"""Demonstrate the break-date search on real cached Sentinel-2 NDVI cells.

Loads the newest data/cache/<key> (no network), takes 10 random donor cells as
"areas": 5 get a -0.2 NDVI step injected at a random bin inside the search
window, 5 are left untouched. Each is searched against the other cells and the
table shows where the search put the break and whether the placebo-of-the-
maximum test called it.
"""
from __future__ import annotations

import glob
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.breakdate import find_break, default_window, refine_uncertainty  # noqa: E402
from src.app.prep import binned
from src.app.series import AreaData


def main(cache_dir: str | None = None, signal: str = "NDVI", seed: int = 0,
         n_donors: int = 80, step: float = -0.2, max_units: int = 40):
    cache_dir = cache_dir or max(glob.glob("data/cache/*/"), key=os.path.getmtime)
    d = AreaData.load(cache_dir)
    V = d.s2.values[signal]                                   # (T, 1+n)
    dates = d.s2.dates.astype("datetime64[D]")
    anchor = np.datetime64(dates[len(dates) // 2])            # nominal, only fixes the bin grid
    rng = np.random.default_rng(seed)
    cov = np.mean(np.isfinite(V[:, 1:]), axis=0)
    good = np.where(cov >= 0.75)[0] + 1
    units = rng.choice(good, size=10, replace=False)
    print(f"cache {cache_dir}  obs {V.shape[0]}  cells {V.shape[1] - 1}  signal {signal}")
    print(f"{'cell':>5} {'bins':>5} {'window':>9} {'true':>5} {'found':>5} {'range':>9} "
          f"{'effect':>7} {'S_max':>6} {'p_search':>8} {'detected':>8}")
    t0 = time.time()
    for i, u in enumerate(units):
        cols = [u] + [c for c in range(1, V.shape[1]) if c != u]
        b = binned(dates, V[:, cols], anchor, bin_days=10)
        M = b.matrix.copy()
        B = M.shape[0]
        s0, s1 = default_window(B)
        # keep the donors that track the area best before the search window (uses no post data)
        rm = np.sqrt(np.mean((M[:s0, 1:] - M[:s0, :1]) ** 2, axis=0))
        M = np.column_stack([M[:, 0], M[:, 1:][:, np.argsort(rm)[:n_donors]]])
        inject = i < 5
        t_true = int(rng.integers(s0, s1)) if inject else None
        if inject:
            M[t_true:, 0] += step
        r = find_break(M, b.dates, max_units=max_units, min_effect=0.05)
        lo, hi = refine_uncertainty(r.curve, r.window[0])
        print(f"{u:>5} {B:>5} {f'{s0}-{s1}':>9} {('-' if t_true is None else t_true):>5} {r.index:>5} "
              f"{f'{lo}-{hi}':>9} {r.point:>+7.3f} {r.stat:>6.2f} {r.p_search:>8.3f} {str(r.detected):>8}")
    print(f"{time.time() - t0:.1f}s for 10 searches")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
