"""Calibration study of the statistical engine (`src/app/estimator.py`).

Detection power (`scripts/power.py`) asks "how often do we find a planted
effect?". This script asks the complementary questions:

1. Does the 90% conformal interval contain zero about 90% of the time when
   nothing happened (real, untouched donor cells, fake event date)?
2. Does it contain a planted effect about 90% of the time?
3. How often does the in-space placebo call an untouched cell "rare"
   (p <= 0.10) when nothing happened?
4. Do 1-3 hold on synthetic series with AR(1) noise (phi = 0.6) and a treated
   unit whose seasonal amplitude is 1.3x the donors' mean?
5. How sensitive is the verdict's REAL rule to the ridge penalty (lam fixed at
   0, 0.3, 3.0 instead of chosen by holdout)?

No network: uses a cached AreaData under data/cache/ and synthetic series.
Writes showcase/calibration.md. Nothing under src/ is modified.

Run:  python3 scripts/calibration.py [cache_dir]
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
import warnings
from datetime import datetime, timezone

# Multithreaded OpenBLAS turns every ridge solve with >= 100 bins (any VH
# series here) into a 1.5-2.5 s call instead of a millisecond one on this
# 4-core box: thread oversubscription, not arithmetic. One thread is 100x
# faster for these sizes. Must be set before numpy is imported.
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.estimator import conformal_interval, fit_ascm, space_placebo  # noqa: E402
from src.app.prep import binned  # noqa: E402
from src.app.series import AreaData  # noqa: E402
from src.app.verdict import ALPHA, MIN_EFFECT, PLACEBO_P_MAX  # noqa: E402

N_GRID = 21          # conformal grid points (the app's time placebos use 21 too)
MAX_PLACEBO = 30     # in-space placebo units, as scripts/power.py
KEEP_DONORS = 60     # best pre-fit donors kept, as the app and scripts/power.py
PLANTED = {"NDVI": -0.10, "VH": -1.0}


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/test_app_calibration.py)
# ---------------------------------------------------------------------------
def ar1(rng: np.random.Generator, n: int, phi: float, sigma: float, k: int = 1) -> np.ndarray:
    """Stationary zero-mean AR(1) noise with marginal std `sigma`.

    Returns (n,) when k == 1, else (n, k) independent columns. The first value
    is drawn from the stationary distribution so there is no burn-in transient.
    """
    if not (-1.0 < phi < 1.0):
        raise ValueError("phi must satisfy |phi| < 1 for a stationary AR(1)")
    innov_sd = sigma * np.sqrt(1.0 - phi ** 2)
    e = rng.normal(0.0, innov_sd, size=(n, k))
    x = np.empty((n, k))
    x[0] = rng.normal(0.0, sigma, size=k)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + e[t]
    return x[:, 0] if k == 1 else x


def coverage(lo, hi, target) -> float:
    """Fraction of intervals [lo_i, hi_i] that contain target (scalar or per-interval array)."""
    lo = np.asarray(lo, dtype=float)
    hi = np.asarray(hi, dtype=float)
    tgt = np.broadcast_to(np.asarray(target, dtype=float), lo.shape)
    if lo.size == 0:
        return float("nan")
    return float(np.mean((lo <= tgt) & (tgt <= hi)))


def half_widths(lo, hi) -> np.ndarray:
    return (np.asarray(hi, dtype=float) - np.asarray(lo, dtype=float)) / 2.0


def synthetic_panel(rng: np.random.Generator, T: int = 100, m: int = 60, n_pre: int = 70,
                    phi: float = 0.6, amp_ratio: float = 1.3, effect: float = 0.0,
                    period: float = 36.5, sigma: float = 0.03):
    """One treated series and m donors on an NDVI-like scale.

    Every unit = offset + amplitude * seasonal(t) + AR(1) noise. Donor amplitudes
    are spread around 0.15; the treated amplitude is `amp_ratio` times the
    donors' mean amplitude (so with amp_ratio = 1.3 the treated unit is outside
    the donors' convex hull and the convex SCM fit cannot match its seasonality
    exactly). A step of `effect` is added to the treated unit after `n_pre`.
    Returns (y (T,), D (m, T), pre (T,) bool).
    """
    t = np.arange(T)
    season = np.sin(2 * np.pi * t / period)
    amps = rng.normal(0.15, 0.02, size=m)
    offs = rng.normal(0.55, 0.05, size=m)
    D = offs[:, None] + amps[:, None] * season[None, :] + ar1(rng, T, phi, sigma, k=m).T
    y = 0.55 + amp_ratio * amps.mean() * season + ar1(rng, T, phi, sigma)
    pre = np.zeros(T, dtype=bool)
    pre[:n_pre] = True
    y = y.copy()
    y[~pre] += effect
    return y, D, pre


def real_rule(point: float, lo: float, hi: float, placebo_p: float, min_effect: float,
              sign: int = -1) -> bool:
    """The verdict's REAL rule (src/app/verdict.py): interval excludes 0 in the
    claimed direction, |point| >= min_effect, in-space placebo p <= 0.10.
    sign = 0 accepts either direction (how scripts/power.py counts null alarms)."""
    if sign < 0:
        excl = hi < 0
    elif sign > 0:
        excl = lo > 0
    else:
        excl = lo > 0 or hi < 0
    return bool(excl and abs(point) >= min_effect and placebo_p <= PLACEBO_P_MAX)


def pick_cache(root: str = "data/cache") -> str:
    """Directory with the most donor cells in meta.json; ties broken by the
    number of NDVI donors with >= 75% coverage (so the pool is genuinely usable)."""
    best, best_key = None, None
    for d in sorted(glob.glob(os.path.join(root, "*/"))):
        with open(os.path.join(d, "meta.json")) as f:
            meta = json.load(f)
        n_cells = len(meta.get("cells_geojson", []))
        n_good = -1
        if meta.get("s2") is not None:
            z = np.load(os.path.join(d, "s2.npz"))
            if "NDVI" in z:
                n_good = int((np.mean(np.isfinite(z["NDVI"][:, 1:]), axis=0) >= 0.75).sum())
        key = (n_cells, n_good)
        if best_key is None or key > best_key:
            best, best_key = os.path.normpath(d), key
    if best is None:
        raise FileNotFoundError(f"no cache directories under {root}")
    return best


# ---------------------------------------------------------------------------
# One unit through the app's estimator
# ---------------------------------------------------------------------------
def analyse(y: np.ndarray, D: np.ndarray, pre: np.ndarray, lam: float | None,
            min_effect: float, target: float) -> dict:
    f = fit_ascm(y, D, pre, lam=lam)
    point = float(np.mean(f.effect[~pre]))
    ci = conformal_interval(y, D, pre, f.lam, point, max(f.pre_rmse, 1e-3), alpha=ALPHA, n_grid=N_GRID)
    sp = space_placebo(y, D, pre, f.lam, point, max_units=MAX_PLACEBO)
    return {
        "lam": f.lam, "pre_rmse": f.pre_rmse, "point": point, "lo": ci.lo, "hi": ci.hi,
        "p_zero": ci.p_zero, "placebo_p": sp.p_value, "degenerate": ci.lo == ci.hi,
        "covers_target": ci.lo <= target <= ci.hi, "covers_point": ci.lo <= point <= ci.hi,
        "real_dir": real_rule(point, ci.lo, ci.hi, sp.p_value, min_effect, sign=-1),
        "real_any": real_rule(point, ci.lo, ci.hi, sp.p_value, min_effect, sign=0),
        "excl0_any": ci.lo > 0 or ci.hi < 0,
        "n_pre": int(pre.sum()), "n_post": int((~pre).sum()), "n_donors": int(D.shape[0]),
    }


def real_units(d: AreaData, signal: str, n_units: int, seed: int):
    """Same unit choice as scripts/power.py: donors with >= 75% raw coverage."""
    ss = d.s2 if signal in ("NDVI", "NDWI", "NBR") else d.s1
    V = ss.values[signal]
    dates = ss.dates.astype("datetime64[D]")
    event = np.datetime64(dates[int(len(dates) * 0.7)])
    rng = np.random.default_rng(seed)
    cov = np.mean(np.isfinite(V[:, 1:]), axis=0)
    good = np.where(cov >= 0.75)[0] + 1
    units = rng.choice(good, size=min(n_units, len(good)), replace=False)
    return V, dates, event, units


def real_unit_matrix(V, dates, event, u, effect):
    cols = [u] + [c for c in range(1, V.shape[1]) if c != u]
    M = V[:, cols].copy()
    M[dates >= event, 0] += effect
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)       # all-NaN bins are expected
        b = binned(dates, M, event, bin_days=10)
    if b.matrix.shape[1] < 21 or b.pre.sum() < 20 or (~b.pre).sum() < 3:
        return None
    y = b.matrix[:, 0]
    D = b.matrix[:, 1:].T
    rm = np.sqrt(np.mean((D[:, b.pre] - y[b.pre]) ** 2, axis=1))
    D = D[np.argsort(rm)[:KEEP_DONORS]]
    return y, D, b.pre


def run_real(d: AreaData, signal: str, effect: float, lam: float | None, n_units: int, seed: int) -> list[dict]:
    V, dates, event, units = real_units(d, signal, n_units, seed)
    rows = []
    for u in units:
        got = real_unit_matrix(V, dates, event, u, effect)
        if got is None:
            continue
        y, D, pre = got
        r = analyse(y, D, pre, lam, MIN_EFFECT[signal], effect)
        r["unit"] = int(u)
        rows.append(r)
    return rows


def run_synthetic(phi: float, amp_ratio: float, effect: float, n_rep: int, seed: int,
                  lam: float | None = None) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n_rep):
        y, D, pre = synthetic_panel(rng, phi=phi, amp_ratio=amp_ratio, effect=effect)
        rows.append(analyse(y, D, pre, lam, MIN_EFFECT["NDVI"], effect))
    return rows


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------
def summarise(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    lo = np.array([r["lo"] for r in rows]); hi = np.array([r["hi"] for r in rows])
    hw = half_widths(lo, hi)
    return {
        "n": len(rows),
        "cover_target": float(np.mean([r["covers_target"] for r in rows])),
        "cover_point": float(np.mean([r["covers_point"] for r in rows])),
        "median_hw": float(np.median(hw)),
        "degenerate": int(sum(r["degenerate"] for r in rows)),
        "placebo_fa": float(np.mean([r["placebo_p"] <= PLACEBO_P_MAX for r in rows])),
        "excl0_any": float(np.mean([r["excl0_any"] for r in rows])),
        "real_dir": int(sum(r["real_dir"] for r in rows)),
        "real_any": int(sum(r["real_any"] for r in rows)),
        "median_point": float(np.median([r["point"] for r in rows])),
        "median_pre_rmse": float(np.median([r["pre_rmse"] for r in rows])),
        "lams": sorted(set(round(r["lam"], 3) for r in rows)),
        "lam_counts": {str(k): int(v) for k, v in zip(*np.unique([r["lam"] for r in rows], return_counts=True))},
        "n_pre": int(np.median([r["n_pre"] for r in rows])),
        "n_post": int(np.median([r["n_post"] for r in rows])),
    }


def pct(x: float) -> str:
    return "n/a" if not np.isfinite(x) else f"{100 * x:.0f}%"


def frac(k: int, n: int) -> str:
    return f"{k}/{n} ({pct(k / n) if n else 'n/a'})"


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def unit(signal: str) -> str:
    return " dB" if signal in ("VV", "VH", "RATIO") else ""


def fmt(v: float, signal: str) -> str:
    return f"{v:+.2f}{unit(signal)}" if signal in ("VV", "VH", "RATIO") else f"{v:+.3f}"


# ---------------------------------------------------------------------------
def main(cache_dir: str | None = None, n_units: int = 30, n_rep: int = 30, seed: int = 0,
         out_path: str = "showcase/calibration.md") -> dict:
    t0 = time.time()
    cache_dir = cache_dir or pick_cache()
    d = AreaData.load(cache_dir)
    signals = ("NDVI", "VH")
    res: dict = {"cache": cache_dir, "n_units": n_units, "n_rep": n_rep, "seed": seed}

    # Q1-3 and the data-driven-lam row of Q5: real cells, null and planted.
    real: dict = {}
    for s in signals:
        real[(s, 0.0)] = run_real(d, s, 0.0, None, n_units, seed)
        real[(s, PLANTED[s])] = run_real(d, s, PLANTED[s], None, n_units, seed)
        print(f"real {s}: null {summarise(real[(s, 0.0)])['cover_target']:.2f} cover, "
              f"planted {summarise(real[(s, PLANTED[s])])['cover_target']:.2f} cover, {time.time() - t0:.0f}s", flush=True)

    # Q4: synthetic, iid (phi=0, no mismatch) as reference, then AR(1) + amplitude mismatch.
    synth: dict = {}
    for name, phi, amp in (("iid, matched amplitude", 0.0, 1.0),
                           ("AR(1) phi=0.6, matched amplitude", 0.6, 1.0),
                           ("iid, treated amplitude 1.3x", 0.0, 1.3),
                           ("AR(1) phi=0.6, treated amplitude 1.3x", 0.6, 1.3)):
        for eff in (0.0, PLANTED["NDVI"]):
            synth[(name, eff)] = run_synthetic(phi, amp, eff, n_rep, seed)
        print(f"synthetic {name}: {time.time() - t0:.0f}s", flush=True)

    # Q5: fixed ridge penalties on the real null cells.
    fixed: dict = {}
    for s in signals:
        for lam in (0.0, 0.3, 3.0):
            fixed[(s, lam)] = run_real(d, s, 0.0, lam, n_units, seed)
        print(f"fixed-lam {s}: {time.time() - t0:.0f}s", flush=True)

    res["runtime_s"] = time.time() - t0
    md = render(res, d, real, synth, fixed)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(md)
    print(f"wrote {out_path} in {res['runtime_s']:.0f}s")
    return {"real": {f"{k[0]}@{k[1]}": summarise(v) for k, v in real.items()},
            "synthetic": {f"{k[0]}@{k[1]}": summarise(v) for k, v in synth.items()},
            "fixed": {f"{k[0]}@lam={k[1]}": summarise(v) for k, v in fixed.items()},
            **res}


def render(res, d: AreaData, real, synth, fixed) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    signals = ("NDVI", "VH")
    S = {k: summarise(v) for k, v in real.items()}
    Y = {k: summarise(v) for k, v in synth.items()}
    F = {k: summarise(v) for k, v in fixed.items()}
    n_cells = len(d.cells_geojson)
    L = []
    L.append("# Calibration of the estimator\n")
    L.append(f"Generated {now} at commit `{git_head()}` by `scripts/calibration.py` "
             f"(cache `{res['cache']}`, {n_cells} donor cells, {d.start} to {d.end}, "
             f"{res['n_units']} real units per signal, {res['n_rep']} synthetic replicates, seed {res['seed']}, "
             f"runtime {res['runtime_s']:.0f} s).\n")
    L.append("Set-up, identical to `scripts/power.py`: each chosen donor cell plays the area, the fake event is at "
             "70% of the window, series are binned to 10 days anchored on the event, the 60 donors with the "
             "lowest pre-event RMSE are kept, the augmented SCM is fitted with the holdout-chosen ridge penalty, "
             f"and the 90% conformal interval is inverted on a {N_GRID}-point grid. The in-space placebo uses "
             f"{MAX_PLACEBO} units. \"Coverage\" is the share of intervals that contain the true value "
             "(0 for the null, the planted step otherwise); the target for a 90% interval is about 90%.\n")

    # ---- Q1
    L.append("## 1. Coverage of the 90% interval under the null (real cells, no effect)\n")
    L.append("| Signal | Units | Pre / post bins (median) | Interval contains 0 | Median half-width | Contains its own point estimate | Degenerate (lo = hi) |")
    L.append("|---|---|---|---|---|---|---|")
    for s in signals:
        q = S[(s, 0.0)]
        L.append(f"| {s} | {q['n']} | {q['n_pre']} / {q['n_post']} | {pct(q['cover_target'])} | "
                 f"{q['median_hw']:.3f}{unit(s)} | {pct(q['cover_point'])} | {q['degenerate']} |")
    L.append("")
    L.append(reading_q1(S, signals))

    # ---- Q2
    L.append("## 2. Coverage with a planted step (real cells)\n")
    L.append("| Signal | Planted effect | Units | Interval contains planted value | Median half-width | Median point estimate | Called REAL (claimed direction) |")
    L.append("|---|---|---|---|---|---|---|")
    for s in signals:
        q = S[(s, PLANTED[s])]
        L.append(f"| {s} | {fmt(PLANTED[s], s)} | {q['n']} | {pct(q['cover_target'])} | {q['median_hw']:.3f}{unit(s)} | "
                 f"{fmt(q['median_point'], s)} | {frac(q['real_dir'], q['n'])} |")
    L.append("")
    L.append(reading_q2(S, signals))

    # ---- Q3
    L.append("## 3. In-space placebo false-alarm rate (real cells, no effect)\n")
    L.append("| Signal | Units | Placebo p <= 0.10 | Interval excludes 0 (either side) | Full REAL rule, either direction | Full REAL rule, claimed (negative) direction |")
    L.append("|---|---|---|---|---|---|")
    for s in signals:
        q = S[(s, 0.0)]
        L.append(f"| {s} | {q['n']} | {pct(q['placebo_fa'])} | {pct(q['excl0_any'])} | "
                 f"{frac(q['real_any'], q['n'])} | {frac(q['real_dir'], q['n'])} |")
    L.append("")
    L.append(reading_q3(S, signals))

    # ---- Q4
    L.append("## 4. Synthetic series: autocorrelated noise and a seasonal amplitude mismatch\n")
    L.append(f"60 donors, 100 steps, 70 pre-event, {res['n_rep']} replicates per row. Units are NDVI-like "
             "(seasonal amplitude about 0.15, noise std 0.03, planted step -0.10). AR(1) noise has phi = 0.6; "
             "\"1.3x\" means the treated unit's seasonal amplitude is 1.3 times the donors' mean, which puts it "
             "outside the donors' convex hull.\n")
    L.append("| Series | Effect | Interval contains truth | Median half-width | Placebo p <= 0.10 | Called REAL (claimed direction) | Chosen lam (count) |")
    L.append("|---|---|---|---|---|---|---|")
    for (name, eff), q in Y.items():
        lam_txt = ", ".join(f"{k}: {v}" for k, v in q["lam_counts"].items())
        L.append(f"| {name} | {eff:+.2f} | {pct(q['cover_target'])} | {q['median_hw']:.3f} | {pct(q['placebo_fa'])} | "
                 f"{frac(q['real_dir'], q['n'])} | {lam_txt} |")
    L.append("")
    L.append(reading_q4(Y))

    # ---- Q5
    L.append("## 5. Sensitivity of the REAL rule to the ridge penalty (real cells, no effect)\n")
    L.append("| Signal | Ridge penalty | Units | Interval contains 0 | Median half-width | Placebo p <= 0.10 | REAL, either direction | REAL, claimed direction | Median pre-event RMSE |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for s in signals:
        q = S[(s, 0.0)]
        lam_txt = "holdout choice (" + ", ".join(f"{k}: {v}" for k, v in q["lam_counts"].items()) + ")"
        L.append(f"| {s} | {lam_txt} | {q['n']} | {pct(q['cover_target'])} | {q['median_hw']:.3f}{unit(s)} | "
                 f"{pct(q['placebo_fa'])} | {frac(q['real_any'], q['n'])} | {frac(q['real_dir'], q['n'])} | {q['median_pre_rmse']:.3f}{unit(s)} |")
        for lam in (0.0, 0.3, 3.0):
            q = F[(s, lam)]
            L.append(f"| {s} | {lam:g} | {q['n']} | {pct(q['cover_target'])} | {q['median_hw']:.3f}{unit(s)} | "
                     f"{pct(q['placebo_fa'])} | {frac(q['real_any'], q['n'])} | {frac(q['real_dir'], q['n'])} | {q['median_pre_rmse']:.3f}{unit(s)} |")
    L.append("")
    L.append(reading_q5(S, F, signals))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# Plain-English readings. They are computed from the numbers, so they cannot
# drift from the tables.
# ---------------------------------------------------------------------------
def _cal_word(c: float, target: float = 0.90, slack: float = 0.05) -> str:
    if c >= target - slack:
        return "calibrated"
    if c >= 0.75:
        return "somewhat under-covered"
    return "badly under-covered"


def reading_q1(S, signals) -> str:
    parts = []
    for s in signals:
        q = S[(s, 0.0)]
        w = _cal_word(q["cover_target"])
        parts.append(f"{s}: the null interval contained 0 in {pct(q['cover_target'])} of {q['n']} untouched cells "
                     f"(target about 90%), so it is {w}; the typical half-width is {q['median_hw']:.3f}{unit(s)}.")
        if q["cover_point"] < 0.9:
            parts.append(f"In {pct(1 - q['cover_point'])} of {s} cells the interval did not even contain its own point estimate: "
                         "the point estimate comes from a fit on the pre-period only, while the conformal test refits on all periods, "
                         "and with 60 donors picked for their pre-fit those two fits can disagree. That is a warning sign that the "
                         "displayed interval and the displayed point are answering slightly different questions.")
    worst = min(S[(s, 0.0)]["cover_target"] for s in signals)
    if worst < 0.85:
        parts.append("Reading: the interval is narrower than its 90% label on real data. A conservative fix is to report the "
                     "interval at alpha = 0.05 (a 95% test inverted gives a wider band) or to require both the interval and the "
                     "placebo to agree before calling anything REAL, which the verdict already does; nothing here argues for "
                     "loosening any threshold.")
    else:
        parts.append("Reading: on real untouched cells the 90% label holds (within the resolution of 30 units, one cell is about 3 points).")
    return " ".join(parts) + "\n"


def reading_q2(S, signals) -> str:
    parts = []
    for s in signals:
        q = S[(s, PLANTED[s])]
        parts.append(f"{s}: with a planted {fmt(PLANTED[s], s)} step the interval contained the planted value in "
                     f"{pct(q['cover_target'])} of cells ({_cal_word(q['cover_target'])}), the median point estimate was "
                     f"{fmt(q['median_point'], s)}, and the full verdict rule called {frac(q['real_dir'], q['n'])} REAL.")
    parts.append("Reading: coverage with an effect should match coverage without one, because the conformal test subtracts the "
                 "hypothesised effect and refits; a gap between this table and table 1 would mean the step itself is being "
                 "partly absorbed by the counterfactual fit.")
    return " ".join(parts) + "\n"


def reading_q3(S, signals) -> str:
    parts = []
    for s in signals:
        q = S[(s, 0.0)]
        ok = "within" if q["placebo_fa"] <= 0.10 + 1e-9 else "above"
        parts.append(f"{s}: the in-space placebo returned p <= 0.10 for {pct(q['placebo_fa'])} of untouched cells, "
                     f"{ok} the 10% target. Combined with the interval and the 0.05 / 1 dB minimum, the full REAL rule fired "
                     f"{frac(q['real_any'], q['n'])} times in either direction and {frac(q['real_dir'], q['n'])} in the claimed direction.")
    parts.append("Reading: the placebo is a rank among about 30 donors, so its p-value floors at 1/31 = 0.03 and its false-alarm "
                 "rate is expected to sit near 10% by construction (3 of 31 ranks pass). The REAL rule's false-alarm rate is "
                 "what matters for the app, and it is the product of three independent-ish gates, which is why it is lower.")
    return " ".join(parts) + "\n"


def reading_q4(Y) -> str:
    rows = {k: v for k, v in Y.items()}
    iid0 = rows[("iid, matched amplitude", 0.0)]
    ar0 = rows[("AR(1) phi=0.6, matched amplitude", 0.0)]
    mis0 = rows[("iid, treated amplitude 1.3x", 0.0)]
    both0 = rows[("AR(1) phi=0.6, treated amplitude 1.3x", 0.0)]
    both1 = rows[("AR(1) phi=0.6, treated amplitude 1.3x", PLANTED["NDVI"])]
    parts = [
        f"With iid noise and a matched treated unit the null interval covers 0 in {pct(iid0['cover_target'])} of replicates "
        f"(the textbook case). Adding AR(1) noise alone gives {pct(ar0['cover_target'])}; the amplitude mismatch alone gives "
        f"{pct(mis0['cover_target'])}; both together give {pct(both0['cover_target'])} on the null and "
        f"{pct(both1['cover_target'])} with the planted -0.10 step, with placebo false alarms at {pct(both0['placebo_fa'])} "
        f"and the full REAL rule firing {frac(both0['real_dir'], both0['n'])} times on the null."
    ]
    if ar0["cover_target"] >= 0.85 and both0["cover_target"] >= 0.85:
        parts.append("Reading: the moving-block permutation handles phi = 0.6 autocorrelation and the ridge correction absorbs the "
                     "amplitude mismatch; the interval stays calibrated in this synthetic setting.")
    else:
        culprit = []
        if ar0["cover_target"] < 0.85:
            culprit.append("autocorrelated noise")
        if mis0["cover_target"] < 0.85:
            culprit.append("the amplitude mismatch")
        parts.append(f"Reading: coverage drops below the 90% label when {' and '.join(culprit) or 'both are combined'}. "
                     "The conformal test permutes cyclic blocks of the residual sequence, which is valid when the post-period "
                     "residuals are exchangeable with the pre-period ones; a treated unit that the donors cannot span leaves "
                     "seasonal structure in the residuals, and that structure is not exchangeable. A conservative fix is to "
                     "flag (CAN'T TELL) any fit whose pre-period residuals show significant lag-1 autocorrelation or seasonality, "
                     "rather than to trust the interval.")
    return " ".join(parts) + "\n"


def reading_q5(S, F, signals) -> str:
    parts = []
    for s in signals:
        base = S[(s, 0.0)]
        fa = {lam: F[(s, lam)] for lam in (0.0, 0.3, 3.0)}
        worst_lam = max(fa, key=lambda l: fa[l]["real_any"])
        parts.append(f"{s}: with the holdout-chosen penalty the REAL rule fired {frac(base['real_any'], base['n'])} times on untouched "
                     f"cells; fixing lam at 0 / 0.3 / 3.0 gave {fa[0.0]['real_any']} / {fa[0.3]['real_any']} / {fa[3.0]['real_any']} "
                     f"false alarms (either direction) and null coverage of {pct(fa[0.0]['cover_target'])} / "
                     f"{pct(fa[0.3]['cover_target'])} / {pct(fa[3.0]['cover_target'])}; the worst penalty was lam = {worst_lam:g}.")
    spread = max(abs(F[(s, l)]["real_any"] - S[(s, 0.0)]["real_any"]) for s in signals for l in (0.0, 0.3, 3.0))
    if spread <= 2:
        parts.append("Reading: the false-alarm rate moves by at most two cells across a 10x range of ridge penalty, so the "
                     "verdict is not sensitive to the exact lam; the holdout choice is fine as it is.")
    else:
        parts.append("Reading: the false-alarm rate depends on the penalty by more than two cells. The conservative reading is to keep "
                     "the holdout choice but report the verdict as CAN'T TELL whenever it flips between the grid's neighbouring "
                     "penalties, rather than to pick whichever lam happens to give the strongest result.")
    return " ".join(parts) + "\n"


if __name__ == "__main__":
    out = main(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps({k: v for k, v in out.items() if k in ("real", "synthetic", "fixed")}, indent=1, default=str))
