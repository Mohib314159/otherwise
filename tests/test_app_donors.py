"""Tests for src/app/donors.py: automatic donor shortlisting."""
from __future__ import annotations

import numpy as np
import pytest

from src.app.covariates import Covariates
from src.app.donors import select_donors


def _matrix(seed=0, B=40, n=60):
    rng = np.random.default_rng(seed)
    pre = np.zeros(B, dtype=bool); pre[:30] = True
    base = 0.5 + 0.1 * np.sin(np.arange(B) / 5)
    donors = base[:, None] + rng.normal(0, 0.05, size=(B, n))
    treated = donors[:, 0] + rng.normal(0, 0.01, size=B)  # closest to donor 0
    matrix = np.column_stack([treated, donors])
    donor_cov = np.ones(n)
    return matrix, pre, donor_cov, n


def _cov(n, landcover=None, elevation=None):
    if landcover is None:
        landcover = np.full(1 + n, 40)
    if elevation is None:
        elevation = np.full(1 + n, 100.0)
    return Covariates(landcover=landcover, landcover_frac=np.ones(1 + n),
                      elevation=elevation, slope=np.zeros(1 + n), year=2021)


def test_select_donors_ranks_by_pre_rmse():
    matrix, pre, donor_cov, n = _matrix()
    cov = _cov(n)

    sel = select_donors(matrix, pre, donor_cov, cov, k=20)

    assert len(sel.index) == 20
    assert sel.index[0] == 0   # smallest pre-period RMSE
    assert np.all(np.diff(sel.pre_rmse) >= -1e-12)
    assert sel.counts["kept"] == 20
    assert sel.counts["grid"] == 60


def test_select_donors_keeps_only_treated_landcover():
    matrix, pre, donor_cov, n = _matrix()
    lc = np.full(1 + n, 40)
    lc[1:36] = 40    # 35 donors share the treated code
    lc[36:] = 30     # 25 donors have a different code
    cov = _cov(n, landcover=lc)

    sel = select_donors(matrix, pre, donor_cov, cov, k=20)

    kept_codes = lc[sel.index + 1]
    assert np.all(kept_codes == 40)
    assert any("land cover" in note for note in sel.notes)


def test_select_donors_relaxes_landcover_filter_when_pool_too_small():
    matrix, pre, donor_cov, n = _matrix()
    lc = np.full(1 + n, 30)
    lc[0] = 40         # treated cell's code
    lc[1:11] = 40      # only 10 donors share it, below min_pool=30
    cov = _cov(n, landcover=lc)

    sel = select_donors(matrix, pre, donor_cov, cov, k=20)

    assert any("relaxed" in note for note in sel.notes)
    kept_codes = lc[sel.index + 1]
    assert set(np.unique(kept_codes)) != {40}   # other codes let back in


def test_select_donors_elevation_tolerance():
    matrix, pre, donor_cov, n = _matrix()
    elev = np.full(1 + n, 100.0)
    elev[1 + 40:] = 500.0   # last 20 donors far outside the 150 m tolerance
    cov = _cov(n, elevation=elev)

    sel = select_donors(matrix, pre, donor_cov, cov, k=60, elev_tol_m=150.0)

    kept_elev = elev[sel.index + 1]
    assert not np.any(kept_elev == 500.0)


def test_select_donors_without_covariates():
    matrix, pre, donor_cov, n = _matrix()
    sel = select_donors(matrix, pre, donor_cov, None, k=20)
    assert len(sel.index) == 20

    y = matrix[pre, 0]
    D = matrix[pre, 1:]
    rmse = np.sqrt(np.mean((D - y[:, None]) ** 2, axis=0))
    expected = np.argsort(rmse)[:20]
    assert set(sel.index.tolist()) == set(expected.tolist())


def test_select_donors_grid_mismatch_raises():
    matrix, pre, donor_cov, n = _matrix()
    bad_cov = np.ones(n - 5)   # fewer covered cells than matrix columns
    with pytest.raises(AssertionError):
        select_donors(matrix, pre, bad_cov, None, k=5)
