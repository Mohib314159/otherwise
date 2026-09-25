"""Pixel-level change test: what fraction of the area's pixels changed more than
comparable control pixels did?

The area-mean synthetic control answers "did the area's average index move more
than its counterfactual?". If only part of a drawn polygon changed, that mean is
diluted. This module works per pixel instead:

  1. two cloud-masked median composites of the chosen index (pre-year, post
     window) on the Sentinel-2 grid of one MGRS tile;
  2. control pixels = same WorldCover class as the area, outside a 300 m buffer,
     observed clear at least twice in both periods;
  3. threshold = the 5th (or 95th) percentile of control deltas, so under no
     change ~5 % of pixels are flagged by construction;
  4. fraction_changed over the area, and a placebo distribution of the same
     fraction over control cells with the area's footprint;
  5. a change map PNG for the human eye.

The numerical core (threshold, mask, cell fractions, placebo p, composite,
render) is pure and tested offline; only compute_pixel_change touches the network.
"""
from __future__ import annotations

import json
import math
import os
import warnings
from collections import Counter
from datetime import date, timedelta

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject as warp_reproject
from shapely.geometry import Point, box

from .covariates import WC_CLASSES, worldcover_url
from .extract import Zones, labels_for, read_window
from .geometry import reproject, validate_polygon
from .providers import PlanetaryComputer
from .s2 import SCL_CLEAR, _nd, reflectance
from .verdict import SIGNALS

INDEX_BANDS = {"NDVI": ("B04", "B08"), "NBR": ("B08", "B12"), "NDWI": ("B03", "B08")}
EXPECTED_NULL_FRACTION = 0.05       # the threshold is a 5 % tail of the control deltas
MIN_CLEAR = 2                       # clear observations a pixel needs in each period
BUFFER_M = 300.0                    # controls must lie outside this ring around the area
MIN_CELL_CONTROL_FRAC = 0.80        # a placebo cell needs this share of control pixels
MIN_CONTROL_PIXELS = 200
MAP_PX = 640
COLOR_DECREASE = (179, 38, 30)
COLOR_INCREASE = (43, 95, 168)
OVERLAY_ALPHA = 0.85


# ----------------------------------------------------------------------------
# pure numerical core
# ----------------------------------------------------------------------------

def index_from_bands(signal: str, bands: dict[str, np.ndarray]) -> np.ndarray:
    """Same formulas as s2.indices_from_bands, one index at a time."""
    if signal == "NDVI":
        return _nd(bands["B08"], bands["B04"])
    if signal == "NBR":
        return _nd(bands["B08"], bands["B12"])
    if signal == "NDWI":
        return _nd(bands["B03"], bands["B08"])
    raise ValueError(f"unknown signal {signal}")


def composite(arrays: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel median across scenes ignoring NaN, plus the count of finite values."""
    if not arrays:
        raise ValueError("composite of no arrays")
    stack = np.stack([np.asarray(a, dtype="float32") for a in arrays])
    count = np.isfinite(stack).sum(axis=0).astype("int32")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)     # all-NaN slices
        median = np.nanmedian(stack, axis=0).astype("float32")
    return median, count


def change_threshold(control_deltas: np.ndarray, expected_sign: int) -> float:
    """5th percentile of control deltas for an expected decrease, 95th for an
    expected increase, 95th of |delta| when either direction counts."""
    d = np.asarray(control_deltas, dtype=float)
    d = d[np.isfinite(d)]
    if d.size == 0:
        return float("nan")
    q = 100.0 * EXPECTED_NULL_FRACTION
    if expected_sign < 0:
        return float(np.percentile(d, q))
    if expected_sign > 0:
        return float(np.percentile(d, 100.0 - q))
    return float(np.percentile(np.abs(d), 100.0 - q))


def changed_mask(delta: np.ndarray, threshold: float, expected_sign: int) -> np.ndarray:
    """Pixels whose delta lies beyond the threshold in the expected direction.
    NaN deltas are never flagged."""
    d = np.asarray(delta, dtype=float)
    if not np.isfinite(threshold):
        return np.zeros(d.shape, dtype=bool)
    with np.errstate(invalid="ignore"):
        if expected_sign < 0:
            m = d < threshold
        elif expected_sign > 0:
            m = d > threshold
        else:
            m = np.abs(d) > threshold
    return m & np.isfinite(d)


def cell_labels(shape: tuple[int, int], cell_px: int) -> np.ndarray:
    """Square cells of `cell_px` pixels aligned to the array grid; label k >= 1."""
    cell_px = max(int(cell_px), 1)
    rows = np.arange(shape[0]) // cell_px
    cols = np.arange(shape[1]) // cell_px
    ncols = int(cols.max()) + 1 if shape[1] else 1
    return (rows[:, None] * ncols + cols[None, :] + 1).astype("int32")


def cell_fractions(changed: np.ndarray, control_mask: np.ndarray, labels_cells: np.ndarray,
                   min_control_frac: float = MIN_CELL_CONTROL_FRAC) -> np.ndarray:
    """fraction_changed per cell, computed over that cell's control pixels only.
    Cells whose control pixels are fewer than `min_control_frac` of a full cell
    (the largest cell in `labels_cells`) are dropped."""
    lab = np.asarray(labels_cells).ravel()
    ctrl = np.asarray(control_mask, dtype=bool).ravel()
    chg = np.asarray(changed, dtype=bool).ravel() & ctrl
    n = int(lab.max()) + 1 if lab.size else 1
    n_total = np.bincount(lab, minlength=n)
    n_ctrl = np.bincount(lab[ctrl], minlength=n)
    n_chg = np.bincount(lab[chg], minlength=n)
    full = n_total[1:].max() if n > 1 else 0
    keep = (np.arange(n) >= 1) & (n_ctrl >= min_control_frac * full) & (n_ctrl > 0)
    if full == 0 or not keep.any():
        return np.zeros(0, dtype=float)
    return n_chg[keep] / n_ctrl[keep]


def placebo_p(cell_fracs: np.ndarray, area_fraction: float) -> float | None:
    """Share of control cells at least as changed as the area, with the +1 correction."""
    c = np.asarray(cell_fracs, dtype=float)
    c = c[np.isfinite(c)]
    if c.size == 0 or not np.isfinite(area_fraction):
        return None
    return float((np.sum(c >= area_fraction) + 1) / (c.size + 1))


def render_change_map(pre_index: np.ndarray, delta: np.ndarray, changed: np.ndarray,
                      area_mask: np.ndarray, path: str, size: int = MAP_PX) -> str:
    """Greyscale pre-period index, changed pixels inside the area in colour
    (red for a decrease, blue for an increase), the area outline in white."""
    from PIL import Image

    pre = np.asarray(pre_index, dtype=float)
    finite = np.isfinite(pre)
    if finite.sum() >= 2:
        lo, hi = np.nanpercentile(pre, [2, 98])
    else:
        lo, hi = 0.0, 1.0
    if not hi > lo:
        hi = lo + 1e-6
    grey = np.clip((np.nan_to_num(pre, nan=lo) - lo) / (hi - lo), 0, 1)
    rgb = np.repeat((grey * 255.0)[:, :, None], 3, axis=2).astype("float32")

    inside = np.asarray(area_mask, dtype=bool)
    chg = np.asarray(changed, dtype=bool) & inside
    d = np.asarray(delta, dtype=float)
    with np.errstate(invalid="ignore"):
        dec = chg & (d < 0)
        inc = chg & ~(d < 0)
    for m, col in ((dec, COLOR_DECREASE), (inc, COLOR_INCREASE)):
        if m.any():
            rgb[m] = (1 - OVERLAY_ALPHA) * rgb[m] + OVERLAY_ALPHA * np.asarray(col, dtype="float32")

    edge = inside & ~(np.roll(inside, 1, 0) & np.roll(inside, -1, 0)
                      & np.roll(inside, 1, 1) & np.roll(inside, -1, 1))
    rgb[edge] = [255, 255, 255]

    img = Image.fromarray(np.clip(rgb, 0, 255).astype("uint8"))
    method = Image.NEAREST if max(pre.shape) < size else Image.BILINEAR
    img = img.resize((size, size), method)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img.save(path, optimize=True)
    return path


def render_change_overlay(delta: np.ndarray, changed: np.ndarray, eligible: np.ndarray,
                          transform, window_bounds, path: str, size: int = 480) -> str | None:
    """Transparent overlay for the verdict page's after image.

    Cropped to `window_bounds` (minx, miny, maxx, maxy in the grid's CRS), which
    the caller sets to the before/after thumbnail's own square, so the overlay
    lines up with the picture underneath. Only pixels where the test is defined
    are coloured: the area and control pixels of the area's land-cover class
    (`eligible`). Everything else is fully transparent. Red = the index fell past
    the control threshold, blue = it rose past it. By construction about 5 % of
    unchanged control pixels are coloured too; that speckle is the baseline."""
    from PIL import Image
    inv = ~transform
    c0, r0 = inv * (window_bounds[0], window_bounds[3])
    c1, r1 = inv * (window_bounds[2], window_bounds[1])
    r0, r1 = int(math.floor(min(r0, r1))), int(math.ceil(max(r0, r1)))
    c0, c1 = int(math.floor(min(c0, c1))), int(math.ceil(max(c0, c1)))
    H, W = delta.shape
    if r0 < 0 or c0 < 0 or r1 > H or c1 > W or r1 - r0 < 4 or c1 - c0 < 4:
        return None                                   # thumbnail window not inside the grid
    d = np.asarray(delta, dtype=float)[r0:r1, c0:c1]
    ch = (np.asarray(changed, bool) & np.asarray(eligible, bool))[r0:r1, c0:c1]
    rgba = np.zeros(d.shape + (4,), dtype="uint8")
    with np.errstate(invalid="ignore"):
        dec, inc = ch & (d < 0), ch & ~(d < 0)
    rgba[dec] = COLOR_DECREASE + (int(255 * OVERLAY_ALPHA),)
    rgba[inc] = COLOR_INCREASE + (int(255 * OVERLAY_ALPHA),)
    img = Image.fromarray(rgba, "RGBA").resize((size, size), Image.NEAREST)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img.save(path, optimize=True)
    return path


# ----------------------------------------------------------------------------
# network-facing pipeline
# ----------------------------------------------------------------------------

def _period_composite(prov, scenes, zones: Zones, signal: str, n_scenes: int, ref_shape=None):
    """Median composite of `signal` over the clearest `n_scenes` scenes.
    Returns (median, count, transform, dates, skipped) or None if nothing was read."""
    bands_needed = INDEX_BANDS[signal]
    order = sorted(scenes, key=lambda s: (s.props.get("cloud_cover") is None,
                                          s.props.get("cloud_cover") or 0.0, s.datetime))
    # one item per acquisition: the catalogue can hold two products of the same
    # pass (reprocessing), and a duplicate adds nothing to a median
    seen, unique = set(), []
    for sc in order:
        if sc.minute_key not in seen:
            seen.add(sc.minute_key); unique.append(sc)
    arrays, dates, skipped = [], [], []
    tr0, shape = None, ref_shape
    for sc in unique[:n_scenes]:
        try:
            r = read_window(prov.sign(sc.hrefs["SCL"]), zones, out_res=10.0)
            if r is None:
                skipped.append((sc.id, "outside")); continue
            scl, tr, _ = r
            if shape is not None and scl.shape != shape:
                skipped.append((sc.id, "shape mismatch")); continue
            bands = {}
            ok = True
            for b in bands_needed:
                rr = read_window(prov.sign(sc.hrefs[b]), zones, out_res=10.0)
                if rr is None or rr[0].shape != scl.shape:
                    ok = False; break
                bands[b] = reflectance(rr[0], sc.props.get("baseline", "00.00"))
            if not ok:
                skipped.append((sc.id, "band window mismatch")); continue
        except Exception as e:                       # network / GDAL errors: skip the scene
            skipped.append((sc.id, f"read error: {type(e).__name__}")); continue
        idx = index_from_bands(signal, bands).astype("float32")
        clear = np.isin(scl, SCL_CLEAR)
        idx[~clear] = np.nan
        arrays.append(idx)
        dates.append(sc.date)
        if tr0 is None:
            tr0, shape = tr, scl.shape
    if not arrays:
        return None
    med, cnt = composite(arrays)
    return med, cnt, tr0, dates, skipped


def _worldcover_on_grid(area, zones_geo: Zones, year: int, dst_transform, dst_shape, dst_epsg: int):
    """WorldCover class per pixel of the scene window (0 = unknown), nearest neighbour."""
    out = np.zeros(dst_shape, dtype="uint8")
    minx, miny, maxx, maxy = zones_geo.bounds
    step = 3.0
    xs = np.arange(math.floor(minx / step) * step, maxx, step)
    ys = np.arange(math.floor(miny / step) * step, maxy, step)
    for x in xs:
        for y in ys:
            url = worldcover_url(x + step / 2, y + step / 2, year)
            try:
                r = read_window(url, zones_geo)
            except Exception:
                continue
            if r is None:
                continue
            arr, tr, _ = r
            dst = np.zeros(dst_shape, dtype="uint8")
            warp_reproject(source=arr.astype("uint8"), destination=dst,
                           src_transform=tr, src_crs=CRS.from_epsg(4326),
                           dst_transform=dst_transform, dst_crs=CRS.from_epsg(dst_epsg),
                           src_nodata=0, dst_nodata=0, resampling=Resampling.nearest)
            out = np.where(out == 0, dst, out)
    return out


def _rasterize(poly, transform, shape) -> np.ndarray:
    return rasterize([(poly, 1)], out_shape=shape, transform=transform, fill=0,
                     dtype="uint8", all_touched=False).astype(bool)


def _r(x, nd=3):
    if x is None:
        return None
    x = float(x)
    return round(x, nd) if np.isfinite(x) else None


def compute_pixel_change(area_geojson: dict, event_date: str, change_type: str, post_months: int,
                         out_dir: str, run_id: str, n_scenes: int = 8, margin_km: float = 4.0) -> dict:
    notes: list[str] = []
    area = validate_polygon(area_geojson)
    signal, expected_sign, _ = SIGNALS.get(change_type, SIGNALS["other"])
    ev = date.fromisoformat(event_date)
    pre_span = (ev - timedelta(days=365), ev - timedelta(days=1))
    post_span = (ev + timedelta(days=1), ev + timedelta(days=int(post_months) * 30))

    # 1. window and scenes ------------------------------------------------------
    side = math.sqrt(area.utm.area)
    half = max(margin_km * 1000.0, 3.0 * side)
    cx, cy = area.utm.centroid.x, area.utm.centroid.y
    square = box(cx - half, cy - half, cx + half, cy + half)
    bbox = [float(v) for v in reproject(square, area.epsg, 4326).bounds]
    centre = reproject(Point(cx, cy), area.epsg, 4326)

    prov = PlanetaryComputer()
    pre_all = prov.search_s2(bbox, pre_span[0].isoformat(), pre_span[1].isoformat())
    post_all = prov.search_s2(bbox, post_span[0].isoformat(), post_span[1].isoformat())
    keep = lambda ss: [s for s in ss if s.geometry is None or s.geometry.contains(centre)]
    pre_all, post_all = keep(pre_all), keep(post_all)
    if not pre_all or not post_all:
        return {"status": "insufficient", "signal": signal, "expected_sign": expected_sign,
                "reason": f"No Sentinel-2 scenes cover the window centre in the "
                          f"{'pre' if not pre_all else 'post'} period."}
    tiles = Counter(s.props.get("tile") for s in pre_all + post_all)
    tile = tiles.most_common(1)[0][0]
    pre_sc = [s for s in pre_all if s.props.get("tile") == tile]
    post_sc = [s for s in post_all if s.props.get("tile") == tile]
    if not pre_sc or not post_sc:
        return {"status": "insufficient", "signal": signal, "expected_sign": expected_sign,
                "reason": f"MGRS tile {tile} has no scenes in both periods."}
    scene_epsg = next((s.epsg for s in pre_sc + post_sc if s.epsg), None) or area.epsg
    pre_sc = [s for s in pre_sc if (s.epsg or scene_epsg) == scene_epsg]
    post_sc = [s for s in post_sc if (s.epsg or scene_epsg) == scene_epsg]
    zones = Zones.build([square, area.utm], area.epsg, scene_epsg)

    # 2. composites -------------------------------------------------------------
    pre = _period_composite(prov, pre_sc, zones, signal, n_scenes)
    if pre is None:
        return {"status": "insufficient", "signal": signal, "expected_sign": expected_sign,
                "reason": "No pre-period scene could be read."}
    pre_med, pre_cnt, tr, pre_dates, pre_skip = pre
    post = _period_composite(prov, post_sc, zones, signal, n_scenes, ref_shape=pre_med.shape)
    if post is None:
        return {"status": "insufficient", "signal": signal, "expected_sign": expected_sign,
                "reason": "No post-period scene could be read on the pre-period grid."}
    post_med, post_cnt, _, post_dates, post_skip = post
    for tag, sk in (("pre", pre_skip), ("post", post_skip)):
        if sk:
            notes.append(f"{tag}: skipped {len(sk)} scene(s): " +
                         "; ".join(f"{i} ({why})" for i, why in sk))
    shape = pre_med.shape
    labels = labels_for(zones, tr, shape)
    area_mask = labels == 2
    n_area_total = int(area_mask.sum())
    if n_area_total == 0:
        return {"status": "insufficient", "signal": signal, "expected_sign": expected_sign,
                "reason": "The area rasterises to no pixels on the scene grid."}
    enough = (pre_cnt >= MIN_CLEAR) & (post_cnt >= MIN_CLEAR)
    for tag, cnt in (("pre", pre_cnt), ("post", post_cnt)):
        short = float((cnt[area_mask] < MIN_CLEAR).mean())
        if short > 0.5:
            return {"status": "insufficient", "signal": signal, "expected_sign": expected_sign,
                    "reason": f"{short:.0%} of the area's pixels have fewer than {MIN_CLEAR} clear "
                              f"observations in the {tag} period "
                              f"({len(pre_dates) if tag == 'pre' else len(post_dates)} scenes read).",
                    "pre": {"n_scenes": len(pre_dates), "dates": pre_dates},
                    "post": {"n_scenes": len(post_dates), "dates": post_dates}}

    # 3. control pixels ---------------------------------------------------------
    wc_year = 2020 if ev.year < 2022 else 2021
    zones_geo = Zones.build([square, area.utm], area.epsg, 4326)
    wc = _worldcover_on_grid(area, zones_geo, wc_year, tr, shape, scene_epsg)
    wc_area = wc[area_mask & (wc > 0)]
    if wc_area.size == 0:
        return {"status": "insufficient", "signal": signal, "expected_sign": expected_sign,
                "reason": "WorldCover could not be read for the area."}
    vals, counts = np.unique(wc_area, return_counts=True)
    lc_class = int(vals[np.argmax(counts)])
    lc_frac = float(counts.max() / wc_area.size)
    buffer_poly = reproject(area.utm.buffer(BUFFER_M), area.epsg, scene_epsg)
    ring = _rasterize(buffer_poly, tr, shape)
    delta = (post_med - pre_med).astype("float32")
    has_data = enough & np.isfinite(delta)
    control = (labels >= 1) & ~ring & (wc == lc_class) & has_data
    n_control = int(control.sum())
    if n_control < MIN_CONTROL_PIXELS:
        return {"status": "insufficient", "signal": signal, "expected_sign": expected_sign,
                "reason": f"Only {n_control} control pixels of class {lc_class} "
                          f"({WC_CLASSES.get(lc_class, 'unknown')}) with enough clear observations.",
                "landcover_class": lc_class, "landcover": WC_CLASSES.get(lc_class, "unknown")}

    # 4. threshold and fraction -------------------------------------------------
    thr = change_threshold(delta[control], expected_sign)
    changed = changed_mask(delta, thr, expected_sign) & has_data
    area_data = area_mask & has_data
    n_area = int(area_data.sum())
    frac = float(changed[area_data].mean()) if n_area else float("nan")

    # 5. placebo over control cells --------------------------------------------
    cell_px = max(int(round(max(side, 100.0) / 10.0)), 1)
    cells = cell_labels(shape, cell_px)
    cf = cell_fractions(changed, control, cells)
    p = placebo_p(cf, frac)
    if cf.size == 0:
        notes.append("No control cell had enough control pixels; placebo_p is null.")
    elif cf.size < 10:
        notes.append(f"Only {cf.size} placebo cells; placebo_p is coarse.")
    if lc_frac < 0.6:
        notes.append(f"The area is mixed land cover: {lc_frac:.0%} in the dominant class "
                     f"({WC_CLASSES.get(lc_class, 'unknown')}); controls match that class only.")

    # 6. map --------------------------------------------------------------------
    os.makedirs(out_dir, exist_ok=True)
    map_name = f"{run_id}_change.png"
    try:
        render_change_map(pre_med, delta, changed, area_mask, os.path.join(out_dir, map_name))
    except Exception as e:                           # the numbers stand without the picture
        map_name = None
        notes.append(f"Change map could not be rendered: {type(e).__name__}: {e}")

    # 6b. overlay aligned with the before/after thumbnails ----------------------
    overlay_name = f"{run_id}_changeoverlay.png"
    try:
        from .imagery import _square_bounds
        thumb_sq = reproject(_square_bounds(area), area.epsg, scene_epsg)
        eligible = area_mask | ((labels >= 1) & (wc == lc_class))
        if render_change_overlay(delta, changed & has_data, eligible, tr, thumb_sq.bounds,
                                 os.path.join(out_dir, overlay_name)) is None:
            overlay_name = None
            notes.append("The thumbnail window lies outside the change grid; no overlay.")
    except Exception as e:                           # the numbers stand without the picture
        overlay_name = None
        notes.append(f"Change overlay could not be rendered: {type(e).__name__}: {e}")

    # 7. result -----------------------------------------------------------------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        med_area = float(np.nanmedian(delta[area_data])) if n_area else float("nan")
        med_ctrl = float(np.nanmedian(delta[control]))
    result = {
        "status": "ok", "signal": signal, "expected_sign": int(expected_sign),
        "fraction_changed": _r(frac), "expected_null_fraction": EXPECTED_NULL_FRACTION,
        "placebo_p": _r(p), "n_placebo_cells": int(cf.size),
        "median_cell_fraction": _r(np.median(cf)) if cf.size else None,
        "p95_cell_fraction": _r(np.percentile(cf, 95)) if cf.size else None,
        "n_area_pixels": n_area, "n_area_pixels_total": n_area_total,
        "n_control_pixels": n_control,
        "landcover_class": lc_class, "landcover": WC_CLASSES.get(lc_class, "unknown"),
        "landcover_fraction": _r(lc_frac, 2), "worldcover_year": wc_year,
        "tile": tile, "epsg": int(scene_epsg), "cell_px": cell_px,
        "pre": {"n_scenes": len(pre_dates), "dates": pre_dates},
        "post": {"n_scenes": len(post_dates), "dates": post_dates},
        "threshold": _r(thr), "median_delta_area": _r(med_area), "median_delta_controls": _r(med_ctrl),
        "map": map_name, "overlay": overlay_name, "notes": notes,
    }
    with open(os.path.join(out_dir, f"{run_id}_change.json"), "w") as f:
        json.dump(result, f, indent=1)
    return result
