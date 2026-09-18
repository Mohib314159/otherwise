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
from src.app.series import AreaData
from src.app.verdict import ALPHA, MIN_EFFECT, PLACEBO_P_MAX


def main(cache_dir: str | None = None, signal: str = "NDVI", n_units: int = 20,
         effects=(0.0, -0.05, -0.10, -0.20), seed: int = 0):
    cache_dir = cache_dir or sorted(glob.glob("data/cache/*/"))[-1]
    d = AreaData.load(cache_dir)
    ss = d.s2 if signal in ("NDVI", "NDWI", "NBR") else d.s1
    V = ss.values[signal]                      # (T, 1+n)
    dates = ss.dates
    T = len(dates)
    event = np.datetime64(dates[int(T * 0.7)])  # fake event at 70% of the window
    rng = np.random.default_rng(seed)
    cov = np.mean(np.isfinite(V[:, 1:]), axis=0)
    good = np.where(cov >= 0.75)[0] + 1
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
            y = b.matrix[:, 0]; D = b.matrix[:, 1:].T
            # keep the 60 best pre-fit donors, as the app does
            rm = np.sqrt(np.mean((D[:, b.pre] - y[b.pre]) ** 2, axis=1))
            D = D[np.argsort(rm)[:60]]
            f = fit_ascm(y, D, b.pre)
            point = float(np.mean(f.effect[~b.pre]))
            ci = conformal_interval(y, D, b.pre, f.lam, point, max(f.pre_rmse, 1e-3), alpha=ALPHA, n_grid=21)
            sp = space_placebo(y, D, b.pre, f.lam, point, max_units=30)
            found = (ci.hi < 0 if eff < 0 else (ci.lo > 0 or ci.hi < 0)) and abs(point) >= MIN_EFFECT[signal] and sp.p_value <= PLACEBO_P_MAX
            hits += int(found); n += 1
        rows.append({"signal": signal, "effect": eff, "n": n, "detected": hits, "cant_tell": cant,
                     "rate": round(hits / max(n, 1), 2)})
        print(rows[-1], f"{time.time() - t0:.0f}s", flush=True)
    return rows


if __name__ == "__main__":
    rows = main(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(rows, indent=1))
