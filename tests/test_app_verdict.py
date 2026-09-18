"""Tests for src/app/verdict.py: turning an estimate + placebos into a verdict."""
from __future__ import annotations

from src.app.verdict import SignalResult, decide

DEFAULTS = dict(
    signal="NDVI", sensor="S2", expected_sign=-1, point=-0.2, lo=-0.26, hi=-0.14,
    p_zero=0.01, pre_rmse=0.03, placebo_pre_rmse_median=0.03, n_pre=40, n_post=10,
    n_donors=50, placebo_p=0.03, placebo_p_effect=0.03, placebo_n=50,
    time_placebo_flags=[False, False, False],
)


def make(**overrides) -> SignalResult:
    kwargs = dict(DEFAULTS)
    kwargs.update(overrides)
    return SignalResult(**kwargs)


POST_LABEL = "in the 12 months after 1 Mar 2023"


def test_default_is_real_change():
    v = decide(make(), "clearing", POST_LABEL)
    assert v.status == "REAL"
    assert v.headline == "Real change"
    assert "placebo p = 0.03" in v.statement


def test_high_placebo_p_is_cant_tell():
    v = decide(make(placebo_p=0.3), "clearing", POST_LABEL)
    assert v.status == "CANT_TELL"
    assert any("placebo" in r for r in v.reasons)


def test_too_few_donors_is_cant_tell():
    v = decide(make(n_donors=10), "clearing", POST_LABEL)
    assert v.status == "CANT_TELL"
    assert any("control cells" in r for r in v.reasons)


def test_too_few_post_periods_is_cant_tell():
    v = decide(make(n_post=2), "clearing", POST_LABEL)
    assert v.status == "CANT_TELL"
    assert any("after the event" in r for r in v.reasons)


def test_poor_pre_fit_is_cant_tell():
    v = decide(make(pre_rmse=0.2, placebo_pre_rmse_median=0.03), "clearing", POST_LABEL)
    assert v.status == "CANT_TELL"
    assert any("track" in r for r in v.reasons)


def test_small_effect_around_zero_is_no_real_change():
    v = decide(make(point=0.01, lo=-0.03, hi=0.04), "clearing", POST_LABEL)
    assert v.status == "NOT_REAL"
    assert v.headline == "No real change"


def test_opposite_direction_is_not_what_was_claimed():
    v = decide(make(point=0.2, lo=0.14, hi=0.26), "clearing", POST_LABEL)
    assert v.status == "NOT_REAL"
    assert v.headline == "Not what was claimed"


def test_wide_interval_is_cant_tell():
    v = decide(make(point=-0.04, lo=-0.12, hi=0.03), "clearing", POST_LABEL)
    assert v.status == "CANT_TELL"
    assert any("too wide" in r for r in v.reasons)


def test_expected_sign_zero_accepts_either_direction():
    v = decide(make(expected_sign=0, point=0.2, lo=0.14, hi=0.26), "other", POST_LABEL)
    assert v.status == "REAL"


def test_time_placebo_flag_still_real_but_noted():
    v = decide(make(time_placebo_flags=[True, False, False]), "clearing", POST_LABEL)
    assert v.status == "REAL"
    assert v.reasons
    assert any("fake event date" in r for r in v.reasons)


def test_radar_signal_reports_db():
    r = make(signal="VV", point=-2.0, lo=-2.6, hi=-1.4, pre_rmse=0.3,
              placebo_pre_rmse_median=0.3)
    v = decide(r, "clearing", POST_LABEL)
    assert v.status == "REAL"
    assert "dB" in v.statement


def test_pre_fit_ok_property():
    assert make(pre_rmse=0.03, placebo_pre_rmse_median=0.03).pre_fit_ok is True
    assert make(pre_rmse=0.1, placebo_pre_rmse_median=0.03).pre_fit_ok is False


def test_min_effect_property():
    assert make(signal="NDVI").min_effect == 0.05
    assert make(signal="VV").min_effect == 1.0
