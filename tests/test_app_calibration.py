"""Tests for the pure helpers in scripts/calibration.py.

Only the helpers are tested (AR(1) generator, coverage counter, synthetic
panel, REAL rule, cache picker); the study itself needs the cached real data
and a few minutes, so it is run by hand and its output lives in
showcase/calibration.md.
"""
from __future__ import annotations

import importlib.util
import json
import os

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def cal():
    spec = importlib.util.spec_from_file_location("calibration", os.path.join(ROOT, "scripts", "calibration.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- ar1 ------------------------------------------------------------------
def test_ar1_shape_and_moments(cal):
    rng = np.random.default_rng(1)
    x = cal.ar1(rng, 20000, phi=0.6, sigma=0.03)
    assert x.shape == (20000,)
    assert abs(x.mean()) < 0.002                       # zero mean
    assert abs(x.std() - 0.03) < 0.003                 # marginal std = sigma, not innovation std
    r1 = np.corrcoef(x[:-1], x[1:])[0, 1]
    assert abs(r1 - 0.6) < 0.03                        # lag-1 autocorrelation = phi


def test_ar1_multi_column_independent(cal):
    rng = np.random.default_rng(2)
    X = cal.ar1(rng, 5000, phi=0.6, sigma=1.0, k=3)
    assert X.shape == (5000, 3)
    c = np.corrcoef(X.T)
    assert np.all(np.abs(c[~np.eye(3, dtype=bool)]) < 0.06)


def test_ar1_phi_zero_is_white(cal):
    rng = np.random.default_rng(3)
    x = cal.ar1(rng, 5000, phi=0.0, sigma=1.0)
    r1 = np.corrcoef(x[:-1], x[1:])[0, 1]
    assert abs(r1) < 0.05


def test_ar1_rejects_nonstationary(cal):
    with pytest.raises(ValueError):
        cal.ar1(np.random.default_rng(0), 10, phi=1.0, sigma=1.0)


# ---- coverage --------------------------------------------------------------
def test_coverage_scalar_target(cal):
    lo = [-1.0, 0.1, -0.5, -2.0]
    hi = [1.0, 0.5, 0.0, -1.0]
    assert cal.coverage(lo, hi, 0.0) == pytest.approx(0.5)   # closed interval: [-0.5, 0] contains 0


def test_coverage_per_interval_target(cal):
    lo = np.array([-0.2, -0.2, -0.2])
    hi = np.array([0.0, 0.0, 0.0])
    assert cal.coverage(lo, hi, [-0.1, 0.05, -0.3]) == pytest.approx(1 / 3)


def test_coverage_empty_is_nan(cal):
    assert np.isnan(cal.coverage([], [], 0.0))


def test_half_widths(cal):
    assert np.allclose(cal.half_widths([-1, 0], [1, 4]), [1.0, 2.0])


# ---- synthetic panel -------------------------------------------------------
def test_synthetic_panel_shapes_and_effect(cal):
    rng = np.random.default_rng(0)
    y, D, pre = cal.synthetic_panel(rng, T=100, m=60, n_pre=70, phi=0.6, amp_ratio=1.3, effect=-0.10)
    assert y.shape == (100,) and D.shape == (60, 100) and pre.shape == (100,)
    assert pre.sum() == 70 and pre.dtype == bool
    assert np.all(np.isfinite(y)) and np.all(np.isfinite(D))
    # same draws without the step: post-period differs by exactly the effect
    y0, _, _ = cal.synthetic_panel(np.random.default_rng(0), T=100, m=60, n_pre=70, phi=0.6, amp_ratio=1.3, effect=0.0)
    assert np.allclose(y[:70], y0[:70])
    assert np.allclose(y[70:] - y0[70:], -0.10)


def test_synthetic_panel_amplitude_mismatch(cal):
    """With amp_ratio = 1.3 the treated seasonal swing is bigger than any donor's on average."""
    rng = np.random.default_rng(5)
    y, D, pre = cal.synthetic_panel(rng, phi=0.0, amp_ratio=1.3, sigma=1e-6)
    swing = lambda v: v.max() - v.min()
    assert swing(y) > 1.2 * np.mean([swing(row) for row in D])


# ---- verdict rule ----------------------------------------------------------
def test_real_rule_direction(cal):
    # negative claimed direction: needs hi < 0
    assert cal.real_rule(-0.2, -0.3, -0.1, 0.05, 0.05, sign=-1)
    assert not cal.real_rule(-0.2, -0.3, 0.01, 0.05, 0.05, sign=-1)   # interval touches 0
    assert not cal.real_rule(-0.2, -0.3, -0.1, 0.20, 0.05, sign=-1)   # placebo too common
    assert not cal.real_rule(-0.02, -0.03, -0.01, 0.05, 0.05, sign=-1)  # below min effect
    # positive effect is not REAL for a negative claim, but is for "either direction"
    assert not cal.real_rule(0.2, 0.1, 0.3, 0.05, 0.05, sign=-1)
    assert cal.real_rule(0.2, 0.1, 0.3, 0.05, 0.05, sign=0)
    assert cal.real_rule(0.2, 0.1, 0.3, 0.05, 0.05, sign=+1)


# ---- cache picker ----------------------------------------------------------
def test_pick_cache_prefers_more_cells_then_coverage(cal, tmp_path):
    def make(name, n_cells, ndvi):
        d = tmp_path / name
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"cells_geojson": [{}] * n_cells, "s2": {"keys": ["NDVI"]}}))
        np.savez(d / "s2.npz", NDVI=ndvi)
    full = np.ones((10, 4))
    patchy = np.ones((10, 4)); patchy[:5, 1:] = np.nan          # donors at 50% coverage
    make("a", 3, patchy)
    make("b", 3, full)
    make("c", 2, full)
    assert os.path.basename(cal.pick_cache(str(tmp_path))) == "b"


def test_pick_cache_empty_raises(cal, tmp_path):
    with pytest.raises(FileNotFoundError):
        cal.pick_cache(str(tmp_path))
