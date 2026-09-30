"""Detection power: inject known effects into real, untouched cells and count
how often the method finds them, and how often it 'finds' an effect of zero.

Uses a cached AreaData (data/cache/<key>) so it costs no network. Every donor
cell in turn plays the treated area; a step effect of the given size is added
after the fake event date.

Each pseudo-treated unit is judged by the product's own rule (CRITIQUE #9): its
SignalResult is built by `run.signal_result` -- the helper `run._analyse` uses,
so the same conformal interval, 60-unit space placebo and three in-time
placebos -- and handed to `verdict.combine`. A unit counts as detected only when
that returns REAL, so the pre-fit gate (with its 4x bypass), the MIN_DONORS /
pre / post bin minima, the "controls shifted" rule and the degenerate-interval
rule all apply. `old_gate_detected` still reports the previous three-condition
gate on the same units, so the two rules can be compared on one run.

Not yet production-identical (the rest of CRITIQUE #9): the donor pool is the
60 best pre-fit cells, not `donors.select_donors` with its land-cover and
elevation filters and spillover buffer, and the injected effect is a constant
step.
"""
from __future__ import annotations

import glob
import json
import sys
import time

import numpy as np

from src.app.prep import binned
from src.app.run import BIN_DAYS, _placebo_selector, _time_selector, signal_result
from src.app.verdict import MIN_EFFECT, PLACEBO_P_MAX, combine

OPTICAL_EFFECTS = (0.0, -0.05, -0.10, -0.20)     # index units
RADAR_EFFECTS = (0.0, -0.5, -1.0, -2.0)          # dB
RADAR = ("VV", "VH", "RATIO")
N_BEST = 60                                      # pre-fit donors kept per unit


def default_effects(signal: str) -> tuple[float, ...]:
    """Injected step sizes in the signal's own units: dB for radar, index for
    optical. (Running VH with the NDVI defaults injected 0.05-0.2 dB, far below
    MIN_EFFECT, so every radar row measured the null.)"""
    return RADAR_EFFECTS if signal.upper() in RADAR else OPTICAL_EFFECTS


def old_gate(res, eff: float) -> bool:
    """The rule power.py used before CRITIQUE #9, kept only for comparison."""
    ci_ok = res.hi < 0 if eff < 0 else (res.lo > 0 or res.hi < 0)
    return bool(ci_ok and abs(res.point) >= MIN_EFFECT[res.signal] and res.placebo_p <= PLACEBO_P_MAX)


def judge_unit(dates, M, event, signal: str, eff: float, symmetric: bool = True):
    """Judge column 0 of M (effect already injected) the way the app judges an
    area. Returns (status, SignalResult | None, old_gate_detected).

    The expected sign is the sign of the injected effect (0 for the null row), so
    the null row is judged two-sided, as the old gate did. A unit too thin to fit
    is CANT_TELL, which is what `decide` returns for those counts anyway."""
    b = binned(dates, M, event, bin_days=BIN_DAYS)
    if b.matrix.shape[1] < 21 or b.pre.sum() < 20 or (~b.pre).sum() < 3:
        return "CANT_TELL", None, False
    y = b.matrix[:, 0]; pool = b.matrix[:, 1:].T
    # keep the 60 best pre-fit donors (the app uses select_donors; see docstring)
    rm = np.sqrt(np.mean((pool[:, b.pre] - y[b.pre]) ** 2, axis=1))
    D = pool[np.argsort(rm)[:N_BEST]]
    kw = {}
    if symmetric:
        # With no covariates select_donors is "N_BEST best pre-fit cells", the rule
        # used for D above, so both placebos re-run exactly this unit's selection.
        kw = {"pool": pool,
              "select_for": _placebo_selector(pool, b.pre, np.arange(pool.shape[0]), None, N_BEST),
              "select_at": _time_selector(b.matrix, np.ones(pool.shape[0]), None, N_BEST)}
    sensor = "S1" if signal.upper() in RADAR else "S2"
    res, *_ = signal_result(y, D, b.pre, signal, sensor, int(np.sign(eff)), **kw)
    v = combine(res, None, "other", "after the injected step")
    return v.status, res, old_gate(res, eff)


def evaluate(V, dates, signal: str = "NDVI", n_units: int = 20, effects=None, seed: int = 0,
             symmetric: bool = True, unit_cov_min: float = 0.50, units=None, log=print):
    """V: (T, 1+n), column 0 unused, columns 1.. real control cells.
    `units` overrides the random choice of pseudo-treated columns (tests)."""
    effects = default_effects(signal) if effects is None else tuple(effects)
    dates = np.asarray(dates).astype("datetime64[D]")
    T = len(dates)
    event = np.datetime64(dates[int(T * 0.7)])  # fake event at 70% of the window
    rng = np.random.default_rng(seed)
    if units is None:
        # Coverage threshold for CHOOSING pseudo-treated units. The real
        # feasibility gate is the binned one in judge_unit (>= 21 donor columns
        # after prep.complete's 0.70 rule, >= 20 pre bins); this only decides
        # which cells are worth trying. The two-pass fetch caps scenes per bin, so
        # raw per-observation coverage is lower than a single-window cache's and
        # 0.75 leaves nothing to test.
        cov = np.mean(np.isfinite(V[:, 1:]), axis=0)
        good = np.where(cov >= unit_cov_min)[0] + 1
        if len(good) == 0:
            raise SystemExit(f"no control cell reaches {unit_cov_min:.0%} coverage for {signal} "
                             f"(best is {cov.max():.0%})")
        units = rng.choice(good, size=min(n_units, len(good)), replace=False)
    rows = []
    t0 = time.time()
    for eff in effects:
        counts = {"REAL": 0, "NOT_REAL": 0, "CANT_TELL": 0}
        old = tflag = n = 0
        for u in units:
            cols = [u] + [c for c in range(1, V.shape[1]) if c != u]
            M = V[:, cols].copy()
            M[dates >= event, 0] += eff
            status, res, was_old = judge_unit(dates, M, event, signal, eff, symmetric)
            counts[status] += 1; n += 1
            old += int(was_old)
            tflag += int(status == "REAL" and any(res.time_placebo_flags))
        rows.append({"signal": signal, "effect": eff, "n": n, "detected": counts["REAL"],
                     "not_real": counts["NOT_REAL"], "cant_tell": counts["CANT_TELL"],
                     "rate": round(counts["REAL"] / max(n, 1), 2),
                     "real_with_time_placebo_flag": tflag, "old_gate_detected": old,
                     "decision_rule": "verdict.combine",
                     "symmetric_placebo": symmetric, "unit_cov_min": unit_cov_min,
                     "units_tried": int(len(units))})
        log(rows[-1], f"{time.time() - t0:.0f}s")
    return rows


def main(cache_dir: str | None = None, signal: str = "NDVI", n_units: int = 20,
         effects=None, seed: int = 0, symmetric: bool = True,
         unit_cov_min: float = 0.50):
    """symmetric=True gives every placebo unit the treated unit's own donor
    selection (CRITIQUE #4). Run both ways on the SAME cache to see what the fix
    costs in power and gains in false-alarm control; a single number run on a
    different area than the published table would confound the two.
    effects=None picks default_effects(signal): dB for radar, index for optical."""
    from src.app.series import AreaData
    cache_dir = cache_dir or sorted(glob.glob("data/cache/*/"))[-1]
    d = AreaData.load(cache_dir)
    key = "s1" if signal.upper() in RADAR else "s2"
    # Two AreaData shapes. The single-window fetch ("full") puts the treated area
    # and every cell in one matrix, column 0 being the treated area. The two-pass
    # fetch ("live", and wide mode) reads the controls separately, so the cells
    # live in `groups`, each group on its own date axis, and `d.s2` holds the
    # treated area ALONE. This test only ever uses control cells as pseudo-treated
    # units, so take the cells from whichever place they are -- reading the
    # combined matrix on a two-pass cache silently yields zero donors.
    if d.groups:
        usable = [g for g in d.groups if g.get(key) is not None and g[key].values[signal].shape[1] >= 21]
        if not usable:
            raise SystemExit(f"{cache_dir}: no control group in this cache has >= 21 cells for {signal}")
        g = max(usable, key=lambda g: g[key].values[signal].shape[1])
        cells = g[key].values[signal]                  # (T, n) controls only
        dates = g[key].dates.astype("datetime64[D]")
        V = np.column_stack([np.full(len(dates), np.nan), cells])   # pad a treated slot
        print(f"  cells from control group ({cells.shape[1]} cells, own date axis)", flush=True)
    else:
        ss = d.s2 if key == "s2" else d.s1
        V = ss.values[signal]                  # (T, 1+n)
        dates = ss.dates.astype("datetime64[D]")
    rows = evaluate(V, dates, signal=signal, n_units=n_units, effects=effects, seed=seed,
                    symmetric=symmetric, unit_cov_min=unit_cov_min,
                    log=lambda *a: print(*a, flush=True))
    for r in rows:
        r["cache"] = cache_dir
    return rows


def parse_args(argv):
    """power.py [cache_dir] [signal] [--symmetric | --asymmetric] [--effects=a,b,c]

    Without --effects the defaults follow the signal: dB for VV/VH/RATIO."""
    args = [a for a in argv if not a.startswith("--")]
    flags = {a.split("=", 1)[0]: (a.split("=", 1)[1] if "=" in a else "") for a in argv if a.startswith("--")}
    cache = args[0] if args else None
    sig = args[1] if len(args) > 1 else "NDVI"
    effects = (tuple(float(x) for x in flags["--effects"].split(",")) if flags.get("--effects")
               else default_effects(sig))
    modes = [False] if "--asymmetric" in flags else ([True] if "--symmetric" in flags else [True, False])
    return cache, sig, effects, modes


if __name__ == "__main__":
    cache, sig, effects, modes = parse_args(sys.argv[1:])
    out = {}
    for sym in modes:
        print(f"=== placebo procedure: {'symmetric (CRITIQUE #4 fix)' if sym else 'asymmetric (old)'} ===",
              flush=True)
        out["symmetric" if sym else "asymmetric"] = main(cache, signal=sig, effects=effects, symmetric=sym)
    print(json.dumps(out, indent=1))
