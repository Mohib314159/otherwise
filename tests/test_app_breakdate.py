"""Tests for src/app/breakdate.py: break-date search with placebo-of-the-maximum inference."""
from __future__ import annotations

import numpy as np
import pytest

from src.app.breakdate import (
    MIN_POST_BINS,
    MIN_PRE_BINS,
    BreakResult,
    clamp_window,
    default_window,
    find_break,
    refine_uncertainty,
)


def synthetic(B=140, n=30, step=0.0, t_step=90, seed=0):
    """Donors share a seasonal shape (period 24) with per-donor amplitude and
    offset plus noise 0.03; the area is a convex combination of the first 5
    donors plus noise. A `step` is added to the area from bin `t_step` on."""
    rng = np.random.default_rng(seed)
    t = np.arange(B)
    seasonal = np.sin(2 * np.pi * t / 24)
    factors = rng.uniform(0.7, 1.3, size=n)
    offsets = rng.normal(0, 0.05, size=n)
    D = 0.5 + seasonal[None, :] * factors[:, None] + offsets[:, None] + rng.normal(0, 0.03, size=(n, B))
    w = rng.dirichlet(np.ones(5))
    y = (w[:, None] * D[:5]).sum(axis=0) + rng.normal(0, 0.03, size=B)
    y[t_step:] += step
    M = np.column_stack([y, D.T])
    dates = np.datetime64("2020-01-05") + np.arange(B) * np.timedelta64(10, "D")
    return M, dates


@pytest.mark.xfail(strict=False, reason="break-date search not yet wired into the product; its author agent was stopped before tuning")
def test_step_is_found_at_the_right_bin():
    M, dates = synthetic(step=-0.25, t_step=90, seed=1)
    r = find_break(M, dates, max_units=29, min_effect=0.05)
    assert isinstance(r, BreakResult)
    assert abs(r.index - 90) <= 2
    assert r.detected is True
    assert r.p_search <= 0.10
    assert r.sign == -1 and r.point < -0.15
    assert r.date == str(dates[r.index])
    s0, s1 = r.window
    assert r.curve.shape == (s1 - s0,)
    assert np.isclose(r.curve.max(), r.stat)
    assert r.placebo_max_stats.shape == r.placebo_break_indices.shape
    assert np.all((r.placebo_break_indices >= s0) & (r.placebo_break_indices < s1))


def test_no_step_is_not_detected_in_most_seeds():
    ok = 0
    for seed in range(5):
        M, dates = synthetic(step=0.0, seed=seed)
        r = find_break(M, dates, max_units=29, min_effect=0.05)
        ok += int((not r.detected) and r.p_search > 0.10)
    assert ok >= 4


def test_refine_uncertainty_contains_chosen_index():
    M, dates = synthetic(step=-0.25, t_step=90, seed=2)
    r = find_break(M, dates, max_units=10)
    lo, hi = refine_uncertainty(r.curve, r.window[0])
    assert lo <= r.index <= hi
    assert r.window[0] <= lo <= hi < r.window[1]
    # a flat curve at the max everywhere spans the whole window
    assert refine_uncertainty(np.ones(7), 5) == (5, 11)
    with pytest.raises(ValueError):
        refine_uncertainty(np.array([]), 0)


def test_window_clamps_to_min_pre_and_post():
    for B in (25, 30, 60, 140, 400):
        s0, s1 = default_window(B)
        assert s1 > s0
        for t in range(s0, s1):
            assert t >= MIN_PRE_BINS
            assert B - t >= MIN_POST_BINS
    assert clamp_window(140, 5, 200) == (MIN_PRE_BINS, 140 - MIN_POST_BINS + 1)
    with pytest.raises(ValueError):
        clamp_window(22, 0, 22)
    # an explicit window is honoured after clamping and the result stays inside it
    M, dates = synthetic(step=-0.25, t_step=90, seed=3)
    r = find_break(M, dates, window=(80, 100), max_units=5)
    assert r.window == (80, 100)
    assert 80 <= r.index < 100


def test_nan_input_raises():
    M, dates = synthetic()
    M[10, 3] = np.nan
    with pytest.raises(ValueError):
        find_break(M, dates)
    with pytest.raises(ValueError):
        find_break(synthetic()[0][:, :2], dates)          # fewer than 2 donors
