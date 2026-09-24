import pandas as pd


def test_boundary_uses_official_map_service_and_surfaces_arcgis_errors():
    import pytest
    from src.app.air.providers import fetch_ulez_boundary
    class HTTP:
        def get_json(self, namespace, url, **kwargs):
            assert "/MapServer/4/query" in url
            return {"error": {"code": 500, "message": "service unavailable"}}
    with pytest.raises(RuntimeError, match="service unavailable"):
        fetch_ulez_boundary(4, HTTP())

from src.app.air.providers import parse_aurn_search_html, parse_aurn_site_codes_html, UKAirProvider, LAQNProvider
from src.app.air.models import normalise_site_type, AirStation


def test_site_type_normalisation_keeps_traffic_and_background_separate():
    assert normalise_site_type("Urban Traffic") == "traffic"
    assert normalise_site_type("Kerbside") == "traffic"
    assert normalise_site_type("Urban Background") == "background"
    assert normalise_site_type("Suburban") == "background"


def test_parse_aurn_search_and_selector_html():
    table = '''<table><tr><td>1</td><td>Bristol Temple Way UK-AIR ID: UKA00631 Location: 51.457968,-2.583975</td>
    <td>Automatic Urban and Rural Monitoring Network</td><td>Urban Traffic</td></tr></table>'''
    selector = '<select><option value="BRI1">Bristol Temple Way</option></select>'
    rows = parse_aurn_search_html(table)
    codes = parse_aurn_site_codes_html(selector)
    assert rows[0]["uk_air_id"] == "UKA00631"
    assert rows[0]["site_type"] == "Urban Traffic"
    assert rows[0]["name"] == "Bristol Temple Way"
    assert codes["bristol temple way"] == "BRI1"


def test_parse_ukair_column_csv_tolerates_realistic_headers():
    text = '''Date,Time,Nitrogen dioxide,Status\n01/01/2019,00:00:00,38.2,V\n01/01/2019,01:00:00,41.0,V\n01/01/2019,02:00:00,No data,N\n'''
    s = UKAirProvider.parse_column_csv(text)
    assert len(s) == 2
    assert abs(s.iloc[0] - 38.2) < 1e-9
    assert isinstance(s.index, pd.DatetimeIndex)

from src.app.air.providers import hourly_to_daily


def test_daily_qc_requires_more_than_75_percent_of_hourly_values():
    idx18 = pd.date_range("2023-01-01", periods=18, freq="h")
    day18, _ = hourly_to_daily(pd.Series(20.0, index=idx18))
    assert pd.isna(day18.iloc[0])

    idx19 = pd.date_range("2023-01-01", periods=19, freq="h")
    day19, _ = hourly_to_daily(pd.Series(20.0, index=idx19))
    assert day19.iloc[0] == 20.0


def test_defra_hour_ending_preserves_all_hours_and_year_end():
    text = "All Data GMT hour ending\nStatus: R =Ratified P=Provisional,P*=As supplied\nDate,time,Nitrogen dioxide,status,unit\n"
    text += "\n".join(f"31-12-2019,{hour:02}:00,{hour},R,ugm-3" for hour in range(1, 25))
    receipts = []
    s = UKAirProvider.parse_column_csv(text, receipts)
    assert len(s) == 24
    assert s.index[0] == pd.Timestamp("2019-12-31 00:00")
    assert s.index[-1] == pd.Timestamp("2019-12-31 23:00")
    assert not receipts
    daily, dropped = hourly_to_daily(s)
    assert len(daily) == 1 and daily.iloc[0] == 12.5
    assert not dropped


def test_no2_status_is_pollutant_adjacent_and_rejections_are_receipted():
    text = "All Data GMT hour ending\nDate,time,Nitric oxide,status,unit,Nitrogen dioxide,status,unit\n"
    text += "01-01-2019,01:00,2,N,ugm-3,20,R,ugm-3\n"
    text += "01-01-2019,02:00,2,R,ugm-3,21,N,ugm-3\n"
    text += "01-01-2019,03:00,2,R,ugm-3,22,P,ugm-3\n"
    text += "01-01-2019,04:00,2,R,ugm-3,23,P*,ugm-3\n"
    text += "01-01-2019,05:00,2,R,ugm-3,-99,R,ugm-3\n"
    text += "01-01-2019,25:00,2,R,ugm-3,24,R,ugm-3\n"
    receipts = []
    s = UKAirProvider.parse_column_csv(text, receipts, sensor="AURN BR11")
    assert s.tolist() == [20.0, 22.0, 23.0]
    assert [r["reason"] for r in receipts] == ["invalid-status", "invalid", "invalid-time"]
    assert all(r["sensor"] == "AURN BR11" for r in receipts)


def test_nox_expressed_as_no2_is_not_the_no2_measurement():
    text = "Date,Time,Nitrogen oxides as nitrogen dioxide,status,Nitrogen dioxide,status\n01/01/2019,00:00,120,R,30,R\n"
    assert UKAirProvider.parse_column_csv(text).tolist() == [30.0]


def test_laqn_exclusive_end_date_preserves_chunk_boundary_and_final_day():
    import re

    class ExclusiveEndpoint:
        def get_json(self, namespace, url, **kwargs):
            start, end = re.search(r"StartDate=([^/]+)/EndDate=([^/]+)", url).groups()
            hours = pd.date_range(start, end, freq="h", inclusive="left")
            return {"RawAQData": {"Data": [{"@MeasurementDateGMT": str(t), "@Value": "20"} for t in hours]}}

    station = AirStation(code="BL0", name="Bloomsbury", lat=51.5, lon=-0.1,
                         site_type="Urban Background", source="LAQN")
    s, receipts = LAQNProvider(ExclusiveEndpoint()).hourly_no2(station, "2018-03-08", "2019-07-08")
    expected = pd.date_range("2018-03-08", "2019-07-09", freq="h", inclusive="left")
    assert s.index.equals(expected)
    assert len(s.loc["2019-03-07"]) == 24
    assert len(s.loc["2019-07-08"]) == 24
    assert not receipts


def test_laqn_active_dates_follow_no2_instrument_not_only_site():
    from datetime import date

    class MetadataEndpoint:
        def get_json(self, *args, **kwargs):
            return {"Sites": {"Site": [
                {"@SiteCode": "OLD", "@Latitude": "51.5", "@Longitude": "-.1",
                 "@DateOpened": "2003-01-01", "@DateClosed": "2023-07-03",
                 "Species": {"@SpeciesCode": "NO2", "@DateMeasurementStarted": "2002-01-01", "@DateMeasurementFinished": "2006-10-01"}},
                {"@SiteCode": "NEW", "@Latitude": "51.5", "@Longitude": "-.1",
                 "@DateOpened": "2011-06-29", "@DateClosed": "",
                 "Species": [{"@SpeciesCode": "NO2", "@DateMeasurementStarted": "2025-04-07", "@DateMeasurementFinished": ""}]},
            ]}}

    old, new = LAQNProvider(MetadataEndpoint()).sites()
    assert not old.active_on(date(2019, 4, 8))
    assert not new.active_on(date(2023, 8, 29))
    assert old.active_on(date(2005, 1, 1))
    assert new.active_on(date(2025, 5, 1))
    assert new.metadata["site_date_opened"] == "2011-06-29"
