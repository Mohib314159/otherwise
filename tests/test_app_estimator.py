"""Tests for src/app/estimator.py: augmented SCM + conformal inference + placebos."""
from __future__ import annotations

import numpy as np
import pytest

from src.app.estimator import (
    conformal_interval,
    conformal_p,
    fit_ascm,
    space_placebo,
    time_placebos,
)

LAM_GRID = (0.0, 0.03, 0.1, 0.3, 1.0, 3.0)


def synthetic(T=80, m=30, n_pre=56, effect=0.0, seed=0):
    """Treated series = convex combination of the first 5 donors, all sharing a
    common seasonal shape but with per-donor amplitude/offset and noise. A
    constant `effect` is added to every post-period observation."""
    rng = np.random.default_rng(seed)
    t = np.arange(T)
    seasonal = np.sin(2 * np.pi * t / 24)
    factors = rng.uniform(0.7, 1.3, size=m)
    offsets = rng.normal(0, 0.05, size=m)
    noise = rng.normal(0, 0.04, size=(m, T))
    D = 0.5 + seasonal[None, :] * factors[:, None] + offsets[:, None] + noise

    w = rng.dirichlet(np.ones(5))
    y = (w[:, None] * D[:5]).sum(axis=0) + rng.normal(0, 0.03, size=T)

    pre = np.zeros(T, dtype=bool)
    pre[:n_pre] = True
    y = y.copy()
    y[~pre] += effect
    return y, D, pre


def test_fit_ascm_shapes_and_weights():
    y, D, pre = synthetic()
    f = fit_ascm(y, D, pre)

    assert np.all(f.weights >= -1e-9)
    assert abs(f.weights.sum() - 1.0) < 1e-6
    assert f.synthetic.shape == (80,)
    assert f.effect.shape == (80,)
    assert np.allclose(f.effect, y - f.synthetic)
    assert f.pre_rmse < 0.05
    assert f.lam in LAM_GRID


def test_fit_ascm_lam0_matches_plain_scm():
    y, D, pre = synthetic()
    f = fit_ascm(y, D, pre, lam=0)
    assert np.allclose(f.synthetic, f.synthetic_scm)


def test_fit_ascm_recovers_negative_effect():
    y, D, pre = synthetic(effect=-0.2)
    f = fit_ascm(y, D, pre)
    mean_post = f.effect[~pre].mean()
    assert -0.28 < mean_post < -0.12


def test_conformal_p_range_and_direction():
    y, D, pre = synthetic()
    p_null = conformal_p(y, D, pre, theta0=0.0, lam=0.3)
    assert 0.0 <= p_null <= 1.0
    assert p_null > 0.1

    y2, D2, pre2 = synthetic(effect=-0.2)
    p_eff_zero = conformal_p(y2, D2, pre2, theta0=0.0, lam=0.3)
    assert 0.0 <= p_eff_zero <= 1.0
    assert p_eff_zero < 0.1

    p_eff_true = conformal_p(y2, D2, pre2, theta0=-0.2, lam=0.3)
    assert p_eff_true > 0.1


def test_conformal_interval_excludes_zero_for_real_effect():
    y, D, pre = synthetic(effect=-0.2)
    f = fit_ascm(y, D, pre, lam=0.3)
    point = float(f.effect[~pre].mean())
    ci = conformal_interval(y, D, pre, lam=0.3, point=point, scale=f.pre_rmse,
                            n_grid=11)

    assert ci.lo <= point <= ci.hi
    assert ci.hi < 0
    assert ci.lo <= -0.2 <= ci.hi


def test_conformal_interval_contains_zero_for_null():
    y, D, pre = synthetic()
    f = fit_ascm(y, D, pre, lam=0.3)
    point = float(f.effect[~pre].mean())
    ci = conformal_interval(y, D, pre, lam=0.3, point=point, scale=f.pre_rmse,
                            n_grid=11)

    assert ci.lo <= point <= ci.hi
    assert ci.lo <= 0.0 <= ci.hi


def test_space_placebo_detects_real_effect():
    y, D, pre = synthetic(effect=-0.2)
    f = fit_ascm(y, D, pre, lam=0.3)
    point = float(f.effect[~pre].mean())

    sp = space_placebo(y, D, pre, lam=0.3, treated_effect=point, max_units=10)

    assert sp.ratios.shape == (10,)
    assert sp.effects.shape == (10,)
    assert sp.pre_rmses.shape == (10,)
    assert sp.effect_series.shape == (10, 80)
    assert 0.0 < sp.p_value <= 1.0
    assert 0.0 < sp.p_effect <= 1.0
    assert sp.p_value <= 2.0 / 11.0 + 1e-9


def test_time_placebos_null_series_all_inside_pre_period():
    y, D, pre = synthetic(n_pre=56)
    tp = time_placebos(y, D, pre, lam=0.3, n=2, min_effect=0.05)

    assert len(tp) == 2
    n_pre = int(pre.sum())
    for placebo in tp:
        assert 0 <= placebo.fake_index < n_pre
        assert not placebo.flagged


def test_time_placebos_too_short_pre_period_returns_empty():
    y, D, pre = synthetic(n_pre=20)
    tp = time_placebos(y, D, pre, lam=0.3, n=2)
    assert tp == []
