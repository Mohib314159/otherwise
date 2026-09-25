from datetime import date

import numpy as np
import pandas as pd

from src.app.air.models import AirStation
from src.app.air.run import (_control_policy_contamination, _fetch_adjusted, _window,
                             air_run_id)
from src.app.air.cases import AIR_CASES


class FakeNO2:
    def __init__(self, hourly): self.hourly = hourly
    def hourly_no2(self, station, start, end): return self.hourly, []


class FakeERA5:
    def daily(self, lat, lon, start, end):
        idx = pd.date_range(start, end, freq="D")
        n = len(idx); t = np.arange(n)
        return pd.DataFrame({
            "temperature_2m": 10 + np.sin(t / 20),
            "precipitation": np.zeros(n),
            "wind_u": np.ones(n), "wind_v": np.ones(n),
            "boundary_layer_height": np.full(n, 700.0),
        }, index=idx)


def _station():
    return AirStation("X", "X", 52.48, -1.89, "Urban Traffic", "test")


def test_missing_chart_bands_serialize_as_null_not_invalid_json():
    import json
    from src.app.air.run import _json_safe
    data = {"placebo_band": [[np.nan, 2.0], [np.inf, -np.inf]], "point": np.float64(-3)}
    encoded = json.dumps(_json_safe(data), allow_nan=False)
    assert json.loads(encoded) == {"placebo_band": [[None, 2.0], [None, None]], "point": -3.0}


def test_registered_window_is_used_not_generic_three_year_lookback():
    assert _window(AIR_CASES["ulez-central-2019"], 3)[0] == "2018-03-08"
    assert _window(AIR_CASES["ulez-londonwide-2023"], 3)[0] == "2021-07-19"


def test_protocol_change_is_baked_into_air_permalink_identity():
    rid = air_run_id("ulez-central-2019", 3)
    assert len(rid) == 16
    # Deterministic and horizon-sensitive.
    assert rid == air_run_id("ulez-central-2019", 3)
    assert rid != air_run_id("ulez-central-2019", 6)


def test_saved_air_permalink_is_not_recomputed_or_overwritten(tmp_path, monkeypatch):
    import json
    import src.app.air.run as run
    rid = air_run_id("ulez-central-2019", 3)
    saved = {"id": rid, "label": "Original evidence", "created": "fixed"}
    path = tmp_path / f"{rid}.json"
    path.write_text(json.dumps(saved), encoding="utf-8")
    before = path.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError("Existing evidence must not refetch or change")
    monkeypatch.setattr(run, "fetch_case_boundary", forbidden)
    assert run.run_air_verdict("ulez-central-2019", 3, label="Replacement", runs_dir=str(tmp_path)) == saved
    assert path.read_bytes() == before


def test_air_identity_includes_cohort_fetch_budget(monkeypatch):
    import src.app.air.run as run
    before = run.air_run_id("ulez-central-2019", 3)
    monkeypatch.setattr(run, "AIR_MAX_DONOR_FETCH", run.AIR_MAX_DONOR_FETCH + 1)
    assert run.air_run_id("ulez-central-2019", 3) != before


def test_station_coverage_rejection_survives_receipt_compression():
    from src.app.air.run import _compress_receipts
    rejection = {"scope": "station", "reason": "coverage", "sensor": "test X",
                 "detail": "station coverage pre=95%, post=0%", "daily_post_coverage": 0.0}
    rows = [{"reason": "coverage", "sensor": "test X", "detail": "0/24 hours"}] * 10
    compressed = _compress_receipts([*rows, rejection], _station())
    assert rejection in compressed
    assert any(r.get("count") == 10 for r in compressed)


def test_known_control_policy_launch_is_screened_only_when_inside_window():
    s = _station()
    hit = _control_policy_contamination(s, "2021-01-01", "2021-12-31")
    assert hit and "Birmingham" in hit["policy"]
    assert _control_policy_contamination(s, "2018-01-01", "2019-01-01") is None


def test_station_must_have_80_percent_daily_coverage_on_both_sides():
    start, end, event = "2018-01-01", "2019-06-30", "2019-04-08"
    days = pd.date_range(start, end, freq="D")
    stamps, vals = [], []
    for d in days:
        nh = 19 if d < pd.Timestamp(event) else 10  # valid pre, invalid post
        for h in range(nh):
            stamps.append(d + pd.Timedelta(hours=h)); vals.append(35.0)
    hourly = pd.Series(vals, index=pd.DatetimeIndex(stamps))
    _, weekly, meta, receipts = _fetch_adjusted(_station(), FakeNO2(hourly), FakeERA5(), start, end, event)
    assert weekly is None
    assert meta["daily_pre_coverage"] >= .8
    assert meta["daily_post_coverage"] < .8
    assert any(r["reason"] == "coverage" for r in receipts)


def test_week_crossing_non_monday_event_is_dropped_from_weekly_panel():
    start, end, event = "2022-07-19", "2023-11-29", "2023-08-29"  # Tuesday
    days = pd.date_range(start, end, freq="D")
    stamps, vals = [], []
    for d in days:
        for h in range(19):
            stamps.append(d + pd.Timedelta(hours=h)); vals.append(35.0)
    hourly = pd.Series(vals, index=pd.DatetimeIndex(stamps))
    _, weekly, _, receipts = _fetch_adjusted(_station(), FakeNO2(hourly), FakeERA5(), start, end, event)
    mixed_end = pd.Timestamp(event).to_period("W-SUN").end_time.normalize()
    assert pd.isna(weekly.loc[mixed_end])
    assert any(r["reason"] == "event-bin" for r in receipts)
