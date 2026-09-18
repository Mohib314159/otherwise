"""Tests for src/app/series.py: AreaData persistence and cache keys."""
from __future__ import annotations

import numpy as np

from src.app.series import AreaData, SensorSeries, cache_key

SQUARE = {
    "type": "Polygon",
    "coordinates": [[[-1.29, 52.9], [-1.2854, 52.9], [-1.2854, 52.9028], [-1.29, 52.9028], [-1.29, 52.9]]],
}
SQUARE2 = {
    "type": "Polygon",
    "coordinates": [[[-1.30, 52.9], [-1.2954, 52.9], [-1.2954, 52.9028], [-1.30, 52.9028], [-1.30, 52.9]]],
}


def _area_data():
    dates = np.array(["2023-06-01", "2023-06-11", "2023-06-21"])
    ndvi = np.array([[0.5, 0.4, 0.3, 0.2],
                      [np.nan, 0.4, 0.3, 0.2],
                      [0.6, 0.5, 0.4, 0.3]], dtype="float32")
    clear_frac = np.ones((3, 4), dtype="float32")
    s2 = SensorSeries(
        sensor="S2", dates=dates,
        values={"NDVI": ndvi, "clear_frac": clear_frac},
        scene_ids=["s1", "s2", "s3"], meta={"provider": "planetary-computer"},
    )
    receipts = [
        {"sensor": "S2", "date": "2023-06-05", "scene_id": "x", "reason": "cloud",
         "detail": "too cloudy", "value": 0.4},
        {"sensor": "S1", "date": "2023-06-06", "scene_id": "y", "reason": "orbit",
         "detail": "wrong orbit", "value": None},
    ]
    summary = {"s2_observations": 3, "s1_observations": 0}
    return AreaData(
        area_geojson=SQUARE, area_ha=10.0, epsg=32630,
        cells_geojson=[], cell_distance_m=[], start="2023-01-01", end="2023-12-31",
        s2=s2, s1=None, receipts=receipts, summary=summary,
    )


def test_area_data_save_and_load_round_trip(tmp_path):
    data = _area_data()
    out_dir = tmp_path / "c"
    data.save(str(out_dir))

    loaded = AreaData.load(str(out_dir))

    assert list(loaded.s2.dates) == list(data.s2.dates)
    assert np.allclose(loaded.s2.values["NDVI"], data.s2.values["NDVI"], equal_nan=True)
    assert np.allclose(loaded.s2.values["clear_frac"], data.s2.values["clear_frac"], equal_nan=True)
    assert loaded.receipts == data.receipts
    assert loaded.summary == data.summary
    assert loaded.s1 is None
    assert loaded.area_ha == data.area_ha
    assert loaded.epsg == data.epsg


def test_cache_key_stable_across_calls():
    k1 = cache_key(SQUARE, "2021-01-01", "2023-12-31", "sig")
    k2 = cache_key(SQUARE, "2021-01-01", "2023-12-31", "sig")
    assert k1 == k2
    assert len(k1) == 16
    int(k1, 16)  # is valid hex


def test_cache_key_differs_with_start_date():
    k1 = cache_key(SQUARE, "2021-01-01", "2023-12-31", "sig")
    k2 = cache_key(SQUARE, "2021-02-01", "2023-12-31", "sig")
    assert k1 != k2


def test_cache_key_differs_with_grid_signature():
    k1 = cache_key(SQUARE, "2021-01-01", "2023-12-31", "sig-a")
    k2 = cache_key(SQUARE, "2021-01-01", "2023-12-31", "sig-b")
    assert k1 != k2
