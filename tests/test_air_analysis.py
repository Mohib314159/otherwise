import numpy as np
import pandas as pd

from src.app.air.analysis import analyse_stratum


def _panel(effect=-7.0, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2016-04-10", periods=170, freq="W-SUN")
    event = pd.Timestamp("2019-04-08")
    common = 42 + 5*np.sin(2*np.pi*np.arange(len(idx))/52.18)
    donors = {}
    meta = {}
    for j in range(18):
        s = common + rng.normal(0, 1.0, len(idx)) + rng.normal(0, 2)
        code = f"D{j:02d}"
        donors[code] = pd.Series(s, index=idx)
        meta[code] = {"code": code, "name": code, "lat": 52+j*.01, "lon": -2,
                      "site_type":"Urban Traffic", "stratum":"traffic", "source":"test", "city":"x", "uk_air_id":None}
    treated = {}
    tmeta = {}
    base = np.mean(np.vstack([donors[f"D{j:02d}"].to_numpy() for j in range(4)]), axis=0)
    for j in range(3):
        y = base + rng.normal(0, .5, len(idx)) + np.where(idx >= event, effect, 0.0)
        code = f"T{j}"
        treated[code] = pd.Series(y, index=idx)
        tmeta[code] = {"code":code,"name":code,"lat":51.5,"lon":-.1,"site_type":"Roadside",
                       "stratum":"traffic","source":"test","city":"London","uk_air_id":None}
    return treated, donors, meta, tmeta


def test_air_analysis_recovers_large_unique_no2_drop():
    treated, donors, meta, tmeta = _panel(effect=-7.0)
    out = analyse_stratum(treated, donors, "2019-04-08", 3, "traffic", meta, tmeta)
    assert out is not None
    result, chart, donor_info, verdict = out
    assert result["point"] < -4.0
    assert result["placebo_symmetric"] is True
    assert result["placebo_cohort_size"] == 3
    assert verdict.status == "REAL"
    assert len(donor_info["station_codes"]) >= 12


def test_air_analysis_does_not_call_null_effect_real():
    treated, donors, meta, tmeta = _panel(effect=0.0, seed=7)
    out = analyse_stratum(treated, donors, "2019-04-08", 3, "traffic", meta, tmeta)
    assert out is not None
    result, chart, donor_info, verdict = out
    assert verdict.status != "REAL"


def _attack_panel(kind: str, seed: int = 123):
    treated, donors, meta, tmeta = _panel(effect=0.0, seed=seed)
    event = pd.Timestamp("2019-04-08")
    idx = next(iter(treated.values())).index
    post = idx >= event
    if kind == "true_effect":
        for c in treated: treated[c].loc[post] -= 6.0
    elif kind == "dropout":
        # Make T0 a materially higher-baseline monitor, then remove it at launch.
        treated["T0"] += 12.0
        treated["T0"].loc[post] = np.nan
    elif kind == "one_station":
        treated["T0"].loc[post] -= 18.0
    elif kind == "pretrend":
        lead = idx >= (event - pd.Timedelta(weeks=13))
        weeks = np.arange(lead.sum(), dtype=float)
        ramp = -0.55 * weeks
        for c in treated: treated[c].loc[lead] += ramp
    elif kind == "common_shock":
        for c in treated: treated[c].loc[post] -= 6.0
        for c in donors: donors[c].loc[post] -= 6.0
    elif kind == "coincident_local":
        # Fundamentally unidentifiable observational confounder: expected residual failure.
        for c in treated: treated[c].loc[post] -= 6.0
    else:
        raise ValueError(kind)
    return treated, donors, meta, tmeta


def _attack_verdict(kind: str):
    treated, donors, meta, tmeta = _attack_panel(kind)
    out = analyse_stratum(treated, donors, "2019-04-08", 3, "traffic", meta, tmeta)
    assert out is not None
    return out[0], out[3]


def test_redteam_monitor_dropout_cannot_manufacture_real_drop():
    result, verdict = _attack_verdict("dropout")
    assert verdict.status != "REAL"
    assert "T0" in result["treated_station_dropped"]


def test_redteam_one_treated_monitor_cannot_drive_real_verdict():
    result, verdict = _attack_verdict("one_station")
    assert verdict.status == "CANT_TELL"
    assert result["treated_jackknife"]["robust"] is False


def test_redteam_preexisting_decline_is_flagged():
    result, verdict = _attack_verdict("pretrend")
    assert verdict.status == "CANT_TELL"
    assert result["pretrend"]["flagged"] is True


def test_redteam_common_national_shock_is_not_called_ulez_effect():
    _, verdict = _attack_verdict("common_shock")
    assert verdict.status != "REAL"


def test_large_no2_effect_interval_search_is_not_legacy_plus_minus_10_truncated():
    treated, donors, meta, tmeta = _panel(effect=-13.0, seed=18)
    result, _, _, verdict = analyse_stratum(treated, donors, "2019-04-08", 3, "traffic", meta, tmeta)
    assert result["point"] < -10
    assert result["conformal_boundary_hit"] is False
    assert result["hi"] < 0
    assert verdict.status == "REAL"


def test_too_small_control_pool_cannot_silently_shrink_placebo_cohort():
    treated, donors, meta, tmeta = _panel(effect=-7.0, seed=11)
    donors = dict(list(donors.items())[:14])
    meta = {k: meta[k] for k in donors}
    result, _, _, verdict = analyse_stratum(treated, donors, "2019-04-08", 3, "traffic", meta, tmeta)
    assert result["placebo_exact_cohort"] is False
    assert result["placebo_n"] == 0
    assert verdict.status == "CANT_TELL"
    # no placebo cohort means no p-value at all, not the old p = 1.0 sentinel
    assert result["placebo_p"] is None and result["placebo_p_effect"] is None


def test_weekly_repair_limits_total_holes_and_reports_actual_imputation():
    from src.app.air.analysis import _repair_one_week_gap

    index = pd.date_range("2023-01-01", periods=6, freq="W-SUN")
    for values in ([1, np.nan, 3, np.nan, 5, 6],
                   [1, np.nan, np.nan, 4, 5, 6],
                   [np.nan, 2, 3, 4, 5, 6],
                   [1, 2, 3, 4, 5, np.nan]):
        original = pd.Series(values, index=index, dtype=float)
        repaired, fraction = _repair_one_week_gap(original)
        pd.testing.assert_series_equal(repaired, original)
        assert fraction == 0.0
    repaired, fraction = _repair_one_week_gap(pd.Series([1, 2, np.nan, 4, 5, 6], index=index))
    assert repaired.iloc[2] == 3
    assert fraction == 1 / 6


def test_weekly_repair_cannot_bridge_an_excluded_calendar_week():
    from src.app.air.analysis import _repair_one_week_gap

    original = pd.Series([1.0, np.nan, 4.0],
                         index=pd.to_datetime(["2023-08-20", "2023-08-27", "2023-09-10"]))
    repaired, fraction = _repair_one_week_gap(original)
    pd.testing.assert_series_equal(repaired, original)
    assert fraction == 0.0


def test_analysis_excludes_mixed_policy_week_from_chart_and_imputation():
    treated, donors, meta, tmeta = _panel(effect=0)
    # Tuesday launch: the Sunday-ending week is mixed exposure. Upstream
    # resampling drops it; direct analysis must preserve that exclusion too.
    event = "2019-04-09"
    crossing = pd.Timestamp("2019-04-14")
    for series in [*treated.values(), *donors.values()]:
        series.loc[crossing] = np.nan
    result, chart, donor_info, verdict = analyse_stratum(
        treated, donors, event, 3, "traffic", meta, tmeta)
    assert "2019-04-14" not in chart["dates"]
    assert all(value == 0 for value in donor_info["imputed_fraction"].values())
    assert "9 Apr 2019" in verdict.statement


def test_positive_point_with_uncertain_reduction_is_inconclusive():
    from src.app.air.analysis import _decide

    result = {
        "point": 0.2, "lo": -5.0, "hi": 5.0, "relative_pct": 0.5,
        "n_donors": 24, "n_pre": 100, "n_post": 13,
        "treated_station_count": 3, "placebo_pre_rmse_median": 1.0,
        "pre_rmse": 1.0, "placebo_exact_cohort": True, "placebo_n": 40,
    }
    assert _decide("NO2_TRAFFIC", result, "after implementation").status == "CANT_TELL"
    # Once the interval excludes a meaningful reduction, the existing
    # minimum-effect rule can support a negative verdict.
    result["lo"] = -0.5
    verdict = _decide("NO2_TRAFFIC", result, "after implementation")
    assert verdict.status == "NOT_REAL"
    assert "rules out" in verdict.reasons[0]
    result["lo"] = 0.1
    verdict = _decide("NO2_TRAFFIC", result, "after implementation")
    assert verdict.status == "NOT_REAL"
    assert "opposite direction" in verdict.reasons[0]
