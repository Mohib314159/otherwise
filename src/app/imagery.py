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
                    days: int = 120, after_min_days: int = 10, before_max_days: int = 365) -> dict:
    area = validate_polygon(area_geojson)
    ev = date.fromisoformat(event_date)
    prov = PlanetaryComputer()
    sq = _square_bounds(area)
    from .geometry import reproject
    bbox = [float(v) for v in reproject(sq, area.epsg, 4326).bounds]
    out = {}
    # A winter or monsoon "before" window can hold no scene that clears the bar;
    # rather than show a cloudy one, look further back (the page shows the date).
    tries = (("before", ev - timedelta(days=days), ev - timedelta(days=1), False),
             ("before", ev - timedelta(days=before_max_days), ev - timedelta(days=1), False),
             ("after", ev + timedelta(days=after_min_days), ev + timedelta(days=days + after_min_days), True))
    for tag, start, end, after in tries:
        if tag in out:
            continue
        scenes = prov.search_s2(bbox, start.isoformat(), end.isoformat(), max_cloud=60)
        scenes = [s for s in scenes if s.geometry is None or s.geometry.contains(area.wgs84)]
        if not scenes:
            continue
        epsg = scenes[0].epsg or area.epsg
        scenes = [s for s in scenes if (s.epsg or epsg) == epsg]
        zones = Zones.build([sq, area.utm], area.epsg, epsg)
        sc, cf = _best_scene(prov, scenes, zones, None, after)
        basis = "scl"
        # burnt or flooded ground is often classed "dark", not cloud: accept a lower clear share after the event
        if (sc is None or cf < (0.6 if after else 0.9)) and not after and (end - start).days > days:
            # Last resort, only on the widened "before" search: the scene
            # classification flags bright bare ground (limestone, fresh fill) as
            # cloud or "unclassified", so a cloud-free scene can score below 0.9
            # (Hasankeyf). Take the nearest scene that is <=5 % cloudy as a whole
            # and >=0.65 clear over the area, and record why it was accepted.
            for cand in sorted([x for x in scenes if (x.props.get("cloud_cover") or 100) <= 5],
                               key=lambda x: x.datetime, reverse=True)[:10]:
                c2 = _clear_share(prov, cand, zones)
                if c2 is not None and c2 >= 0.65:
                    sc, cf, basis = cand, c2, "scene_cloud_cover<=5%"
                    break
        if sc is None or (basis == "scl" and cf < (0.6 if after else 0.9)):
            continue
        path = os.path.join(out_dir, f"{run_id}_{tag}.png")
        os.makedirs(out_dir, exist_ok=True)
        if _rgb_png(prov, sc, zones, path, area):
            out[tag] = {"date": sc.date, "scene_id": sc.id, "clear": round(cf, 2), "file": path,
                        "clear_basis": basis, "scene_cloud_cover": sc.props.get("cloud_cover")}
    return out


def make_timelapse(area_geojson: dict, start: str, end: str, out_dir: str, run_id: str,
                   n_frames: int = 8, min_clear: float = 0.85, event_date: str | None = None) -> list[dict]:
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
    # Equal slots can all land on one side of a short post-event window (Sindh:
    # 3 months after, 3 years before). The event must be markable, so add the
    # clearest frame on a missing side, if any scene there clears the bar.
    if event_date:
        ev = _date.fromisoformat(event_date)
        sides = (("pre", d0, ev - _td(days=1), lambda f: f["date"] < event_date),
                 ("post", ev + _td(days=1), d1, lambda f: f["date"] > event_date))
        for name, a, b, on_side in sides:
            if any(on_side(f) for f in frames) or b <= a:
                continue
            scenes = prov.search_s2(bbox, a.isoformat(), b.isoformat(), max_cloud=40)
            scenes = [s for s in scenes if s.geometry is None or s.geometry.contains(area.wgs84)]
            if not scenes:
                continue
            epsg = scenes[0].epsg or area.epsg
            scenes = sorted([s for s in scenes if (s.epsg or epsg) == epsg], key=lambda s: s.props.get("cloud_cover") or 0)
            zones = Zones.build([sq, area.utm], area.epsg, epsg)
            sc, cf = _best_scene(prov, scenes, zones, None, name == "post")
            if sc is None or cf < min_clear:
                continue
            i = n_frames + (0 if name == "pre" else 1)
            path = os.path.join(out_dir, f"{run_id}_t{i}.png")
            if _rgb_png(prov, sc, zones, path, area):
                frames.append({"index": i, "date": sc.date, "scene_id": sc.id, "clear": round(cf, 2),
                               "url": f"/api/runs/{run_id}/t{i}.png"})
        frames.sort(key=lambda f: f["date"])
    with open(os.path.join(out_dir, f"{run_id}_frames.json"), "w") as f:
        json.dump(frames, f)
    return frames


def _clear_share(prov, sc, zones) -> float | None:
    """Clear-sky share (SCL) over the inner polygon of a two-zone window."""
    try:
        r = read_window(prov.sign(sc.hrefs["SCL"]), zones, out_res=10.0)
    except Exception:
        return None
    if r is None:
        return None
    scl, tr, _ = r
    inside = labels_for(zones, tr, scl.shape) == 2
    if not inside.any():
        return None
    return float(np.isin(scl[inside], SCL_CLEAR).mean())


def make_control_thumbnails(run: dict, out_dir: str, k: int = 3, max_try: int = 16,
                            same_day_window: int = 5) -> list[dict]:
    """Before/after thumbnails of the `k` highest-weighted control cells, for the
    verdict page's "compared with" panel. Purely visual; the verdict never uses them.

    Fairness rule: each control is shown on the SAME Sentinel-2 scene as the
    area's own before/after thumbnail whenever that scene covers it, so the two
    are compared on identical dates. Distant (wide-mode) controls can fall on
    another tile; then the clearest scene within +-`same_day_window` days is used
    and its real date is recorded and shown. A control whose scene is not clear
    enough (0.9 before, 0.6 after, the same bar as the area's own thumbnails) is
    skipped and the next-highest weight is tried, and that is recorded too."""
    from datetime import date as _date, timedelta as _td
    from shapely.geometry import shape
    rid = run["id"]
    meta = {}
    for tag in ("before", "after"):
        p = os.path.join(out_dir, f"{rid}_{tag}.json")
        if os.path.exists(p):
            meta[tag] = json.load(open(p))
    if set(meta) != {"before", "after"}:
        import glob as _glob
        for f in _glob.glob(os.path.join(out_dir, f"{rid}_ctl*_*.png")):
            os.remove(f)
        with open(os.path.join(out_dir, f"{rid}_controls.json"), "w") as f:
            json.dump({"controls": [], "skipped": [], "reason": "the area has no before/after pair"}, f)
        return []
    lead = run["verdict"].get("lead_signal")
    donors = run.get("donors") or {}
    sel = donors.get(lead) or {}
    cells = donors.get("cells") or []
    # Controls that carry weight in the no-event prediction come first, largest
    # first. Convex weights are often sparse (one cell can take 100%), so any
    # remaining slots go to the best pre-event matches in the same selected pool,
    # labelled as such -- never presented as if they drove the counterfactual.
    trip = list(zip(sel.get("grid_index", []), sel.get("weights", []),
                    sel.get("pre_rmse", [None] * len(sel.get("grid_index", [])))))
    weighted = sorted([t for t in trip if t[1] > 0], key=lambda t: -t[1])
    pool = sorted([t for t in trip if t[1] <= 0 and t[2] is not None], key=lambda t: t[2])
    order = [(g, w, "weighted") for g, w, _ in weighted] + [(g, w, "pool") for g, w, _ in pool]
    prov = PlanetaryComputer()
    out, skipped = [], []
    for gi, w, role in order[:max_try]:
        if len(out) >= k:
            break
        if gi is None or gi >= len(cells):
            continue
        cell = validate_polygon(cells[gi])        # cells share the area's shape and size
        sq = _square_bounds(cell)
        from .geometry import reproject
        bbox = [float(v) for v in reproject(sq, cell.epsg, 4326).bounds]
        dist, lc = donors.get("distance_m") or [], donors.get("landcover") or []
        entry = {"rank": len(out) + 1, "grid_index": int(gi), "weight": round(float(w), 4), "role": role,
                 "distance_m": dist[gi] if gi < len(dist) else None,
                 "landcover": lc[gi] if gi < len(lc) else None}
        ok = True
        for tag, min_clear in (("before", 0.9), ("after", 0.6)):
            want = meta[tag]
            d0 = _date.fromisoformat(want["date"])
            scenes = prov.search_s2(bbox, (d0 - _td(days=same_day_window)).isoformat(),
                                    (d0 + _td(days=same_day_window)).isoformat(), max_cloud=80)
            scenes = [s for s in scenes if s.geometry is None or s.geometry.contains(cell.wgs84)]
            if not scenes:
                ok = False; break
            epsg = scenes[0].epsg or cell.epsg
            scenes = [s for s in scenes if (s.epsg or epsg) == epsg]
            same = [s for s in scenes if s.id == want.get("scene_id")]
            same_day = [s for s in scenes if s.date == want["date"]]
            zones = Zones.build([sq, cell.utm], cell.epsg, epsg)
            ranked = same + same_day + sorted(scenes, key=lambda s: abs((_date.fromisoformat(s.date) - d0).days))
            chosen = None
            for sc in ranked[:6]:
                cf = _clear_share(prov, sc, zones)
                if cf is not None and cf >= min_clear:
                    chosen = (sc, cf); break
            if chosen is None:
                ok = False; break
            sc, cf = chosen
            path = os.path.join(out_dir, f"{rid}_ctl{entry['rank']}_{tag}.png")
            if not _rgb_png(prov, sc, zones, path, cell):
                ok = False; break
            entry[tag] = {"date": sc.date, "scene_id": sc.id, "clear": round(cf, 2),
                          "same_scene_as_area": sc.id == want.get("scene_id"),
                          "url": f"/api/runs/{rid}/ctl{entry['rank']}_{tag}.png"}
        if ok:
            out.append(entry)
        else:
            skipped.append({"grid_index": int(gi), "weight": round(float(w), 4),
                            "reason": "no clear scene on the area's before/after dates"})
    with open(os.path.join(out_dir, f"{rid}_controls.json"), "w") as f:
        json.dump({"controls": out, "skipped": skipped, "lead_signal": lead}, f)
    return out

