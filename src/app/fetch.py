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
from .geometry import Area, DonorGrid, bbox_wgs84, donor_grid, reproject, validate_polygon
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


def _run(scenes_by_crs, polygons_utm, src_epsg, sign, process, progress, stage):
    obs, receipts = [], []
    total = sum(len(v) for v in scenes_by_crs.values())
    done = 0
    progress(stage, 0, total)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for epsg, scenes in scenes_by_crs.items():
            zones = Zones.build(polygons_utm, src_epsg, epsg)
            for sc in scenes:
                futs[ex.submit(process, sc, zones, sign)] = sc
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


def fetch_area(area_geojson: dict, start: str, end: str, *,
               providers: str = "pc", inner_m: float = 1000.0, outer_m: float = 12000.0,
               max_cells: int = 400, use_cache: bool = True, cache_dir: str = CACHE_DIR,
               progress: Progress = _noop, sensors: tuple[str, ...] = ("S2", "S1")) -> AreaData:
    """Return cleaned S2 and S1 series for the area and its donor cells."""
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
