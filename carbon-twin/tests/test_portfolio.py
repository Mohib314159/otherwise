"""Portfolio aggregation: sane, and NaN-robust."""
import numpy as np
from src.synth_data import generate
from src.pipeline import run_audit, audit_all_claims
from src.portfolio import summarize


def test_portfolio_totals_are_sane():
    ds = generate(seed=7)
    reports = [run_audit(ds, f.field_id) for f in ds.fields]
    ps = summarize(reports, price=50.0)
    assert ps.n_fields == len(reports)
    assert ps.verified_tco2e > 0
    assert ps.fraud_fields >= 1 and ps.fraud_exposure_value > 0
    assert ps.reversal_fields >= 1
    assert 0.0 <= ps.base_reversal_rate <= 1.0
    # verified@95 cannot exceed total verified
    assert ps.verified_at_95_tco2e <= ps.verified_tco2e + 1e-6


def test_portfolio_survives_a_nan():
    ds = generate(seed=7)
    reports = audit_all_claims(ds)
    # inject a NaN into one field's carbon estimate
    reports[0].carbon.central_tco2e_yr = float("nan")
    ps = summarize(reports, price=50.0)        # must not raise / propagate NaN
    assert np.isfinite(ps.verified_tco2e)
    assert np.isfinite(ps.fraud_exposure_value)
