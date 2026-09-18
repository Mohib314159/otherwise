"""Reversal / permanence monitoring."""
from src.synth_data import generate
from src.pipeline import run_audit


def _by_truth(ds):
    out = {}
    for f in ds.fields:
        out.setdefault(f.truth_label, f.field_id)
    return out


def test_reverter_flagged_and_steady_adopter_not():
    ds = generate(seed=7)
    bt = _by_truth(ds)
    reverter = run_audit(ds, bt["reverter"])
    adopter = run_audit(ds, bt["adopter"])
    assert reverter.reversal.detected is True
    assert reverter.reversal.reversal_year is not None
    assert adopter.reversal.detected is False


def test_no_false_reversal_on_controls_or_liars():
    ds = generate(seed=7)
    for f in ds.fields:
        if f.truth_label in ("control", "liar"):
            rep = run_audit(ds, f.field_id)
            assert rep.reversal.detected is False


def test_onset_year_detected_for_adopters():
    from src.monitor import detect_onset
    ds = generate(seed=7)
    for f in ds.fields:
        if f.truth_label in ("adopter", "over_claimer", "weak", "reverter"):
            rep = run_audit(ds, f.field_id)
            assert rep.detected_adoption_year == 2021
        if f.truth_label == "liar":
            rep = run_audit(ds, f.field_id)
            assert rep.detected_adoption_year is None
