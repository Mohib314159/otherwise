"""Tests for src/app/prep.py: binning and completion of raw series into the
regular matrix the estimator needs."""
from __future__ import annotations

import numpy as np

from src.app.prep import bin_series, binned, complete


def test_bin_series_boundary_on_event_and_counts():
    dates = np.array("2023-01-01", dtype="datetime64[D]") + np.arange(30)
    values = np.zeros((30, 3))
    values[:, 0] = np.arange(30, dtype=float)
    values[:, 1] = 1.0
    values[:, 2] = 2.0
    event = np.datetime64("2023-01-15")

    mid, mat, cnt = bin_series(dates, values, event, bin_days=10)

    # one row per 10-day bin
    rel = (dates.astype("datetime64[D]") - event.astype("datetime64[D]")).astype(int)
    k = np.floor_divide(rel, 10)
    ks = np.arange(k.min(), k.max() + 1)
    assert mat.shape[0] == len(ks)
    assert cnt.shape[0] == len(ks)

    # a bin boundary falls exactly on the event: rel==0 for the event's own day,
    # so the bin with k==0 starts precisely at the event date
    event_bin = int(np.where(ks == 0)[0][0])
    # that bin holds day-indices 14..23 (the observations dated on/after the event
    # within the first 10-day window); median of column 0 there is 18.5
    assert mat[event_bin, 0] == 18.5

    # counts equal the number of finite values per bin
    for i, kk in enumerate(ks):
        rows = values[k == kk]
        assert cnt[i, 0] == np.isfinite(rows[:, 0]).sum()
        assert cnt[i, 1] == np.isfinite(rows[:, 1]).sum()


def test_bin_series_ignores_nan_in_median_and_counts():
    dates = np.array("2023-01-01", dtype="datetime64[D]") + np.arange(30)
    values = np.zeros((30, 2))
    values[:, 0] = np.arange(30, dtype=float)
    values[5, 0] = np.nan   # date 2023-01-06
    event = np.datetime64("2023-01-15")

    mid, mat, cnt = bin_series(dates, values, event, bin_days=10)

    rel = (dates.astype("datetime64[D]") - event.astype("datetime64[D]")).astype(int)
    k = np.floor_divide(rel, 10)
    ks = np.arange(k.min(), k.max() + 1)
    bin_of_5 = int(np.where(ks == k[5])[0][0])

    rows = values[k == k[5]][:, 0]
    finite_rows = rows[np.isfinite(rows)]
    assert cnt[bin_of_5, 0] == len(finite_rows)
    assert mat[bin_of_5, 0] == np.median(finite_rows)


def test_complete_drops_empty_rows_interpolates_and_filters_donors():
    n_bins = 12
    mid = np.array("2023-01-01", dtype="datetime64[D]") + np.arange(n_bins) * 10
    event = np.datetime64("2023-01-01") + np.timedelta64(60, "D")

    mat = np.zeros((n_bins, 4))
    cnt = np.ones((n_bins, 4), dtype=int)

    # treated column: no observation (cnt 0) in bins 3 and 7
    mat[:, 0] = np.arange(n_bins, dtype=float)
    cnt[:, 0] = 1
    mat[3, 0] = np.nan; cnt[3, 0] = 0
    mat[7, 0] = np.nan; cnt[7, 0] = 0
    dropped = {3, 7}
    kept_rows = [i for i in range(n_bins) if i not in dropped]

    # donor 1: fully covered
    mat[:, 1] = np.arange(n_bins, dtype=float) * 2

    # donor 2: NaN in 3 of the kept rows
    mat[:, 2] = np.arange(n_bins, dtype=float) * 3
    for pos in (0, 1, 2):
        mat[kept_rows[pos], 2] = np.nan

    # donor 3: NaN in 6 of the kept rows -> below the 0.70 coverage threshold
    mat[:, 3] = np.arange(n_bins, dtype=float) * 5
    for pos in (0, 1, 2, 4, 5, 6):
        mat[kept_rows[pos], 3] = np.nan

    b = complete(mid, mat, cnt, event, min_cov=0.70)

    assert len(b.dates) == len(kept_rows)
    assert b.matrix.shape == (len(kept_rows), 3)   # treated + 2 surviving donors
    assert not np.isnan(b.matrix).any()

    expected_pre = mid[kept_rows] < event.astype("datetime64[D]")
    assert np.array_equal(b.pre, expected_pre)

    # coverage computed the same way the module computes it: over the kept rows
    donors_raw = mat[kept_rows][:, 1:]
    expected_cov = np.isfinite(donors_raw).mean(axis=0)
    assert len(b.donor_cov) == 3
    assert np.allclose(b.donor_cov, expected_cov)
    assert np.allclose(expected_cov, [1.0, 0.7, 0.4], atol=0.05)


def test_binned_wrapper_sets_bin_days_and_shape():
    rng = np.random.default_rng(0)
    n = 120
    dates = np.array("2023-01-01", dtype="datetime64[D]") + np.arange(n)
    values = np.zeros((n, 4))
    for j in range(4):
        values[:, j] = 0.5 + 0.1 * np.sin(np.arange(n) / 10) + rng.normal(0, 0.02, n)
    event = np.datetime64("2023-01-01") + np.timedelta64(60, "D")

    b = binned(dates, values, event)

    assert b.bin_days == 10
    assert b.matrix.shape[0] == len(b.dates)
