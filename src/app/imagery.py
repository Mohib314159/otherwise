"""Before/after true-colour thumbnails of the area from the clearest Sentinel-2
scenes near the event date. Purely for the human eye; the verdict never uses them."""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

import numpy as np
from shapely.geometry import box

from .extract import Zones, labels_for, read_window
from .geometry import validate_polygon
from .providers import PlanetaryComputer
from .s2 import SCL_CLEAR, reflectance

THUMB_PX = 480


def _square_bounds(area, factor: float = 3.0):
    minx, miny, maxx, maxy = area.utm.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half = max(maxx - minx, maxy - miny) * factor / 2
    half = max(half, 300.0)
    return box(cx - half, cy - half, cx + half, cy + half)


def _best_scene(prov, scenes, zones, area_poly_zone, want_after: bool):
    """Return (scene, clear_fraction) for the clearest scene over the area."""
    best, best_cf = None, 0.0
    # nearest first, but only among scenes that are not obviously cloudy; then widen
    near = sorted(scenes, key=lambda s: s.datetime, reverse=not want_after)
    order = [s for s in near if (s.props.get("cloud_cover") or 0) <= 20] + [s for s in near if (s.props.get("cloud_cover") or 0) > 20]
    for sc in order[:20]:
        try:
            r = read_window(prov.sign(sc.hrefs["SCL"]), zones, out_res=10.0)
        except Exception:
            continue
        if r is None:
            continue
        scl, tr, _ = r
        lab = labels_for(zones, tr, scl.shape)
        inside = lab == 2          # zones are [square, area]; the area is painted last
        if not inside.any():
            continue
        cf = float(np.isin(scl[inside], SCL_CLEAR).mean())
        if cf > best_cf:
            best, best_cf = sc, cf
        if cf >= 0.98:
            break
    return best, best_cf


def _rgb_png(prov, sc, zones, path: str, area_poly):
    from PIL import Image, ImageDraw
    bands = []
    for b in ("B04", "B03", "B02"):
        r = read_window(prov.sign(sc.hrefs[b]), zones, out_res=10.0)
        if r is None:
            return False
        bands.append(reflectance(r[0], sc.props.get("baseline", "00.00")))
    tr = r[1]
    rgb = np.dstack(bands)
    # fixed stretch so before/after are comparable, mild gamma for dark scenes
    rgb = np.clip(rgb / 0.30, 0, 1) ** 0.8
    img = Image.fromarray((rgb * 255).astype("uint8"))
    lab = labels_for(zones, tr, rgb.shape[:2])
    # outline of the area: pixels inside whose 4-neighbour is outside
    inside = lab == 2
    edge = inside & ~(np.roll(inside, 1, 0) & np.roll(inside, -1, 0) & np.roll(inside, 1, 1) & np.roll(inside, -1, 1))
    arr = np.array(img)
    arr[edge] = [255, 255, 255]
    img = Image.fromarray(arr)
    img = img.resize((THUMB_PX, THUMB_PX), Image.BILINEAR)
    img.save(path, optimize=True)
    return True


def make_thumbnails(area_geojson: dict, event_date: str, out_dir: str, run_id: str,
                    days: int = 120, after_min_days: int = 10) -> dict:
    area = validate_polygon(area_geojson)
    ev = date.fromisoformat(event_date)
    prov = PlanetaryComputer()
    sq = _square_bounds(area)
    from .geometry import reproject
    bbox = [float(v) for v in reproject(sq, area.epsg, 4326).bounds]
    out = {}
    for tag, start, end, after in (("before", ev - timedelta(days=days), ev - timedelta(days=1), False),
                                   ("after", ev + timedelta(days=after_min_days), ev + timedelta(days=days + after_min_days), True)):
        scenes = prov.search_s2(bbox, start.isoformat(), end.isoformat(), max_cloud=60)
        scenes = [s for s in scenes if s.geometry is None or s.geometry.contains(area.wgs84)]
        if not scenes:
            continue
        epsg = scenes[0].epsg or area.epsg
        scenes = [s for s in scenes if (s.epsg or epsg) == epsg]
        zones = Zones.build([sq, area.utm], area.epsg, epsg)
        sc, cf = _best_scene(prov, scenes, zones, None, after)
        if sc is None or cf < 0.9:
            continue
        path = os.path.join(out_dir, f"{run_id}_{tag}.png")
        os.makedirs(out_dir, exist_ok=True)
        if _rgb_png(prov, sc, zones, path, area):
            out[tag] = {"date": sc.date, "scene_id": sc.id, "clear": round(cf, 2), "file": path}
    return out


def make_timelapse(area_geojson: dict, start: str, end: str, out_dir: str, run_id: str,
                   n_frames: int = 8, min_clear: float = 0.85) -> list[dict]:
    """Up to `n_frames` clear true-colour frames spread evenly across [start, end],
    for a time-lapse scrubber. Each frame is the clearest scene in its slot."""
    from datetime import date as _date, timedelta as _td
    area = validate_polygon(area_geojson)
    prov = PlanetaryComputer()
    sq = _square_bounds(area)
    from .geometry import reproject
    bbox = [float(v) for v in reproject(sq, area.epsg, 4326).bounds]
    d0, d1 = _date.fromisoformat(start), _date.fromisoformat(end)
    span = (d1 - d0).days
    frames = []
    for i in range(n_frames):
        a = d0 + _td(days=int(span * i / n_frames))
        b = d0 + _td(days=int(span * (i + 1) / n_frames) - 1)
        scenes = prov.search_s2(bbox, a.isoformat(), b.isoformat(), max_cloud=40)
        scenes = [s for s in scenes if s.geometry is None or s.geometry.contains(area.wgs84)]
        if not scenes:
            continue
        epsg = scenes[0].epsg or area.epsg
        scenes = sorted([s for s in scenes if (s.epsg or epsg) == epsg], key=lambda s: s.props.get("cloud_cover") or 0)
        zones = Zones.build([sq, area.utm], area.epsg, epsg)
        sc, cf = _best_scene(prov, scenes, zones, None, True)
        if sc is None or cf < min_clear:
            continue
        path = os.path.join(out_dir, f"{run_id}_t{i}.png")
        os.makedirs(out_dir, exist_ok=True)
        if _rgb_png(prov, sc, zones, path, area):
            frames.append({"index": i, "date": sc.date, "scene_id": sc.id, "clear": round(cf, 2),
                           "url": f"/api/runs/{run_id}/t{i}.png"})
    with open(os.path.join(out_dir, f"{run_id}_frames.json"), "w") as f:
        json.dump(frames, f)
    return frames
