"""Before/after true-colour thumbnails of the area from the clearest Sentinel-2
scenes near the event date. Purely for the human eye; the verdict never uses them."""
from __future__ import annotations

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
    order = sorted(scenes, key=lambda s: s.datetime, reverse=not want_after)
    for sc in order[:12]:
        try:
            r = read_window(prov.sign(sc.hrefs["SCL"]), zones, out_res=10.0)
        except Exception:
            continue
        if r is None:
            continue
        scl, tr, _ = r
        lab = labels_for(zones, tr, scl.shape)
        inside = lab == 1
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
    inside = lab == 1
    edge = inside & ~(np.roll(inside, 1, 0) & np.roll(inside, -1, 0) & np.roll(inside, 1, 1) & np.roll(inside, -1, 1))
    arr = np.array(img)
    arr[edge] = [255, 255, 255]
    img = Image.fromarray(arr)
    img = img.resize((THUMB_PX, THUMB_PX), Image.BILINEAR)
    img.save(path, optimize=True)
    return True


def make_thumbnails(area_geojson: dict, event_date: str, out_dir: str, run_id: str,
                    days: int = 120) -> dict:
    area = validate_polygon(area_geojson)
    ev = date.fromisoformat(event_date)
    prov = PlanetaryComputer()
    sq = _square_bounds(area)
    from .geometry import reproject
    bbox = [float(v) for v in reproject(sq, area.epsg, 4326).bounds]
    out = {}
    for tag, start, end, after in (("before", ev - timedelta(days=days), ev - timedelta(days=1), False),
                                   ("after", ev + timedelta(days=1), ev + timedelta(days=days), True)):
        scenes = prov.search_s2(bbox, start.isoformat(), end.isoformat(), max_cloud=60)
        scenes = [s for s in scenes if s.geometry is None or s.geometry.contains(area.wgs84)]
        if not scenes:
            continue
        epsg = scenes[0].epsg or area.epsg
        scenes = [s for s in scenes if (s.epsg or epsg) == epsg]
        zones = Zones.build([area.utm, sq], area.epsg, epsg)
        sc, cf = _best_scene(prov, scenes, zones, None, after)
        if sc is None or cf < 0.5:
            continue
        path = os.path.join(out_dir, f"{run_id}_{tag}.png")
        os.makedirs(out_dir, exist_ok=True)
        if _rgb_png(prov, sc, zones, path, area):
            out[tag] = {"date": sc.date, "scene_id": sc.id, "clear": round(cf, 2), "file": path}
    return out
