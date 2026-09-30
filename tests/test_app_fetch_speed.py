"""Equivalence tests for the fetch speed-ups: the optimised S2 path must give
exactly the numbers and receipts the original path gave.

`_reference_process_scene` is a verbatim copy of `s2.process_scene` before the
zone-0 SCL gate and the label cache were introduced; every case compares the
two for exact equality (same receipts, bit-identical arrays).
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from src.app import s2 as s2mod
from rasterio.windows import Window

from src.app.extract import (GDAL_ENV, Zones, _window, cached_labels, labels_for, read_geometry,
                             zone_bbox, zone_counts, zone_means)
from src.app.providers import Scene

EPSG = 32633
X0, Y0 = 600000.0, 5860000.0


def _write(path, arr, res, origin=(X0, Y0), block=32):
    h, w = arr.shape
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1, dtype=arr.dtype,
                       crs=f"EPSG:{EPSG}", transform=from_origin(origin[0], origin[1], res, res),
                       tiled=True, blockxsize=block, blockysize=block, compress="deflate") as ds:
        ds.write(arr, 1)
    return str(path)


def _reference_read_window(href, zones, out_res=None):
    """extract.read_window as it was: GDAL does the nearest-neighbour upsample."""
    with rasterio.Env(**GDAL_ENV):
        with rasterio.open(href) as ds:
            win = _window(ds, zones.bounds)
            if win is None:
                return None
            if out_res and (abs(ds.res[0] - out_res) > 1e-9 or abs(ds.res[1] - out_res) > 1e-9):
                fy, fx = ds.res[1] / out_res, ds.res[0] / out_res
                out_shape = (max(int(round(win.height * fy)), 1), max(int(round(win.width * fx)), 1))
                arr = ds.read(1, window=win, out_shape=out_shape,
                              resampling=rasterio.enums.Resampling.nearest)
                tr = ds.window_transform(win)
                tr = rasterio.Affine(out_res, 0, tr.c, 0, -out_res, tr.f)
            else:
                arr = ds.read(1, window=win)
                tr = ds.window_transform(win)
            return arr, tr, ds.nodata


def _reference_process_scene(scene, zones, sign, res=10.0, require_zone0=True):
    """s2.process_scene as it was before the speed-ups (verbatim logic)."""
    n = len(zones.polygons)
    r = _reference_read_window(sign(scene.hrefs["SCL"]), zones, out_res=res)
    if r is None:
        return None, s2mod.Receipt("S2", scene.date, scene.id, "outside",
                                   "Scene footprint does not cover the area.")
    scl, tr, _ = r
    labels = labels_for(zones, tr, scl.shape)
    clear = np.isin(scl, s2mod.SCL_CLEAR)
    n_clear, n_total = zone_counts(labels, n, clear)
    with np.errstate(invalid="ignore", divide="ignore"):
        clear_frac = np.where(n_total > 0, n_clear / np.maximum(n_total, 1), 0.0)
    if not require_zone0:
        if not np.any(clear_frac >= s2mod.CLEAR_MIN):
            return None, s2mod.Receipt("S2", scene.date, scene.id, "cloud", "No donor cell in this group is clear.")
    elif n_total[0] == 0:
        return None, s2mod.Receipt("S2", scene.date, scene.id, "outside",
                                   "Scene footprint does not cover the area.")
    elif clear_frac[0] < s2mod.CLEAR_MIN:
        bd = s2mod.scl_breakdown(scl, labels)
        worst = max(((k, v) for k, v in bd.items() if k not in ("vegetation", "bare", "water")),
                    key=lambda kv: kv[1], default=("cloud", 1 - clear_frac[0]))
        return None, s2mod.Receipt("S2", scene.date, scene.id, "cloud",
                                   f"Only {clear_frac[0]:.0%} of the area is clear "
                                   f"({worst[0]} over {worst[1]:.0%}); dropped.",
                                   value=float(clear_frac[0]))
    del scl
    baseline = scene.props.get("baseline", "00.00")

    def band(name):
        rr = _reference_read_window(sign(scene.hrefs[name]), zones, out_res=res)
        if rr is None or rr[0].shape != labels.shape:
            return None
        return s2mod.reflectance(rr[0], baseline)

    b08 = band("B08")
    values = {}
    for name, partner, order in (("NDVI", "B04", "b08_first"), ("NDWI", "B03", "partner_first"),
                                 ("NBR", "B12", "b08_first")):
        other = band(partner)
        arr = s2mod._nd(b08, other) if order == "b08_first" else s2mod._nd(other, b08)
        v = clear & np.isfinite(arr)
        np.nan_to_num(arr, copy=False)
        m, _, _ = zone_means(arr, v, labels, n)
        m[clear_frac < s2mod.CLEAR_MIN] = np.nan
        values[name] = m
    return s2mod.S2Observation(scene.id, scene.date, scene.minute_key, values, clear_frac, n_total,
                               props=dict(scene.props)), None


def _random_polygon(rng, cx, cy, r):
    k = int(rng.integers(3, 9))
    ang = np.sort(rng.uniform(0, 2 * np.pi, k))
    rad = rng.uniform(0.4 * r, r, k)
    return Polygon(list(zip(cx + rad * np.cos(ang), cy + rad * np.sin(ang))))


def _case(tmp_path, rng, cloud_p, origin_shift):
    """A 20 m SCL raster with patchy cloud (cloud probability `cloud_p`) and 10/20 m
    bands with random DNs, a treated polygon and a few donor polygons. The raster
    origin is shifted so some windows are clipped by the raster edge."""
    ox, oy = X0 + origin_shift[0], Y0 + origin_shift[1]
    n20 = 90                                            # 1800 m at 20 m
    coarse = rng.random((n20 // 6 + 1, n20 // 6 + 1)) < cloud_p
    cloudy = np.kron(coarse, np.ones((6, 6), bool))[:n20, :n20] | (rng.random((n20, n20)) < cloud_p / 4)
    scl = np.where(cloudy, rng.choice([3, 8, 9, 10], (n20, n20)), rng.choice([4, 5, 6], (n20, n20))).astype("uint8")
    scl[rng.random((n20, n20)) < 0.02] = 0
    hrefs = {"SCL": _write(tmp_path / "scl.tif", scl, 20.0, (ox, oy))}
    for b, res, n in (("B03", 10.0, 2 * n20), ("B04", 10.0, 2 * n20), ("B08", 10.0, 2 * n20), ("B12", 20.0, n20)):
        arr = rng.integers(0, 12000, (n, n)).astype("uint16")
        arr[rng.random((n, n)) < 0.01] = 0
        hrefs[b] = _write(tmp_path / f"{b}.tif", arr, res, (ox, oy))
    polys = [_random_polygon(rng, X0 + rng.uniform(300, 1500), Y0 - rng.uniform(300, 1500), rng.uniform(40, 250))]
    for _ in range(int(rng.integers(1, 8))):
        polys.append(_random_polygon(rng, X0 + rng.uniform(-200, 2000), Y0 - rng.uniform(-200, 2000),
                                     rng.uniform(40, 300)))
    zones = Zones.build(polys, EPSG, EPSG)
    scene = Scene(id="s", sensor="S2", datetime=datetime(2020, 6, 1, 10, 30, tzinfo=timezone.utc),
                  hrefs=hrefs, props={"baseline": str(rng.choice(["02.08", "04.00", "05.09"])), "tile": "33UVU"})
    return scene, zones


def _same(a, b):
    oa, ra = a
    ob, rb = b
    assert ra == rb
    assert (oa is None) == (ob is None)
    if oa is not None:
        assert oa.values.keys() == ob.values.keys()
        for k in oa.values:
            np.testing.assert_array_equal(oa.values[k], ob.values[k])     # bit-identical, NaN == NaN
        np.testing.assert_array_equal(oa.clear_frac, ob.clear_frac)
        np.testing.assert_array_equal(oa.n_pixels, ob.n_pixels)


@pytest.mark.parametrize("seed", range(24))
def test_process_scene_matches_reference(tmp_path, seed):
    rng = np.random.default_rng(seed)
    cloud_p = [0.0, 0.05, 0.15, 0.3, 0.6, 0.9][seed % 6]
    shift = [(0, 0), (-300, 0), (0, 420), (-540, 360)][seed // 6]
    scene, zones = _case(tmp_path, rng, cloud_p, shift)
    for require_zone0 in (True, False):
        ref = _reference_process_scene(scene, zones, lambda h: h, require_zone0=require_zone0)
        new = s2mod.process_scene(scene, Zones.build(zones.polygons, EPSG, EPSG), lambda h: h,
                                  require_zone0=require_zone0)
        _same(new, ref)
        # and again on a Zones whose label cache is already warm
        _same(s2mod.process_scene(scene, zones, lambda h: h, require_zone0=require_zone0), ref)
        _same(s2mod.process_scene(scene, zones, lambda h: h, require_zone0=require_zone0), ref)


def test_both_gate_outcomes_are_exercised(tmp_path, monkeypatch):
    """Both outcomes occur in the cases above, and a cloud drop is decided
    without the full-window SCL read."""
    full_reads = []
    real = s2mod.read_geometry
    monkeypatch.setattr(s2mod, "read_geometry", lambda ds, g: full_reads.append(1) or real(ds, g))
    kinds = set()
    for seed in range(24):
        rng = np.random.default_rng(seed)
        scene, zones = _case(tmp_path, rng, [0.0, 0.05, 0.15, 0.3, 0.6, 0.9][seed % 6],
                             [(0, 0), (-300, 0), (0, 420), (-540, 360)][seed // 6])
        full_reads.clear()
        o, r = s2mod.process_scene(scene, zones, lambda h: h)
        kinds.add("obs" if o is not None else r.reason)
        if r is not None and r.reason == "cloud":
            assert not full_reads
    assert {"obs", "cloud"} <= kinds


def test_cached_labels_equal_labels_for_and_bbox():
    rng = np.random.default_rng(0)
    polys = [_random_polygon(rng, X0 + rng.uniform(0, 1000), Y0 - rng.uniform(0, 1000), 150) for _ in range(5)]
    zones = Zones.build(polys, EPSG, EPSG)
    tr = from_origin(zones.bounds[0], zones.bounds[3], 10.0, 10.0)
    shape = (int((zones.bounds[3] - zones.bounds[1]) / 10), int((zones.bounds[2] - zones.bounds[0]) / 10))
    lab, bb = cached_labels(zones, tr, shape)
    np.testing.assert_array_equal(lab, labels_for(zones, tr, shape))
    assert not lab.flags.writeable
    assert cached_labels(zones, tr, shape)[0] is lab
    rows, cols = np.nonzero(lab == 1)
    assert bb == (rows.min(), rows.max() + 1, cols.min(), cols.max() + 1)
    assert zone_bbox(np.zeros((4, 4), "int32")) is None


def _reference_reflectance(dn, baseline):
    x = dn.astype("float32")
    if s2mod.needs_offset(baseline):
        x = np.clip(x - s2mod.DN_OFFSET, 0.0, None)
    return x / 10000.0


@pytest.mark.parametrize("baseline", ["02.08", "04.00", "05.10", None, "garbage"])
def test_reflectance_in_place_is_bit_identical(baseline):
    rng = np.random.default_rng(1)
    dn = rng.integers(0, 65536, (300, 257)).astype("uint16")
    dn[0], dn[1], dn[2] = 0, 999, 1000          # below, just below and at the offset
    got, ref = s2mod.reflectance(dn, baseline), _reference_reflectance(dn, baseline)
    assert got.dtype == ref.dtype == np.float32
    np.testing.assert_array_equal(got.view("uint32"), ref.view("uint32"))


@pytest.mark.parametrize("k", [2, 3, 4])
@pytest.mark.parametrize("dtype", ["uint8", "uint16", "float32"])
def test_integer_upsample_matches_gdal_nearest(tmp_path, k, dtype):
    """read_geometry's native-read-and-repeat equals GDAL's nearest upsample,
    for random windows including ones at the raster edge."""
    rng = np.random.default_rng(k)
    arr = (rng.random((150, 170)) * 250).astype(dtype)
    path = _write(tmp_path / f"r{k}{dtype}.tif", arr, 20.0, block=16)
    with rasterio.open(path) as ds:
        for _ in range(40):
            c0, r0 = int(rng.integers(0, 169)), int(rng.integers(0, 149))
            w = Window(c0, r0, int(rng.integers(1, 171 - c0)), int(rng.integers(1, 151 - r0)))
            shape = (w.height * k, w.width * k)
            gdal = ds.read(1, window=w, out_shape=shape, resampling=rasterio.enums.Resampling.nearest)
            ours = read_geometry(ds, (w, None, shape))
            assert ours.dtype == gdal.dtype
            np.testing.assert_array_equal(ours, gdal)
