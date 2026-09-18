"""Reversal-risk pricing."""
import numpy as np
from src.synth_data import generate
from src.pipeline import run_audit
from src.portfolio import summarize
from src.actuary import price_report


def _by_truth(ds):
    out = {}
    for f in ds.fields:
        out.setdefault(f.truth_label, f.field_id)
    return out


def test_survival_is_monotonic_and_bounded():
    ds = generate(seed=7)
    bt = _by_truth(ds)
    reps = [run_audit(ds, f.field_id) for f in ds.fields]
    ps = summarize(reps)
    rep = run_audit(ds, bt["adopter"])
    rr = price_report(rep, ps.base_annual_hazard, price=50.0)
    s = np.array(rr.survival_curve)
    assert np.all(np.diff(s) <= 1e-9)            # survival never increases
    assert 0.0 <= rr.reversal_prob_horizon <= 1.0
    assert rr.annual_premium_per_tco2e >= 0.0


def test_reverter_prices_higher_than_steady_adopter():
    ds = generate(seed=7)
    bt = _by_truth(ds)
    reps = [run_audit(ds, f.field_id) for f in ds.fields]
    ps = summarize(reps)
    adopter = price_report(run_audit(ds, bt["adopter"]), ps.base_annual_hazard)
    reverter = price_report(run_audit(ds, bt["reverter"]), ps.base_annual_hazard)
    assert reverter.annual_hazard > adopter.annual_hazard


def test_liar_has_no_insurable_carbon():
    ds = generate(seed=7)
    bt = _by_truth(ds)
    reps = [run_audit(ds, f.field_id) for f in ds.fields]
    ps = summarize(reps)
    rr = price_report(run_audit(ds, bt["liar"]), ps.base_annual_hazard)
    assert rr.applicable is False
    assert rr.annual_premium_value == 0.0
