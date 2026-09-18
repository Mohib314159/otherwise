"""From per-observation series to the regular, complete matrix the estimator needs.

Bins are anchored on the event date so a boundary falls exactly on it. Within a
bin each column takes the median of its observations. The treated column is
never interpolated: bins without a real treated observation are dropped, so
every point on the chart is evidence. Donor gaps are interpolated linearly
(they are averaged anyway) and donors with poor coverage are dropped.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Binned:
    dates: np.ndarray          # (B,) datetime64[D] bin midpoints, only bins with a treated obs
    matrix: np.ndarray         # (B, 1+n) column 0 = treated, donors interpolated
    n_obs: np.ndarray          # (B,) treated observations per bin
    pre: np.ndarray            # (B,) bool
    donor_cov: np.ndarray      # (n,) coverage of each donor before interpolation
    bin_days: int


def bin_series(dates: np.ndarray, values: np.ndarray, event: np.datetime64,
               bin_days: int = 10) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Median per bin. Returns (bin_mid_dates, matrix (B, N) with NaN, counts (B, N))."""
    d = dates.astype("datetime64[D]")
    rel = (d - event.astype("datetime64[D]")).astype(int)
    k = np.floor_divide(rel, bin_days)
    ks = np.arange(k.min(), k.max() + 1)
    B, N = len(ks), values.shape[1]
    mat = np.full((B, N), np.nan); cnt = np.zeros((B, N), dtype=int)
    for i, kk in enumerate(ks):
        rows = values[k == kk]
        if rows.size == 0:
            continue
        with np.errstate(all="ignore"):
            mat[i] = np.nanmedian(rows, axis=0)
        cnt[i] = np.isfinite(rows).sum(axis=0)
    mid = event.astype("datetime64[D]") + (ks * bin_days + bin_days // 2).astype("timedelta64[D]")
    return mid, mat, cnt


def complete(mid, mat, cnt, event, min_cov: float = 0.70, max_gap_bins: int = 6) -> Binned:
    """Keep bins with a treated observation; drop weak donors; interpolate the rest."""
    keep = cnt[:, 0] > 0
    mid, mat, cnt = mid[keep], mat[keep], cnt[keep]
    pre = mid < event.astype("datetime64[D]")
    donors = mat[:, 1:]
    cov = np.isfinite(donors).mean(axis=0) if len(mid) else np.zeros(donors.shape[1])
    good = cov >= min_cov
    donors = donors[:, good]
    x = np.arange(len(mid))
    for j in range(donors.shape[1]):
        col = donors[:, j]
        ok = np.isfinite(col)
        if ok.all():
            continue
        donors[:, j] = np.interp(x, x[ok], col[ok])
    out = np.column_stack([mat[:, 0], donors]) if donors.size else mat[:, :1]
    return Binned(mid, out, cnt[:, 0], pre, cov, 0)


def binned(dates, values, event, bin_days=10, min_cov=0.70) -> Binned:
    mid, mat, cnt = bin_series(dates, values, event, bin_days)
    b = complete(mid, mat, cnt, event, min_cov)
    b.bin_days = bin_days
    return b
