"""Carbon estimate behaviour."""
from src.carbon import estimate_carbon, RATE_LOW, RATE_HIGH


def test_unverified_is_zero():
    e = estimate_carbon(0.20, 50.0, verified=False)
    assert e.central_tco2e_yr == 0.0


def test_negative_effect_is_zero():
    e = estimate_carbon(-0.05, 50.0, verified=True)
    assert e.central_tco2e_yr == 0.0


def test_central_within_band_and_monotonic():
    weak = estimate_carbon(0.05, 50.0, verified=True)
    strong = estimate_carbon(0.18, 50.0, verified=True)
    assert strong.central_tco2e_yr > weak.central_tco2e_yr
    for e in (weak, strong):
        assert e.low_tco2e_yr <= e.central_tco2e_yr <= e.high_tco2e_yr
        assert RATE_LOW - 1e-9 <= e.rate_central <= RATE_HIGH + 1e-9


def test_scales_with_area():
    small = estimate_carbon(0.15, 20.0, verified=True)
    big = estimate_carbon(0.15, 60.0, verified=True)
    assert abs(big.central_tco2e_yr - 3 * small.central_tco2e_yr) < 1e-6
