"""Detection power: inject known effects into real, untouched cells and count
how often the method finds them, and how often it 'finds' an effect of zero.

Uses a cached AreaData (data/cache/<key>) so it costs no network. Every donor
cell in turn plays the treated area; a step effect of the given size is added
after the fake event date; the same estimator + verdict logic is applied.
"""
from __future__ import annotations

import glob
import json
import sys
import time

import numpy as np

from src.app.estimator import conformal_interval, fit_ascm, space_placebo
from src.app.prep import binned
from src.app.run import _placebo_selector
from src.app.series import AreaData
from src.app.verdict import ALPHA, MIN_EFFECT, PLACEBO_P_MAX


def main(cache_dir: str | None = None, signal: str = "NDVI", n_units: int = 20,
         effects=(0.0, -0.05, -0.10, -0.20), seed: int = 0, symmetric: bool = True,
         unit_cov_min: float = 0.50):
    """symmetric=True gives every placebo unit the treated unit's own donor
    selection (CRITIQUE #4). Run both ways on the SAME cache to see what the fix
    costs in power and gains in false-alarm control; a single number run on a
    different area than the published table would confound the two."""
    cache_dir = cache_dir or sorted(glob.glob("data/cache/*/"))[-1]
    d = AreaData.load(cache_dir)
    key = "s2" if signal in ("NDVI", "NDWI", "NBR") else "s1"
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
    T = len(dates)
    event = np.datetime64(dates[int(T * 0.7)])  # fake event at 70% of the window
    rng = np.random.default_rng(seed)
    # Coverage threshold for CHOOSING pseudo-treated units. The real feasibility
    # gate is the binned one below (>= 21 donor columns after prep.complete's 0.70
    # rule, >= 20 pre bins); this only decides which cells are worth trying. The
    # two-pass fetch caps scenes per bin, so raw per-observation coverage is lower
    # than a single-window cache's and 0.75 leaves nothing to test.
    cov = np.mean(np.isfinite(V[:, 1:]), axis=0)
    good = np.where(cov >= unit_cov_min)[0] + 1
    if len(good) == 0:
        raise SystemExit(f"{cache_dir}: no control cell reaches {unit_cov_min:.0%} coverage for {signal} "
                         f"(best is {cov.max():.0%})")
    units = rng.choice(good, size=min(n_units, len(good)), replace=False)
    rows = []
    t0 = time.time()
    for eff in effects:
        hits = 0; cant = 0; n = 0
        for u in units:
            cols = [u] + [c for c in range(1, V.shape[1]) if c != u]
            M = V[:, cols].copy()
            M[dates >= event, 0] += eff
            b = binned(dates, M, event, bin_days=10)
            if b.matrix.shape[1] < 21 or b.pre.sum() < 20 or (~b.pre).sum() < 3:
                cant += 1; n += 1; continue
            y = b.matrix[:, 0]; pool = b.matrix[:, 1:].T
            # keep the 60 best pre-fit donors, as the app does
            rm = np.sqrt(np.mean((pool[:, b.pre] - y[b.pre]) ** 2, axis=1))
            D = pool[np.argsort(rm)[:60]]
            f = fit_ascm(y, D, b.pre)
            point = float(np.mean(f.effect[~b.pre]))
            ci = conformal_interval(y, D, b.pre, f.lam, point, max(f.pre_rmse, 1e-3), alpha=ALPHA, n_grid=21)
            kw = {}
            if symmetric:
                kw = {"pool": pool,
                      "select_for": _placebo_selector(pool, b.pre, np.arange(pool.shape[0]), None, 60)}
            sp = space_placebo(y, D, b.pre, f.lam, point, max_units=30, **kw)
            found = (ci.hi < 0 if eff < 0 else (ci.lo > 0 or ci.hi < 0)) and abs(point) >= MIN_EFFECT[signal] and sp.p_value <= PLACEBO_P_MAX
            hits += int(found); n += 1
        rows.append({"signal": signal, "effect": eff, "n": n, "detected": hits, "cant_tell": cant,
                     "rate": round(hits / max(n, 1), 2), "symmetric_placebo": symmetric,
                     "cache": cache_dir, "unit_cov_min": unit_cov_min, "units_tried": int(len(units))})
        print(rows[-1], f"{time.time() - t0:.0f}s", flush=True)
    return rows


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    cache = args[0] if args else None
    sig = args[1] if len(args) > 1 else "NDVI"
    out = {}
    modes = [False] if "--asymmetric" in flags else ([True] if "--symmetric" in flags else [True, False])
    for sym in modes:
        print(f"=== placebo procedure: {'symmetric (CRITIQUE #4 fix)' if sym else 'asymmetric (old)'} ===",
              flush=True)
        out["symmetric" if sym else "asymmetric"] = main(cache, signal=sig, symmetric=sym)
    print(json.dumps(out, indent=1))
