"""Tests for src/app/evidence.py: weighing optical and radar evidence together."""
from __future__ import annotations

import pytest

from src.app.evidence import Evidence, assess, status_of
from src.app.verdict import SignalResult

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


def optical(**overrides) -> SignalResult:
    """Supportive NDVI drop for a clearing event unless overridden."""
    return make(**overrides)


def radar(**overrides) -> SignalResult:
    """Supportive VH drop for a clearing event unless overridden."""
    kwargs = dict(signal="VH", sensor="S1", expected_sign=-1, point=-1.5, lo=-2.1, hi=-0.9,
                  pre_rmse=0.3, placebo_pre_rmse_median=0.3, placebo_p=0.05, placebo_p_effect=0.05)
    kwargs.update(overrides)
    return make(**kwargs)


# --- status_of -------------------------------------------------------------

def test_status_supportive_by_default():
    assert status_of(optical()) == "supportive"
    assert status_of(radar()) == "supportive"


def test_status_unavailable_when_missing_or_too_few_post_bins():
    assert status_of(None) == "unavailable"
    assert status_of(optical(n_post=2)) == "unavailable"
    assert status_of(optical(n_post=3)) == "supportive"


def test_status_contradicting_when_opposite_side():
    assert status_of(optical(point=0.2, lo=0.14, hi=0.26)) == "contradicting"


def test_status_neutral_when_interval_straddles_zero():
    assert status_of(optical(point=-0.04, lo=-0.12, hi=0.03)) == "neutral"


def test_status_neutral_when_effect_below_min_effect():
    # Interval excludes zero but the point is smaller than MIN_EFFECT["NDVI"] = 0.05.
    assert status_of(optical(point=-0.03, lo=-0.045, hi=-0.015)) == "neutral"


def test_status_neutral_when_placebo_p_too_high():
    assert status_of(optical(placebo_p=0.3)) == "neutral"


def test_status_expected_sign_zero_accepts_either_side():
    assert status_of(optical(expected_sign=0, point=0.2, lo=0.14, hi=0.26)) == "supportive"
    assert status_of(optical(expected_sign=0, point=-0.2, lo=-0.26, hi=-0.14)) == "supportive"


# --- assess ----------------------------------------------------------------

def test_both_supportive_is_both_with_bonferroni_p():
    o, r = optical(placebo_p=0.03), radar(placebo_p=0.05)
    ev = assess({"NDVI": o, "VH": r}, "clearing")
    assert isinstance(ev, Evidence)
    assert ev.optical is o and ev.radar is r
    assert ev.optical_status == "supportive" and ev.radar_status == "supportive"
    assert ev.agreement == "both"
    assert ev.p_combined == pytest.approx(min(1.0, 2 * min(o.placebo_p, r.placebo_p)))
    assert ev.p_combined == pytest.approx(0.06)


def test_both_sentence():
    ev = assess({"NDVI": optical(), "VH": radar()}, "clearing")
    assert ev.sentence == ("Optical and radar agree: greenness (NDVI) fell by 0.20 and "
                           "radar backscatter (VH) fell by 1.5 dB (combined placebo p = 0.06).")


def test_p_combined_capped_at_one():
    ev = assess({"NDVI": optical(placebo_p=0.6), "VH": radar(placebo_p=0.7)}, "clearing")
    assert ev.p_combined == 1.0


def test_optical_supportive_radar_neutral_is_optical_only():
    r = radar(point=-0.3, lo=-1.2, hi=0.6)
    ev = assess({"NDVI": optical(), "VH": r}, "clearing")
    assert ev.agreement == "optical-only"
    assert ev.optical_status == "supportive"
    assert ev.radar_status == "neutral"
    assert ev.sentence == ("Optical shows the change (greenness (NDVI) fell by 0.20); radar is inconclusive "
                           "(radar backscatter (VH) −0.3 dB, interval −1.2 to 0.6).")
    # Radar was available, so k = 2 and the combined p is Bonferroni over both.
    assert ev.p_combined == pytest.approx(2 * min(0.03, r.placebo_p))


def test_optical_supportive_radar_unavailable_sentence():
    ev = assess({"NDVI": optical(), "VH": radar(n_post=2)}, "clearing")
    assert ev.agreement == "optical-only"
    assert ev.radar_status == "unavailable"
    assert ev.sentence == ("Optical shows the change (greenness (NDVI) fell by 0.20); "
                           "radar has too few observations to weigh in.")
    # Only one sensor available, so k = 1.
    assert ev.p_combined == pytest.approx(0.03)


def test_radar_supportive_optical_too_few_post_is_radar_only():
    ev = assess({"NDVI": optical(n_post=2), "VH": radar()}, "clearing")
    assert ev.agreement == "radar-only"
    assert ev.optical_status == "unavailable"
    assert ev.radar_status == "supportive"
    assert ev.p_combined == pytest.approx(0.05)
    assert ev.sentence == ("Radar shows the change (radar backscatter (VH) fell by 1.5 dB); "
                           "optical has too few observations to weigh in.")


def test_radar_supportive_optical_neutral_sentence():
    ev = assess({"NDVI": optical(point=-0.04, lo=-0.12, hi=0.03), "VH": radar()}, "clearing")
    assert ev.agreement == "radar-only"
    assert ev.optical_status == "neutral"
    assert ev.sentence == ("Radar shows the change (radar backscatter (VH) fell by 1.5 dB); optical is "
                           "inconclusive (greenness (NDVI) −0.04, interval −0.12 to 0.03).")


def test_opposite_direction_radar_is_conflict():
    ev = assess({"NDVI": optical(), "VH": radar(point=1.5, lo=0.9, hi=2.1)}, "clearing")
    assert ev.agreement == "conflict"
    assert ev.optical_status == "supportive"
    assert ev.radar_status == "contradicting"
    assert ev.sentence.startswith("Optical and radar disagree: ")
    assert "greenness (NDVI) fell by 0.20" in ev.sentence
    assert "radar backscatter (VH) rose by 1.5 dB" in ev.sentence
    assert ev.sentence.endswith("; treat the result with caution.")


def test_opposite_direction_optical_is_conflict():
    ev = assess({"NDVI": optical(point=0.2, lo=0.14, hi=0.26), "VH": radar()}, "clearing")
    assert ev.agreement == "conflict"
    assert ev.optical_status == "contradicting"
    assert ev.radar_status == "supportive"


def test_nothing_supportive_is_none():
    ev = assess({"NDVI": optical(point=-0.04, lo=-0.12, hi=0.03),
                 "VH": radar(point=-0.3, lo=-1.2, hi=0.6)}, "clearing")
    assert ev.agreement == "none"
    assert ev.sentence == "Neither optical nor radar shows a change beyond what the controls did."
    assert ev.p_combined is not None


def test_missing_radar_uses_k_equals_one():
    ev = assess({"NDVI": optical(placebo_p=0.03)}, "clearing")
    assert ev.radar is None
    assert ev.radar_status == "unavailable"
    assert ev.agreement == "optical-only"
    assert ev.p_combined == pytest.approx(0.03)


def test_empty_results_is_none_with_no_p():
    ev = assess({}, "clearing")
    assert ev.optical is None and ev.radar is None
    assert ev.optical_status == "unavailable" and ev.radar_status == "unavailable"
    assert ev.agreement == "none"
    assert ev.p_combined is None
    assert ev.sentence == "Neither optical nor radar shows a change beyond what the controls did."


def test_picks_primary_signal_per_change_type():
    # Flood: NDWI up, VV down. Extra correlated indices in the dict are ignored.
    ndwi = make(signal="NDWI", expected_sign=+1, point=0.2, lo=0.14, hi=0.26)
    vv = radar(signal="VV", expected_sign=-1)
    ndvi = optical()  # not the primary optical signal for a flood
    ev = assess({"NDWI": ndwi, "VV": vv, "NDVI": ndvi}, "flood")
    assert ev.optical is ndwi
    assert ev.radar is vv
    assert ev.agreement == "both"
    assert "surface water index (NDWI) rose by 0.20" in ev.sentence
    assert "radar backscatter (VV) fell by 1.5 dB" in ev.sentence


def test_secondary_optical_index_does_not_count_as_evidence():
    # Only NBR (primary for burn) is consulted; a supportive NDVI does not stand in for it.
    ev = assess({"NDVI": optical(), "VH": radar()}, "burn")
    assert ev.optical is None
    assert ev.optical_status == "unavailable"
    assert ev.agreement == "radar-only"


# --- REDTEAM E9: the sentence may not be stronger than the verdict ------------

@pytest.mark.parametrize("over", [dict(n_donors=19), dict(pre_rmse=0.2),
                                  dict(placebo_effect_median=-0.3),
                                  dict(time_placebo_flags=[True, False, False])])
def test_status_is_not_supportive_when_a_verdict_gate_fails(over):
    assert status_of(optical(**over)) != "supportive"


def test_clear_but_small_move_is_reported_with_numbers_not_as_no_change():
    """Saddleworth's shape: VH interval excludes zero but misses the 1 dB minimum."""
    ev = assess({"NDVI": optical(point=-0.01, lo=-0.05, hi=0.03),
                 "VH": radar(point=-0.91, lo=-1.3, hi=-0.5)}, "clearing")
    assert ev.agreement == "none"
    assert "Neither optical nor radar passes every test" in ev.sentence
    assert "−0.9 dB, interval −1.3 to −0.5" in ev.sentence
    assert "beyond what the controls did" not in ev.sentence
