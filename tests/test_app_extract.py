"""Tests for src/app/extract.py: windowed zonal statistics."""
from __future__ import annotations

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from src.app.extract import Zones, labels_for, read_window, zone_means

EPSG = 32630
ORIGIN_X, ORIGIN_Y = 600000, 5860000


def _write_raster(path, array, res=10.0, dtype=None, nodata=None,
                   origin=(ORIGIN_X, ORIGIN_Y), epsg=EPSG):
    array = np.asarray(array)
    if dtype is not None:
        array = array.astype(dtype)
    h, w = array.shape
    transform = from_origin(origin[0], origin[1], res, res)
    with rasterio.open(
        path, "w", driver="GTiff", height=h, width=w, count=1,
        dtype=array.dtype, crs=f"EPSG:{epsg}", transform=transform, nodata=nodata,
    ) as ds:
        ds.write(array, 1)
    return path


def _native_raster(tmp_path, name="native.tif", value=1.0, dtype="float32", nodata=None,
                    fill=None, res=10.0, size=120):
    arr = np.full((size, size), value, dtype=dtype)
    if fill is not None:
        arr[:] = fill
    return _write_raster(str(tmp_path / name), arr, res=res, nodata=nodata)


def test_zones_build_bounds_multiples_of_60_and_contain_polygons():
    poly1 = box(600100, 5860100, 600300, 5860300)
    poly2 = box(600500, 5860500, 600700, 5860700)
    zones = Zones.build([poly1, poly2], EPSG, EPSG, pad_m=20.0)

    assert len(zones.polygons) == 2
    minx, miny, maxx, maxy = zones.bounds
    assert minx % 60 == 0
    assert miny % 60 == 0
    assert maxx % 60 == 0
    assert maxy % 60 == 0
    for poly in (poly1, poly2):
        pminx, pminy, pmaxx, pmaxy = poly.bounds
        assert minx <= pminx and miny <= pminy
        assert maxx >= pmaxx and maxy >= pmaxy


def test_read_window_shape_and_transform(tmp_path):
    # raster covers x:[600000,601200], y:[5858800,5860000] (origin is top-left)
    path = _native_raster(tmp_path, value=5.0)
    poly = box(600100, 5859700, 600300, 5859900)
    zones = Zones.build([poly], EPSG, EPSG, pad_m=20.0)

    result = read_window(path, zones)
    assert result is not None
    arr, transform, nodata = result

    minx, miny, maxx, maxy = zones.bounds
    expected_w = round((maxx - minx) / 10.0)
    expected_h = round((maxy - miny) / 10.0)
    assert arr.shape == (expected_h, expected_w)
    assert transform.c == minx
    assert transform.f == maxy


def test_read_window_resample_to_10m_doubles_size_and_is_nearest(tmp_path):
    # 20 m native raster, same origin, 60x60 px -> 1200x1200 m extent
    size = 60
    arr = np.arange(size * size, dtype="float32").reshape(size, size)
    path = _write_raster(str(tmp_path / "twenty.tif"), arr, res=20.0)

    poly = box(600100, 5860100 - 400, 600300, 5860300 - 400)
    # keep inside the 1200x1200 extent starting at (600000, 5860000) going down
    # raster covers x:[600000,601200], y:[5858800,5860000]
    poly = box(600100, 5859100, 600300, 5859300)
    zones = Zones.build([poly], EPSG, EPSG, pad_m=20.0)

    native = read_window(path, zones)
    assert native is not None
    native_arr, native_tr, _ = native

    resampled = read_window(path, zones, out_res=10.0)
    assert resampled is not None
    res_arr, res_tr, _ = resampled

    assert res_arr.shape == (native_arr.shape[0] * 2, native_arr.shape[1] * 2)

    # nearest resampling: each native pixel appears as a 2x2 block
    for i in range(native_arr.shape[0]):
        for j in range(native_arr.shape[1]):
            block = res_arr[2 * i:2 * i + 2, 2 * j:2 * j + 2]
            assert np.all(block == native_arr[i, j])


def test_read_window_returns_none_outside_raster(tmp_path):
    path = _native_raster(tmp_path, value=1.0)
    # far away polygon, well outside the 120x120@10m = 1200x1200m raster
    poly = box(700000, 5900000, 700100, 5900100)
    zones = Zones.build([poly], EPSG, EPSG, pad_m=20.0)

    assert read_window(path, zones) is None


def test_labels_for_pixel_counts_match_area():
    # 200m x 100m rectangle aligned to the 10m grid -> 200 pixels of 100 sqm each
    poly = box(600100, 5860100, 600300, 5860200)
    zones = Zones.build([poly], EPSG, EPSG, pad_m=20.0)
    minx, miny, maxx, maxy = zones.bounds
    h = round((maxy - miny) / 10.0)
    w = round((maxx - minx) / 10.0)
    transform = from_origin(minx, maxy, 10.0, 10.0)

    labels = labels_for(zones, transform, (h, w))
    count = int((labels == 1).sum())
    assert count == 200  # (200*100)/(10*10)


def test_zone_means_basic_and_partial_validity():
    # build two zones side by side, 100x100m each on a 10m grid -> 10x10 px
    poly1 = box(600000, 5860000, 600100, 5860100)
    poly2 = box(600100, 5860000, 600200, 5860100)
    zones = Zones.build([poly1, poly2], EPSG, EPSG, pad_m=0.0)
    minx, miny, maxx, maxy = zones.bounds
    h = round((maxy - miny) / 10.0)
    w = round((maxx - minx) / 10.0)
    transform = from_origin(minx, maxy, 10.0, 10.0)
    labels = labels_for(zones, transform, (h, w))

    values = np.zeros((h, w), dtype="float32")
    values[labels == 1] = 3.0
    # zone 2: half 1.0, half 5.0
    zone2_idx = np.argwhere(labels == 2)
    half = len(zone2_idx) // 2
    for k, (r, c) in enumerate(zone2_idx):
        values[r, c] = 1.0 if k < half else 5.0

    valid = np.ones((h, w), dtype=bool)
    means, n_valid, n_total = zone_means(values, valid, labels, 2)
    assert np.isclose(means[0], 3.0)
    assert np.isclose(means[1], 3.0)

    # now make zone 2 entirely invalid
    valid2 = valid.copy()
    valid2[labels == 2] = False
    means2, n_valid2, n_total2 = zone_means(values, valid2, labels, 2)
    assert np.isnan(means2[1])
    assert n_valid2[1] == 0
    assert n_total2[1] > 0
