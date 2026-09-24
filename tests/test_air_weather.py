import numpy as np
import pandas as pd

from src.app.air.weather import weather_normalise


def _coverage_fixture():
    idx = pd.date_range("2018-01-01", periods=500)
    weather = pd.DataFrame({"temperature_2m": 10.0, "precipitation": 1.0,
                            "wind_u": 2.0, "wind_v": 3.0}, index=idx)
    return pd.Series(30.0, index=idx), weather, idx[365]


def test_empty_era5_cannot_be_reported_as_weather_normalised():
    y, _, event = _coverage_fixture()
    out = weather_normalise(y, pd.DataFrame(), event)
    assert not out.applicable
    assert out.metadata()["coverage"]["valid_days_after_repair"] == 0


def test_optional_boundary_layer_absence_is_explicit():
    y, weather, event = _coverage_fixture()
    out = weather_normalise(y, weather, event)
    assert out.applicable
    assert out.metadata()["coverage"]["unavailable_optional_features"] == ["boundary_layer_height"]


def test_long_weather_gap_is_rejected_instead_of_median_filled():
    y, weather, event = _coverage_fixture()
    weather.loc[weather.index[380:400], "wind_u"] = np.nan
    out = weather_normalise(y, weather, event)
    assert not out.applicable
    assert out.coverage["interpolated_days"]["wind_u"] == 0


def test_short_internal_weather_gap_is_repaired_and_receipted():
    y, weather, event = _coverage_fixture()
    weather.loc[weather.index[100:103], "wind_u"] = np.nan
    out = weather_normalise(y, weather, event)
    assert out.applicable
    assert out.coverage["interpolated_days"]["wind_u"] == 3


def test_weather_interpolation_cannot_cross_policy_date():
    y, weather, event = _coverage_fixture()
    weather.loc[event - pd.Timedelta(days=1), "wind_u"] = np.nan
    assert not weather_normalise(y, weather, event).applicable


def test_infinite_weather_is_missing_not_valid_observation():
    y, weather, event = _coverage_fixture()
    weather["temperature_2m"] = np.inf
    assert not weather_normalise(y, weather, event).applicable


def test_weather_normalisation_is_pre_only_and_recovers_planted_policy_drop():
    rng = np.random.default_rng(4)
    idx = pd.date_range("2016-01-01", "2019-08-31", freq="D")
    event = pd.Timestamp("2019-04-08")
    t = np.arange(len(idx))
    temp = 10 + 8*np.sin(2*np.pi*t/365.25) + rng.normal(0, 2, len(idx))
    wind_u = rng.normal(0, 3, len(idx)); wind_v = rng.normal(0, 3, len(idx))
    precip = np.maximum(0, rng.gamma(1.2, 1.0, len(idx)) - .7)
    pbl = 600 + 250*np.sin(2*np.pi*(t+90)/365.25) + rng.normal(0, 60, len(idx))
    weather = pd.DataFrame({"temperature_2m":temp, "precipitation":precip,
                            "wind_u":wind_u, "wind_v":wind_v,
                            "boundary_layer_height":pbl}, index=idx)
    # Strong weather component plus a known -6 ug/m3 policy shift.
    y = 46 - .65*temp + .7*np.sqrt(wind_u**2+wind_v**2) - .005*pbl + rng.normal(0, 1.2, len(idx))
    y = y + np.where(idx >= event, -6.0, 0.0)
    out = weather_normalise(pd.Series(y, index=idx), weather, event)
    assert out.applicable
    assert out.metadata()["trained_pre_event_only"] is True
    pre = out.series[idx < event].mean()
    post = out.series[(idx >= event) & (idx < event + pd.Timedelta(days=90))].mean()
    # Seasonality is deliberately retained, so don't demand exact -6; demand a
    # clearly recovered drop after the weather component is removed.
    assert post - pre < -3.0


def test_post_policy_values_cannot_change_weather_model_fit():
    """Regression guard against target leakage through model/alpha selection."""
    rng = np.random.default_rng(44)
    idx = pd.date_range("2017-01-01", "2019-12-31", freq="D")
    event = pd.Timestamp("2019-04-08")
    n = len(idx); t = np.arange(n)
    weather = pd.DataFrame({
        "temperature_2m": 10 + 7*np.sin(2*np.pi*t/365.25),
        "precipitation": rng.gamma(1.0, .5, n),
        "wind_u": rng.normal(0, 2, n), "wind_v": rng.normal(0, 2, n),
        "boundary_layer_height": 700 + 100*np.cos(2*np.pi*t/365.25),
    }, index=idx)
    base = 35 - .4*weather.temperature_2m + rng.normal(0, .8, n)
    a = pd.Series(base.to_numpy().copy(), idx)
    b = a.copy(); b.loc[idx >= event] -= 50.0
    ra = weather_normalise(a, weather, event)
    rb = weather_normalise(b, weather, event)
    assert ra.alpha == rb.alpha
    assert abs(ra.pre_rmse - rb.pre_rmse) < 1e-12
    np.testing.assert_allclose(ra.series.loc[idx < event], rb.series.loc[idx < event], atol=1e-10)
