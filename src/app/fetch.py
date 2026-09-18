"""Fetch and clean Sentinel-1 + Sentinel-2 for one drawn area and its donor grid."""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Callable

import numpy as np
from shapely.geometry import mapping

from . import s1 as s1mod
from . import s2 as s2mod
from .extract import Zones
from .geometry import Area, DonorGrid, bbox_wgs84, donor_grid, reproject, validate_polygon, wide_candidates
from .providers import EarthSearch, PlanetaryComputer, Scene
from .series import AreaData, SensorSeries, cache_key

CACHE_DIR = os.environ.get("APP_CACHE_DIR", "data/cache")
WORKERS = int(os.environ.get("APP_FETCH_WORKERS", "16"))
USER_RECEIPTS = ("cloud", "haze", "duplicate", "orbit", "edge", "read-error")   # shown on the verdict page
Progress = Callable[[str, int, int], None]


def _noop(stage: str, done: int, total: int) -> None:
    pass


def _group_by_crs(scenes: list[Scene], sign) -> dict[int, list[Scene]]:
    """Scenes are read in their own CRS; group so Zones are built once per CRS."""
    import rasterio
    from .extract import GDAL_ENV
    out: dict[int, list[Scene]] = {}
    for sc in scenes:
        epsg = sc.epsg
        if epsg is None and sc.sensor == "S2" and sc.props.get("tile"):
            tile = sc.props["tile"]
            epsg = (32600 if tile[2] >= "N" else 32700) + int(tile[:2])
        if epsg is None:
            href = sign(next(iter(sc.hrefs.values())))
            with rasterio.Env(**GDAL_ENV), rasterio.open(href) as ds:
                epsg = ds.crs.to_epsg()
        out.setdefault(epsg, []).append(sc)
    return out


def _covering(scenes: list[Scene], area_wgs84) -> list[Scene]:
    """Only scenes whose footprint actually covers the drawn area are read."""
    return [s for s in scenes if s.geometry is None or s.geometry.intersects(area_wgs84)]


def _latest_processing(scenes: list[Scene]) -> list[Scene]:
    """Planetary Computer can hold several processing versions of one
    acquisition and tile. Keep the newest baseline per (minute, tile)."""
    best: dict[tuple, Scene] = {}
    for s in scenes:
        k = (s.minute_key, s.props.get("tile"))
        if k not in best or str(s.props.get("baseline")) > str(best[k].props.get("baseline")):
            best[k] = s
    return list(best.values())


def _run(scenes_by_crs, polygons_utm, src_epsg, sign, process, progress, stage,
         res=None, require_zone0=True):
    obs, receipts = [], []
    total = sum(len(v) for v in scenes_by_crs.values())
    done = 0
    progress(stage, 0, total)
    kw = {"require_zone0": require_zone0}
    if res is not None:
        kw["res"] = res
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for epsg, scenes in scenes_by_crs.items():
            zones = Zones.build(polygons_utm, src_epsg, epsg)
            for sc in scenes:
                futs[ex.submit(process, sc, zones, sign, **kw)] = sc
        for f in as_completed(futs):
            sc = futs[f]
            try:
                o, r = f.result()
            except Exception as e:     # a single bad scene must not kill the run
                o, r = None, s2mod.Receipt(sc.sensor, sc.date, sc.id, "read-error", f"Read failed: {e}")
            if o is not None:
                obs.append(o)
            if r is not None:
                receipts.append(r)
            done += 1
            progress(stage, done, total)
    return obs, receipts


def _to_series(obs, sensor: str, keys: tuple[str, ...], meta: dict) -> SensorSeries | None:
    if not obs:
        return None
    obs = sorted(obs, key=lambda o: o.minute_key)
    dates = np.asarray([o.date for o in obs])
    values = {k: np.vstack([o.values[k] for o in obs]).astype("float32") for k in keys}
    values["clear_frac" if sensor == "S2" else "valid_frac"] = np.vstack(
        [o.clear_frac if sensor == "S2" else o.valid_frac for o in obs]).astype("float32")
    return SensorSeries(sensor, dates, values, [o.scene_id for o in obs], meta)


def _fetch_group(polys_utm, src_epsg, group_wgs84, start, end, prov, s1_prov, sensors, progress,
                 receipts, res, require_zone0, tag):
    """Search and read one group of polygons (the treated area, or a cluster of
    donor cells far away). Returns (s2_series, s1_series, counts)."""
    from shapely.geometry import box as _box
    bbox = [float(v) for v in group_wgs84.bounds]
    s2_found = prov.search_s2(bbox, start, end) if "S2" in sensors else []
    s1_found = s1_prov.search_s1(bbox, start, end) if "S1" in sensors else []
    s2_scenes = _latest_processing(_covering(s2_found, group_wgs84))
    s1_scenes, orbit_receipts, orbit = s1mod.select_orbit_scenes(s1_found, group_wgs84)
    if require_zone0:
        receipts += [asdict(r) for r in orbit_receipts]
    s2_series = s1_series = None
    if s2_scenes:
        groups = _group_by_crs(s2_scenes, prov.sign)
        obs, rec = _run(groups, polys_utm, src_epsg, prov.sign, s2mod.process_scene, progress,
                        f"sentinel-2{tag}", res=res, require_zone0=require_zone0)
        obs, rec2 = s2mod.dedupe_by_minute(obs)
        if require_zone0:
            receipts += [asdict(r) for r in rec + rec2]
        s2_series = _to_series(obs, "S2", s2mod.INDICES, {"provider": prov.name, "n_scenes": len(s2_scenes)})
    if s1_scenes:
        groups = _group_by_crs(s1_scenes, s1_prov.sign)
        obs, rec = _run(groups, polys_utm, src_epsg, s1_prov.sign, s1mod.process_scene, progress,
                        f"sentinel-1{tag}", res=res, require_zone0=require_zone0)
        obs, rec2 = s1mod.dedupe_by_minute(obs)
        if require_zone0:
            receipts += [asdict(r) for r in rec + rec2]
        s1_series = _to_series(obs, "S1", ("VV", "VH", "RATIO"),
                               {"provider": s1_prov.name, "n_scenes": len(s1_scenes), "orbit": orbit})
    counts = {"s2_found": len(s2_found), "s2_covering": len(s2_scenes),
              "s1_found": len(s1_found), "s1_covering": len(s1_scenes), "orbit": orbit}
    return s2_series, s1_series, counts


def _strip_treated(ss: SensorSeries | None) -> SensorSeries | None:
    """Donor-only groups have no treated column; drop the dummy zone 0 column."""
    if ss is None:
        return None
    return SensorSeries(ss.sensor, ss.dates, {k: v[:, 1:] for k, v in ss.values.items()}, ss.scene_ids, ss.meta)


def _despike_donors(ss: SensorSeries | None, col0: int) -> None:
    if ss is None or "NDVI" not in ss.values:
        return
    nd = ss.values["NDVI"]
    dts = ss.dates.astype("datetime64[D]")
    for j in range(col0, nd.shape[1]):
        sj = s2mod.despike(dts, nd[:, j])
        for k in ss.values:
            ss.values[k][sj, j] = np.nan


def _wide_groups(area: Area, cands: DonorGrid, cov, max_cells: int, n_groups: int, group_km: float):
    """Filter wide candidates by land cover and terrain, then bucket them into
    compact groups so each group is one read window."""
    n = len(cands.cells)
    lc = cov.landcover[1:]; frac = cov.landcover_frac[1:]; el = cov.elevation[1:]; sl = cov.slope[1:]
    lc_t, el_t, sl_t = int(cov.landcover[0]), float(cov.elevation[0]), float(cov.slope[0])
    ok = np.ones(n, dtype=bool)
    ok &= lc != 80                                     # never water
    ok &= lc != 0
    if lc_t:
        same = (lc == lc_t) & (frac >= 0.5)
        if same.sum() >= 40:
            ok &= same
    if np.isfinite(el_t):
        near = np.abs(np.nan_to_num(el, nan=el_t) - el_t) <= 200.0
        if (ok & near).sum() >= 40:
            ok &= near
    score = (np.abs(np.nan_to_num(el, nan=el_t) - el_t) / 200.0
             + np.abs(np.nan_to_num(sl, nan=sl_t) - sl_t) / 10.0 + (1.0 - frac))
    idx = np.where(ok)[0]
    idx = idx[np.argsort(score[idx])][:max_cells]
    # bucket by a coarse grid in the area's UTM
    B = group_km * 1000.0
    buckets: dict[tuple, list] = {}
    for i in idx:
        c = cands.cells[i].centroid
        buckets.setdefault((int(c.x // B), int(c.y // B)), []).append(int(i))
    ordered = sorted(buckets.values(), key=len, reverse=True)[:n_groups]
    return [sorted(b) for b in ordered if len(b) >= 3]


def fetch_area(area_geojson: dict, start: str, end: str, *,
               providers: str = "pc", inner_m: float = 1000.0, outer_m: float = 12000.0,
               max_cells: int = 400, use_cache: bool = True, cache_dir: str = CACHE_DIR,
               progress: Progress = _noop, sensors: tuple[str, ...] = ("S2", "S1"),
               mode: str = "ring", cov_year: int = 2021, n_groups: int = 6,
               group_km: float = 30.0, donor_res: float = 40.0) -> AreaData:
    """Return cleaned S2 and S1 series for the area and its donor cells.

    mode="ring": donors are same-size cells 1-12 km away, read in one window.
    mode="wide": donors are similarity-matched cells anywhere in a wide annulus
    (inner_m..outer_m, e.g. 20-150 km), filtered by land cover and terrain and
    read in compact groups at `donor_res` metres from the COG overviews.
    """
    if mode == "wide":
        return _fetch_wide(area_geojson, start, end, providers=providers, inner_m=inner_m, outer_m=outer_m,
                           max_cells=max_cells, use_cache=use_cache, cache_dir=cache_dir, progress=progress,
                           sensors=sensors, cov_year=cov_year, n_groups=n_groups, group_km=group_km,
                           donor_res=donor_res)
    t0 = time.time()
    area: Area = validate_polygon(area_geojson)
    grid: DonorGrid = donor_grid(area, inner_m=inner_m, outer_m=outer_m, max_cells=max_cells)
    grid_sig = f"{inner_m}-{outer_m}-{max_cells}-{''.join(sensors)}"
    key = cache_key(area.geojson, start, end, grid_sig)
    cdir = os.path.join(cache_dir, key)
    if use_cache and os.path.exists(os.path.join(cdir, "meta.json")):
        progress("cache", 1, 1)
        return AreaData.load(cdir)

    prov = PlanetaryComputer() if providers == "pc" else EarthSearch()
    s1_prov = prov if providers == "pc" else PlanetaryComputer()
    bbox = bbox_wgs84(area, grid)
    polygons = [area.utm] + grid.cells
    receipts: list[dict] = []
    timing = {}

    progress("search", 0, 1)
    t = time.time()
    s2_found = prov.search_s2(bbox, start, end) if "S2" in sensors else []
    s1_found = s1_prov.search_s1(bbox, start, end) if "S1" in sensors else []
    s2_scenes = _latest_processing(_covering(s2_found, area.wgs84))
    s1_scenes, orbit_receipts, orbit = s1mod.select_orbit_scenes(s1_found, area.wgs84)
    receipts += [asdict(r) for r in orbit_receipts]
    timing["search_s"] = round(time.time() - t, 1)
    progress("search", 1, 1)

    s2_series = s1_series = None
    if s2_scenes:
        t = time.time()
        groups = _group_by_crs(s2_scenes, prov.sign)
        obs, rec = _run(groups, polygons, area.epsg, prov.sign, s2mod.process_scene, progress, "sentinel-2")
        obs, rec2 = s2mod.dedupe_by_minute(obs)
        receipts += [asdict(r) for r in rec + rec2]
        s2_series = _to_series(obs, "S2", s2mod.INDICES, {"provider": prov.name, "n_scenes": len(s2_scenes)})
        if s2_series is not None:
            # residual cloud/haze on the treated series -> drop the observation
            sus = s2mod.despike(s2_series.dates.astype("datetime64[D]"), s2_series.treated("NDVI"))
            for i in np.where(sus)[0]:
                receipts.append(asdict(s2mod.Receipt("S2", str(s2_series.dates[i]), s2_series.scene_ids[i], "haze",
                    f"NDVI {s2_series.treated('NDVI')[i]:.2f} sits well below its neighbours in time; "
                    f"likely cloud or haze the scene classifier missed.")))
            keep = ~sus
            s2_series = SensorSeries("S2", s2_series.dates[keep], {k: v[keep] for k, v in s2_series.values.items()},
                                     [s for s, k in zip(s2_series.scene_ids, keep) if k], s2_series.meta)
            # and the same test on every donor cell, cell by cell (NaN out, no receipt)
            nd = s2_series.values["NDVI"]
            dts = s2_series.dates.astype("datetime64[D]")
            for j in range(1, nd.shape[1]):
                sj = s2mod.despike(dts, nd[:, j])
                for k in s2_series.values:
                    s2_series.values[k][sj, j] = np.nan
        timing["s2_s"] = round(time.time() - t, 1)
    if s1_scenes:
        t = time.time()
        groups = _group_by_crs(s1_scenes, s1_prov.sign)
        obs, rec = _run(groups, polygons, area.epsg, s1_prov.sign, s1mod.process_scene, progress, "sentinel-1")
        obs, rec2 = s1mod.dedupe_by_minute(obs)
        receipts += [asdict(r) for r in rec + rec2]
        s1_series = _to_series(obs, "S1", ("VV", "VH", "RATIO"),
                               {"provider": s1_prov.name, "n_scenes": len(s1_scenes), "orbit": orbit})
        timing["s1_s"] = round(time.time() - t, 1)

    internal = [r for r in receipts if r["reason"] not in USER_RECEIPTS]
    receipts = sorted([r for r in receipts if r["reason"] in USER_RECEIPTS], key=lambda r: r["date"])
    summary = {
        "s2_scenes_found": len(s2_found), "s2_scenes_covering": len(s2_scenes),
        "s2_observations": s2_series.n_obs if s2_series else 0,
        "s1_scenes_found": len(s1_found), "s1_scenes_covering": len(s1_scenes),
        "s1_observations": s1_series.n_obs if s1_series else 0,
        "s1_orbit": orbit, "internal_receipts": len(internal),
        "n_donor_cells": len(grid.cells), "cell_m": round(grid.cell_m),
        "receipts": {r: sum(1 for x in receipts if x["reason"] == r) for r in sorted({x["reason"] for x in receipts})},
    }
    timing["total_s"] = round(time.time() - t0, 1)
    data = AreaData(area_geojson=area.geojson, area_ha=round(area.area_ha, 2), epsg=area.epsg,
                    cells_geojson=[mapping(reproject(c, area.epsg, 4326)) for c in grid.cells],
                    cell_distance_m=[float(d) for d in grid.distances_m],
                    start=start, end=end, s2=s2_series, s1=s1_series,
                    receipts=receipts, summary=summary, timing=timing)
    if use_cache:
        data.save(cdir)
    return data


def _fetch_wide(area_geojson, start, end, *, providers, inner_m, outer_m, max_cells, use_cache, cache_dir,
                progress, sensors, cov_year, n_groups, group_km, donor_res) -> AreaData:
    from shapely.geometry import box as _box
    from .covariates import fetch_covariates
    t0 = time.time()
    area = validate_polygon(area_geojson)
    grid_sig = f"wide-{inner_m}-{outer_m}-{max_cells}-{n_groups}-{group_km}-{donor_res}-{cov_year}-{''.join(sensors)}"
    key = cache_key(area.geojson, start, end, grid_sig)
    cdir = os.path.join(cache_dir, key)
    if use_cache and os.path.exists(os.path.join(cdir, "meta.json")):
        progress("cache", 1, 1)
        return AreaData.load(cdir)
    prov = PlanetaryComputer() if providers == "pc" else EarthSearch()
    s1_prov = prov if providers == "pc" else PlanetaryComputer()
    receipts: list[dict] = []
    timing = {}

    # 1. treated area alone, full resolution
    t = time.time()
    progress("search", 0, 1)
    s2_t, s1_t, counts_t = _fetch_group([area.utm], area.epsg, area.wgs84, start, end, prov, s1_prov,
                                        sensors, progress, receipts, None, True, "")
    if s2_t is not None:
        sus = s2mod.despike(s2_t.dates.astype("datetime64[D]"), s2_t.treated("NDVI"))
        for i in np.where(sus)[0]:
            receipts.append(asdict(s2mod.Receipt("S2", str(s2_t.dates[i]), s2_t.scene_ids[i], "haze",
                f"NDVI {s2_t.treated('NDVI')[i]:.2f} sits well below its neighbours in time; likely cloud or haze.")))
        keep = ~sus
        s2_t = SensorSeries("S2", s2_t.dates[keep], {k: v[keep] for k, v in s2_t.values.items()},
                            [x for x, k in zip(s2_t.scene_ids, keep) if k], s2_t.meta)
    timing["treated_s"] = round(time.time() - t, 1)

    # 2. candidates over the wide annulus, filtered by static covariates
    t = time.time()
    progress("covariates", 0, 1)
    cands = wide_candidates(area, inner_m, outer_m, n=max(3 * max_cells, 600))
    cov = fetch_covariates([area.utm] + cands.cells, area.epsg, cov_year, coarse=True)
    buckets = _wide_groups(area, cands, cov, max_cells, n_groups, group_km)
    timing["covariates_s"] = round(time.time() - t, 1)
    progress("covariates", 1, 1)

    # 3. each group read at donor resolution
    groups = []
    for gi, idxs in enumerate(buckets):
        t = time.time()
        cells = [cands.cells[i] for i in idxs]
        minx = min(c.bounds[0] for c in cells); miny = min(c.bounds[1] for c in cells)
        maxx = max(c.bounds[2] for c in cells); maxy = max(c.bounds[3] for c in cells)
        g_wgs = reproject(_box(minx, miny, maxx, maxy), area.epsg, 4326)
        s2_g, s1_g, counts_g = _fetch_group([area.utm] + cells, area.epsg, g_wgs, start, end, prov, s1_prov,
                                            sensors, progress, receipts, donor_res, False, f" group {gi + 1}/{len(buckets)}")
        s2_g, s1_g = _strip_treated(s2_g), _strip_treated(s1_g)
        _despike_donors(s2_g, 0)
        groups.append({"cells_geojson": [mapping(reproject(c, area.epsg, 4326)) for c in cells],
                       "distance_m": [float(cands.distances_m[i]) for i in idxs],
                       "landcover": [int(cov.landcover[i + 1]) for i in idxs],
                       "elevation": [float(cov.elevation[i + 1]) if np.isfinite(cov.elevation[i + 1]) else None for i in idxs],
                       "counts": counts_g, "s2": s2_g, "s1": s1_g, "seconds": round(time.time() - t, 1)})
    receipts = sorted([r for r in receipts if r["reason"] in USER_RECEIPTS], key=lambda r: r["date"])
    n_cells = sum(len(g["cells_geojson"]) for g in groups)
    summary = {"mode": "wide", "inner_m": inner_m, "outer_m": outer_m,
               "s2_scenes_found": counts_t["s2_found"], "s2_scenes_covering": counts_t["s2_covering"],
               "s2_observations": s2_t.n_obs if s2_t else 0,
               "s1_scenes_found": counts_t["s1_found"], "s1_scenes_covering": counts_t["s1_covering"],
               "s1_observations": s1_t.n_obs if s1_t else 0, "s1_orbit": counts_t["orbit"],
               "n_candidates": len(cands.cells), "n_donor_cells": n_cells, "n_groups": len(groups),
               "cell_m": round(cands.cell_m), "treated_landcover": int(cov.landcover[0]),
               "receipts": {r: sum(1 for x in receipts if x["reason"] == r) for r in sorted({x["reason"] for x in receipts})}}
    timing["total_s"] = round(time.time() - t0, 1)
    all_cells = [c for g in groups for c in g["cells_geojson"]]
    all_d = [d for g in groups for d in g["distance_m"]]
    data = AreaData(area_geojson=area.geojson, area_ha=round(area.area_ha, 2), epsg=area.epsg,
                    cells_geojson=all_cells, cell_distance_m=all_d, start=start, end=end,
                    s2=s2_t, s1=s1_t, receipts=receipts, summary=summary, timing=timing,
                    mode="wide", groups=groups)
    if use_cache:
        data.save(cdir)
    return data
