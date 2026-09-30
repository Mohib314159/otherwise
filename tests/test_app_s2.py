"""Tests for src/app/s2.py: cloud masking, baseline harmonisation, indices, receipts."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from src.app.extract import Zones
from src.app.providers import Scene
from src.app.s2 import (
    S2Observation,
    despike,
    indices_from_bands,
    merge_duplicates,
    needs_offset,
    process_scene,
    reflectance,
)

EPSG = 32630
ORIGIN = (600000, 5860000)


def _write_raster(path, array, res, nodata=None, origin=ORIGIN, epsg=EPSG):
    transform = from_origin(origin[0], origin[1], res, res)
    with rasterio.open(
        path, "w", driver="GTiff", height=array.shape[0], width=array.shape[1], count=1,
        dtype=array.dtype, crs=f"EPSG:{epsg}", transform=transform, nodata=nodata,
    ) as ds:
        ds.write(array, 1)
    return path


# ---------------------------------------------------------------- needs_offset


@pytest.mark.parametrize(
    "baseline,expected",
    [
        ("03.01", False),
        ("04.00", True),
        ("05.10", True),
        ("garbage", False),
        (None, False),
    ],
)
def test_needs_offset(baseline, expected):
    assert needs_offset(baseline) is expected


# ---------------------------------------------------------------- reflectance


def test_reflectance_with_offset():
    dn = np.array([1500, 500], dtype="uint16")
    out = reflectance(dn, "05.10")
    assert np.allclose(out, [0.05, 0.0])


def test_reflectance_without_offset():
    dn = np.array([1500, 500], dtype="uint16")
    out = reflectance(dn, "03.00")
    assert np.allclose(out, [0.15, 0.05])


# ---------------------------------------------------------------- indices


def test_indices_from_bands():
    b03 = np.array([0.1])
    b04 = np.array([0.2])
    b08 = np.array([0.6])
    b12 = np.array([0.3])
    idx = indices_from_bands(b03, b04, b08, b12)
    assert np.isclose(idx["NDVI"][0], 0.5)
    assert np.isclose(idx["NDWI"][0], -5 / 7)
    assert np.isclose(idx["NBR"][0], 1 / 3)


def test_indices_from_bands_zero_denominator_is_nan():
    zero = np.array([0.0])
    idx = indices_from_bands(zero, zero, zero, zero)
    assert np.isnan(idx["NDVI"][0])
    assert np.isnan(idx["NDWI"][0])
    assert np.isnan(idx["NBR"][0])


# ---------------------------------------------------------------- despike


def _dates(n, step_days=10):
    base = np.datetime64("2023-01-01")
    return np.array([base + np.timedelta64(i * step_days, "D") for i in range(n)])


def test_despike_flags_single_dip():
    dates = _dates(12)
    ndvi = np.full(12, 0.6)
    ndvi[5] = 0.2
    suspect = despike(dates, ndvi)
    assert suspect.tolist() == [i == 5 for i in range(12)]


def test_despike_step_change_not_flagged():
    dates = _dates(12)
    ndvi = np.array([0.6] * 6 + [0.2] * 6)
    suspect = despike(dates, ndvi)
    assert not suspect.any()


def test_despike_keeps_dip_with_ndwi_water_rise():
    """E7: a one-observation NDVI dip whose NDWI rises above its neighbours
    and above 0 is water, not haze, and is kept."""
    dates = _dates(12)
    ndvi = np.full(12, 0.6); ndvi[5] = -0.1
    ndwi = np.full(12, -0.45); ndwi[5] = 0.3
    assert not despike(dates, ndvi, ndwi=ndwi).any()
    assert despike(dates, ndvi).tolist() == [i == 5 for i in range(12)]   # NDVI alone still drops it


def test_despike_still_drops_haze_dip_without_ndwi_rise():
    dates = _dates(12)
    ndvi = np.full(12, 0.6); ndvi[5] = 0.2
    ndwi = np.full(12, -0.45)                        # NDWI flat: no water signal
    assert despike(dates, ndvi, ndwi=ndwi).tolist() == [i == 5 for i in range(12)]


def test_despike_still_drops_haze_that_raises_ndwi_but_stays_below_zero():
    """Haze pulls NDWI up towards 0 (a rise well past the threshold) but not
    above it; that is still haze."""
    dates = _dates(12)
    ndvi = np.full(12, 0.6); ndvi[5] = 0.2
    ndwi = np.full(12, -0.45); ndwi[5] = -0.05
    assert despike(dates, ndvi, ndwi=ndwi).tolist() == [i == 5 for i in range(12)]


def test_despike_positive_ndwi_without_rise_is_still_dropped():
    """A permanently wet area (NDWI always > 0): an NDVI dip with no NDWI rise
    relative to its neighbours is treated as haze, as before."""
    dates = _dates(12)
    ndvi = np.full(12, 0.3); ndvi[5] = -0.1
    ndwi = np.full(12, 0.25); ndwi[5] = 0.28
    assert despike(dates, ndvi, ndwi=ndwi).tolist() == [i == 5 for i in range(12)]


def test_despike_nan_ndwi_falls_back_to_ndvi_only():
    dates = _dates(12)
    ndvi = np.full(12, 0.6); ndvi[5] = -0.1
    ndwi = np.full(12, np.nan)
    assert despike(dates, ndvi, ndwi=ndwi).tolist() == [i == 5 for i in range(12)]


def test_despike_all_nan_is_all_false():
    dates = _dates(12)
    ndvi = np.full(12, np.nan)
    suspect = despike(dates, ndvi)
    assert not suspect.any()


# ---------------------------------------------------------------- process_scene


def _zones_and_rasters(tmp_path, scl_override_zone0=None, scl_default=4,
                        b04=2000, b08=5000, b03=1500, b12=3000):
    zone0 = box(600200, 5859600, 600400, 5859800)   # 200 x 200 m
    zone1 = box(600600, 5859600, 600800, 5859800)   # 200 x 200 m, disjoint
    zones = Zones.build([zone0, zone1], EPSG, EPSG)

    # SCL: 20 m, 60x60 px, origin (600000, 5860000)
    scl = np.full((60, 60), scl_default, dtype="uint8")
    if scl_override_zone0 is not None:
        # zone0 (600200-600400, 5859600-5859800) -> rows 10:20, cols 10:20 at 20 m res
        scl[10:20, 10:20] = scl_override_zone0
    scl_path = _write_raster(str(tmp_path / "scl.tif"), scl, res=20.0)

    # B03/B04/B08: 10 m, 120x120 px
    b03_path = _write_raster(str(tmp_path / "b03.tif"),
                             np.full((120, 120), b03, dtype="uint16"), res=10.0)
    b04_path = _write_raster(str(tmp_path / "b04.tif"),
                             np.full((120, 120), b04, dtype="uint16"), res=10.0)
    b08_path = _write_raster(str(tmp_path / "b08.tif"),
                             np.full((120, 120), b08, dtype="uint16"), res=10.0)
    # B12: 20 m, 60x60 px
    b12_path = _write_raster(str(tmp_path / "b12.tif"),
                             np.full((60, 60), b12, dtype="uint16"), res=20.0)

    hrefs = {"SCL": scl_path, "B03": b03_path, "B04": b04_path, "B08": b08_path, "B12": b12_path}
    return zones, hrefs


def _scene(hrefs, baseline="05.10"):
    return Scene(id="s", sensor="S2", datetime=datetime(2023, 6, 1, tzinfo=timezone.utc),
                 hrefs=hrefs, props={"baseline": baseline, "tile": "30UXD"})


def test_process_scene_clear_observation(tmp_path):
    zones, hrefs = _zones_and_rasters(tmp_path, scl_override_zone0=None, scl_default=4)
    scene = _scene(hrefs, baseline="05.10")

    obs, receipt = process_scene(scene, zones, sign=lambda h: h)

    assert receipt is None
    assert obs is not None
    expected_ndvi = (0.4 - 0.1) / (0.4 + 0.1)
    assert abs(obs.values["NDVI"][0] - expected_ndvi) < 1e-5
    assert obs.clear_frac[0] == 1.0


def test_process_scene_cloud_receipt(tmp_path):
    zones, hrefs = _zones_and_rasters(tmp_path, scl_override_zone0=None, scl_default=9)
    scene = _scene(hrefs, baseline="05.10")

    obs, receipt = process_scene(scene, zones, sign=lambda h: h)

    assert obs is None
    assert receipt is not None
    assert receipt.reason == "cloud"


def test_process_scene_cloud_shadow_zone0(tmp_path):
    zones, hrefs = _zones_and_rasters(tmp_path, scl_override_zone0=3, scl_default=4)
    scene = _scene(hrefs, baseline="05.10")

    obs, receipt = process_scene(scene, zones, sign=lambda h: h)

    assert obs is None
    assert receipt is not None
    assert receipt.reason == "cloud"
    assert "cloud shadow" in receipt.detail


# ---------------------------------------------------------------- merge_duplicates


def _s2obs(scene_id, minute_key, ndvi_zone0, ndvi_zone1, clear0=1.0, clear1=1.0):
    return S2Observation(
        scene_id=scene_id, date="2023-06-01", minute_key=minute_key,
        values={"NDVI": np.array([ndvi_zone0, ndvi_zone1])},
        clear_frac=np.array([clear0, clear1]),
        n_pixels=np.array([100, 100]),
    )


def test_merge_duplicates_same_minute_key():
    o1 = _s2obs("s1", "2023-06-01T10:30", 0.4, np.nan)
    o2 = _s2obs("s2", "2023-06-01T10:30", 0.4, 0.5)

    out, receipts = merge_duplicates([o1, o2])

    assert len(out) == 1
    assert np.allclose(out[0].values["NDVI"], [0.4, 0.5])
    assert len(receipts) == 1
    assert receipts[0].reason == "duplicate"


def test_merge_duplicates_different_minute_keys_both_kept():
    o1 = _s2obs("s1", "2023-06-01T10:30", 0.4, 0.3)
    o2 = _s2obs("s2", "2023-06-01T10:40", 0.5, 0.2)

    out, receipts = merge_duplicates([o1, o2])

    assert len(out) == 2
    assert receipts == []
