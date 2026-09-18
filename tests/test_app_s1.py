"""Tests for src/app/s1.py: gamma0 dB conversion, orbit selection, receipts."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from src.app.extract import Zones
from src.app.providers import Scene
from src.app.s1 import process_scene, select_orbit_scenes, to_db

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


# ---------------------------------------------------------------- to_db


def test_to_db():
    out = to_db(np.array([1.0, 0.1, 0.0]))
    assert np.isclose(out[0], 0.0)
    assert np.isclose(out[1], -10.0)
    assert np.isnan(out[2])


# ---------------------------------------------------------------- select_orbit_scenes


def _s1_scene(id_, orbit_state, relative_orbit, geometry=None):
    return Scene(id=id_, sensor="S1", datetime=datetime(2023, 6, 1, tzinfo=timezone.utc),
                 hrefs={}, props={"orbit_state": orbit_state, "relative_orbit": relative_orbit},
                 geometry=geometry)


def test_select_orbit_scenes_keeps_majority_orbit():
    area = box(0, 0, 10, 10)
    scenes = [
        _s1_scene("a", "descending", 154),
        _s1_scene("b", "descending", 154),
        _s1_scene("c", "descending", 154),
        _s1_scene("d", "ascending", 132),
    ]

    keep, receipts, best = select_orbit_scenes(scenes, area)

    assert best == "descending-154"
    assert len(keep) == 3
    assert {s.id for s in keep} == {"a", "b", "c"}
    assert len(receipts) == 1
    assert receipts[0].reason == "orbit"


def test_select_orbit_scenes_excludes_non_intersecting_geometry():
    area = box(0, 0, 10, 10)
    outside = box(100, 100, 110, 110)
    scenes = [
        _s1_scene("a", "descending", 154, geometry=area),
        _s1_scene("b", "descending", 154, geometry=area),
        _s1_scene("c", "descending", 154, geometry=outside),   # excluded, no receipt
        _s1_scene("d", "ascending", 132, geometry=area),
    ]

    keep, receipts, best = select_orbit_scenes(scenes, area)

    assert best == "descending-154"
    assert {s.id for s in keep} == {"a", "b"}
    # only "d" (ascending, still covering) gets an orbit receipt; "c" is dropped silently
    assert len(receipts) == 1
    assert receipts[0].scene_id == "d"


# ---------------------------------------------------------------- process_scene


def _zones(tmp_path):
    zone0 = box(600200, 5859600, 600400, 5859800)   # 200 x 200 m
    zone1 = box(600600, 5859600, 600800, 5859800)   # 200 x 200 m, disjoint
    return Zones.build([zone0, zone1], EPSG, EPSG)


def _rasters(tmp_path, vv_value=0.1, vh_value=0.01, vv_nodata_slice=None, nodata=-32768.0):
    vv = np.full((120, 120), vv_value, dtype="float32")
    vh = np.full((120, 120), vh_value, dtype="float32")
    if vv_nodata_slice is not None:
        vv[vv_nodata_slice] = nodata
    vv_path = _write_raster(str(tmp_path / "vv.tif"), vv, res=10.0, nodata=nodata)
    vh_path = _write_raster(str(tmp_path / "vh.tif"), vh, res=10.0, nodata=nodata)
    return {"VV": vv_path, "VH": vh_path}


def _scene(hrefs):
    return Scene(id="s", sensor="S1", datetime=datetime(2023, 6, 1, tzinfo=timezone.utc),
                 hrefs=hrefs, props={"orbit_state": "descending", "relative_orbit": 154})


def test_process_scene_all_valid(tmp_path):
    zones = _zones(tmp_path)
    hrefs = _rasters(tmp_path)
    scene = _scene(hrefs)

    obs, receipt = process_scene(scene, zones, sign=lambda h: h)

    assert receipt is None
    assert obs is not None
    assert abs(obs.values["VV"][0] - (-10.0)) < 1e-4
    assert abs(obs.values["VH"][0] - (-20.0)) < 1e-4
    assert abs(obs.values["RATIO"][0] - (-10.0)) < 1e-4
    assert obs.valid_frac[0] == 1.0


def test_process_scene_zone1_nodata(tmp_path):
    zones = _zones(tmp_path)
    # zone1 -> rows 20:40, cols 60:80 at 10 m res (600600-600800, 5859600-5859800)
    hrefs = _rasters(tmp_path, vv_nodata_slice=np.s_[20:40, 60:80])
    scene = _scene(hrefs)

    obs, receipt = process_scene(scene, zones, sign=lambda h: h)

    assert receipt is None
    assert obs is not None
    assert np.isnan(obs.values["VV"][1])
    assert obs.valid_frac[1] == 0


def test_process_scene_zone0_nodata_is_outside(tmp_path):
    zones = _zones(tmp_path)
    # zone0 -> rows 20:40, cols 20:40 at 10 m res (600200-600400, 5859600-5859800)
    hrefs = _rasters(tmp_path, vv_nodata_slice=np.s_[20:40, 20:40])
    scene = _scene(hrefs)

    obs, receipt = process_scene(scene, zones, sign=lambda h: h)

    assert obs is None
    assert receipt is not None
    assert receipt.reason == "outside"
