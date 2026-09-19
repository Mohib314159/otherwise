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
LIVE_WORKERS = int(os.environ.get("APP_LIVE_FETCH_WORKERS", "2"))
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


class MemoryBudgetError(RuntimeError):
    """Raised before any read when a live run cannot fit the memory budget."""


# --- profiles ---------------------------------------------------------------
#
# "full" is the original path: the treated area and every donor cell are read
# from one window at 10 m. It is what the showcase and validation runs use and
# its numbers are unchanged.
#
# "live" is for user-drawn runs on the 512 MB free tier. It never reads a big
# window: the treated area is read alone at 10 m (a few hundred pixels), and the
# donor cells are read separately at DONOR_RES from the COG overviews. See
# DECISIONS.md for the measured allocation that forced this.
PROFILES = {
    "full": {"max_cloud": 95.0, "donor_res": None, "max_cells": 400, "per_bin": None,
             "one_tile_per_minute": False, "workers": WORKERS, "split_donors": False},
    "live": {"max_cloud": 60.0, "donor_res": 40.0, "max_cells": 120, "per_bin": 2,
             "one_tile_per_minute": True, "workers": LIVE_WORKERS, "split_donors": True},
}
LIVE_MAX_WINDOW_PX = float(os.environ.get("APP_LIVE_MAX_WINDOW_PX", 1_500_000))
LIVE_RES_LADDER = (40.0, 60.0, 80.0)


def _cloud(sc: Scene) -> float:
    c = sc.props.get("cloud_cover")
    return 100.0 if c is None else float(c)


def best_tile_per_minute(scenes: list[Scene], target) -> tuple[list[Scene], list]:
    """One scene per acquisition minute: the tile that covers `target` best.

    Adjacent MGRS tiles overlap by ~10 km, so a single acquisition can appear
    two to four times over one area. The old code read all of them and merged
    the results afterwards (`merge_duplicates`), i.e. it paid full read cost for
    copies it was about to average. For a window that already sits inside one
    tile, the extra copies add nothing, so they are dropped before any read.
    """
    best: dict[str, tuple[float, Scene]] = {}
    dropped = []
    for sc in scenes:
        if sc.geometry is None:
            cover = 0.0
        else:
            try:
                cover = sc.geometry.intersection(target).area / max(target.area, 1e-12)
            except Exception:
                cover = 0.0
        prev = best.get(sc.minute_key)
        if prev is None or cover > prev[0]:
            if prev is not None:
                dropped.append(prev[1])
            best[sc.minute_key] = (cover, sc)
        else:
            dropped.append(sc)
    return [v[1] for v in best.values()], dropped


def cap_per_bin(scenes: list[Scene], anchor: str, bin_days: int, per_bin: int) -> tuple[list[Scene], list]:
    """Keep at most `per_bin` scenes per analysis bin, least cloudy first.

    The estimator bins observations to `bin_days` and takes the median within a
    bin, so a fifth cloudy scene in the same bin costs a full read and changes
    almost nothing. Bins are anchored on the same date the estimator uses.
    """
    if not per_bin:
        return scenes, []
    a = np.datetime64(anchor, "D")
    buckets: dict[int, list[Scene]] = {}
    for sc in scenes:
        k = int((np.datetime64(sc.date, "D") - a).astype(int) // bin_days)
        buckets.setdefault(k, []).append(sc)
    keep, dropped = [], []
    for k, group in buckets.items():
        group.sort(key=_cloud)
        keep.extend(group[:per_bin])
        dropped.extend(group[per_bin:])
    return sorted(keep, key=lambda s: s.minute_key), dropped


def window_px(polygons_utm, res: float, pad_m: float = 20.0) -> float:
    """Pixels in the read window that covers `polygons_utm` at `res` metres."""
    minx = min(p.bounds[0] for p in polygons_utm) - pad_m
    miny = min(p.bounds[1] for p in polygons_utm) - pad_m
    maxx = max(p.bounds[2] for p in polygons_utm) + pad_m
    maxy = max(p.bounds[3] for p in polygons_utm) + pad_m
    return ((maxx - minx) / res) * ((maxy - miny) / res)


def choose_donor_res(polygons_utm, budget_px: float = LIVE_MAX_WINDOW_PX) -> float:
    """Coarsest-but-sufficient donor read resolution, or raise if none fits."""
    for res in LIVE_RES_LADDER:
        if window_px(polygons_utm, res) <= budget_px:
            return res
    px = window_px(polygons_utm, LIVE_RES_LADDER[-1])
    raise MemoryBudgetError(
        f"This area needs a control window of {px / 1e6:.0f} million pixels even at "
        f"{LIVE_RES_LADDER[-1]:.0f} m, which will not fit in the memory this deployment has. "
        f"Draw a smaller area, or run it offline in full mode.")


def _run(scenes_by_crs, polygons_utm, src_epsg, sign, process, progress, stage,
         res=None, require_zone0=True, workers=None):
    obs, receipts = [], []
    total = sum(len(v) for v in scenes_by_crs.values())
    done = 0
    progress(stage, 0, total)
    kw = {"require_zone0": require_zone0}
    if res is not None:
        kw["res"] = res
    with ThreadPoolExecutor(max_workers=workers or WORKERS) as ex:
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
                 receipts, res, require_zone0, tag, cfg=None, bin_anchor=None, bin_days=10):
    """Search and read one group of polygons (the treated area, or a cluster of
    donor cells far away). Returns (s2_series, s1_series, counts).

    `cfg` is a PROFILES entry; under the "live" profile the scene list is cut
    down before any pixel is read (cloud cover at search time, one tile per
    acquisition, at most `per_bin` scenes per analysis bin)."""
    cfg = cfg or PROFILES["full"]
    bbox = [float(v) for v in group_wgs84.bounds]
    s2_found = prov.search_s2(bbox, start, end, max_cloud=cfg["max_cloud"]) if "S2" in sensors else []
    s1_found = s1_prov.search_s1(bbox, start, end) if "S1" in sensors else []
    s2_scenes = _latest_processing(_covering(s2_found, group_wgs84))
    n_after_cover = len(s2_scenes)
    if cfg["one_tile_per_minute"]:
        s2_scenes, _dropped = best_tile_per_minute(s2_scenes, group_wgs84)
    n_after_tile = len(s2_scenes)
    if cfg["per_bin"] and bin_anchor:
        s2_scenes, _dropped = cap_per_bin(s2_scenes, bin_anchor, bin_days, cfg["per_bin"])
    s1_scenes, orbit_receipts, orbit = s1mod.select_orbit_scenes(s1_found, group_wgs84)
    if cfg["per_bin"] and bin_anchor:
        s1_scenes, _dropped = cap_per_bin(s1_scenes, bin_anchor, bin_days, cfg["per_bin"])
    if require_zone0:
        receipts += [asdict(r) for r in orbit_receipts]
    s2_series = s1_series = None
    if s2_scenes:
        groups = _group_by_crs(s2_scenes, prov.sign)
        obs, rec = _run(groups, polys_utm, src_epsg, prov.sign, s2mod.process_scene, progress,
                        f"sentinel-2{tag}", res=res, require_zone0=require_zone0,
                        workers=cfg["workers"])
        obs, rec2 = s2mod.dedupe_by_minute(obs)
        if require_zone0:
            receipts += [asdict(r) for r in rec + rec2]
        s2_series = _to_series(obs, "S2", s2mod.INDICES, {"provider": prov.name, "n_scenes": len(s2_scenes)})
    if s1_scenes:
        groups = _group_by_crs(s1_scenes, s1_prov.sign)
        obs, rec = _run(groups, polys_utm, src_epsg, s1_prov.sign, s1mod.process_scene, progress,
                        f"sentinel-1{tag}", res=res, require_zone0=require_zone0,
                        workers=cfg["workers"])
        obs, rec2 = s1mod.dedupe_by_minute(obs)
        if require_zone0:
            receipts += [asdict(r) for r in rec + rec2]
        s1_series = _to_series(obs, "S1", ("VV", "VH", "RATIO"),
                               {"provider": s1_prov.name, "n_scenes": len(s1_scenes), "orbit": orbit})
    counts = {"s2_found": len(s2_found), "s2_covering": n_after_cover,
              "s2_after_tile_dedupe": n_after_tile, "s2_read": len(s2_scenes),
              "s1_found": len(s1_found), "s1_covering": len(s1_scenes), "orbit": orbit}
    return s2_series, s1_series, counts


def _strip_treated(ss: SensorSeries | None) -> SensorSeries | None:
    """Drop a leading treated column from a donor group series.

    Unused since donor groups stopped being read with the treated polygon in
    their window (that inflated the wide-mode read window 4-11x). Kept because
    a cached AreaData written by the old path still has the extra column.
    """
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
               max_cells: int | None = None, use_cache: bool = True, cache_dir: str = CACHE_DIR,
               progress: Progress = _noop, sensors: tuple[str, ...] = ("S2", "S1"),
               mode: str = "ring", cov_year: int = 2021, n_groups: int = 6,
               group_km: float = 30.0, donor_res: float = 40.0,
               profile: str = "full", event_date: str | None = None) -> AreaData:
    """Return cleaned S2 and S1 series for the area and its donor cells.

    mode="ring": donors are same-size cells 1-12 km away, read in one window.
    mode="wide": donors are similarity-matched cells anywhere in a wide annulus
    (inner_m..outer_m, e.g. 20-150 km), filtered by land cover and terrain and
    read in compact groups at `donor_res` metres from the COG overviews.

    profile="full" reads one window at 10 m (original behaviour; used offline).
    profile="live" splits the read: the treated area alone at 10 m, the donor
    cells separately at a coarser resolution, with the scene list pre-filtered.
    It exists so a user-drawn run fits a 512 MB container.
    """
    cfg = PROFILES[profile]
    if max_cells is None:
        max_cells = cfg["max_cells"]
    if profile == "live" and mode == "ring":
        return _fetch_live_ring(area_geojson, start, end, providers=providers, inner_m=inner_m,
                                outer_m=outer_m, max_cells=max_cells, use_cache=use_cache,
                                cache_dir=cache_dir, progress=progress, sensors=sensors,
                                cov_year=cov_year, event_date=event_date, cfg=cfg)
    if mode == "wide":
        return _fetch_wide(area_geojson, start, end, providers=providers, inner_m=inner_m, outer_m=outer_m,
                           max_cells=max_cells, use_cache=use_cache, cache_dir=cache_dir, progress=progress,
                           sensors=sensors, cov_year=cov_year, n_groups=n_groups, group_km=group_km,
                           donor_res=donor_res, cfg=cfg, event_date=event_date)
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
                progress, sensors, cov_year, n_groups, group_km, donor_res,
                cfg=None, event_date=None) -> AreaData:
    cfg = cfg or PROFILES["full"]
    from shapely.geometry import box as _box
    from .covariates import fetch_covariates
    t0 = time.time()
    area = validate_polygon(area_geojson)
    grid_sig = (f"wide-{inner_m}-{outer_m}-{max_cells}-{n_groups}-{group_km}-{donor_res}-{cov_year}-"
                f"{''.join(sensors)}-p{cfg['max_cloud']}-{cfg['per_bin']}-{int(cfg['one_tile_per_minute'])}")
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
                                        sensors, progress, receipts, None, True, "",
                                        cfg=cfg, bin_anchor=event_date)
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
        # Read the donor cells ONLY. Passing the treated polygon as well put it in
        # the same Zones bounding box, and in wide mode the cells sit 20-150 km
        # away, so the window stretched across that whole separation: measured on
        # Rhodes, 4.47 Mpx with the treated polygon against 0.41 Mpx without --
        # 4-11x per group. It was only there so column 0 could be stripped again
        # afterwards. This is what pushed a wide run to the 512 MiB ceiling.
        s2_g, s1_g, counts_g = _fetch_group(cells, area.epsg, g_wgs, start, end, prov, s1_prov,
                                            sensors, progress, receipts, donor_res, False,
                                            f" group {gi + 1}/{len(buckets)}",
                                            cfg=cfg, bin_anchor=event_date)
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


def _ring_groups(area: Area, grid: DonorGrid, group_km: float, max_per_group: int = 60):
    """Bucket ring cells into compact clusters, each read as one window.

    One window over the whole 12 km ring is 24 km wide; at 40 m that is well
    inside budget, so most rings come back as a single group. Large areas (whose
    cells are large, so the ring is wider) split into a few windows instead of
    one oversized one.
    """
    B = group_km * 1000.0
    buckets: dict[tuple, list[int]] = {}
    for i, c in enumerate(grid.cells):
        p = c.centroid
        buckets.setdefault((int(p.x // B), int(p.y // B)), []).append(i)
    out = []
    for idxs in buckets.values():
        for k in range(0, len(idxs), max_per_group):
            chunk = sorted(idxs[k:k + max_per_group])
            if len(chunk) >= 3:
                out.append(chunk)
    return sorted(out, key=len, reverse=True)


def _fetch_live_ring(area_geojson, start, end, *, providers, inner_m, outer_m, max_cells,
                     use_cache, cache_dir, progress, sensors, cov_year, event_date, cfg) -> AreaData:
    """Ring donors, read without ever opening a big window.

    Pass 1 reads the treated polygon alone at 10 m. Its window is the drawn area
    plus 20 m of padding -- for a 27 ha area that is about 3 000 pixels, against
    the 6 million pixels the single-window path reads for the same scene.
    Pass 2 reads the donor cells at `choose_donor_res`, from the COG overviews.
    The two passes have their own date axes and are joined on event-anchored
    bins by `prep.binned_groups`, exactly as wide mode already does.
    """
    from shapely.geometry import box as _box
    from .covariates import fetch_covariates
    t0 = time.time()
    area: Area = validate_polygon(area_geojson)
    grid: DonorGrid = donor_grid(area, inner_m=inner_m, outer_m=outer_m, max_cells=max_cells)
    if not grid.cells:
        raise MemoryBudgetError("No control cells fit around this area; try a smaller polygon.")
    # One window for the whole ring whenever it fits the budget: each extra group
    # costs its own STAC search and its own scene reads. Only split when it does
    # not fit even at the coarsest resolution on the ladder.
    all_idx = list(range(len(grid.cells)))
    try:
        donor_res = choose_donor_res([area.utm] + grid.cells)
        buckets = [all_idx]
    except MemoryBudgetError:
        buckets = _ring_groups(area, grid, group_km=max(outer_m / 1000.0, 8.0))
        if not buckets:
            raise
        donor_res = max(choose_donor_res([area.utm] + [grid.cells[i] for i in b]) for b in buckets)

    grid_sig = (f"live-{inner_m}-{outer_m}-{max_cells}-{donor_res}-{cov_year}-{''.join(sensors)}"
                f"-c{cfg['max_cloud']}-b{cfg['per_bin']}")
    key = cache_key(area.geojson, start, end, grid_sig)
    cdir = os.path.join(cache_dir, key)
    if use_cache and os.path.exists(os.path.join(cdir, "meta.json")):
        progress("cache", 1, 1)
        return AreaData.load(cdir)

    prov = PlanetaryComputer() if providers == "pc" else EarthSearch()
    s1_prov = prov if providers == "pc" else PlanetaryComputer()
    receipts: list[dict] = []
    timing = {}

    # pass 1: the treated area alone, at full resolution
    progress("search", 0, 1)
    t = time.time()
    s2_t, s1_t, counts_t = _fetch_group([area.utm], area.epsg, area.wgs84, start, end, prov, s1_prov,
                                        sensors, progress, receipts, None, True, "",
                                        cfg=cfg, bin_anchor=event_date)
    if s2_t is not None:
        sus = s2mod.despike(s2_t.dates.astype("datetime64[D]"), s2_t.treated("NDVI"))
        for i in np.where(sus)[0]:
            receipts.append(asdict(s2mod.Receipt("S2", str(s2_t.dates[i]), s2_t.scene_ids[i], "haze",
                f"NDVI {s2_t.treated('NDVI')[i]:.2f} sits well below its neighbours in time; "
                f"likely cloud or haze the scene classifier missed.")))
        keep = ~sus
        s2_t = SensorSeries("S2", s2_t.dates[keep], {k: v[keep] for k, v in s2_t.values.items()},
                            [x for x, k in zip(s2_t.scene_ids, keep) if k], s2_t.meta)
    timing["treated_s"] = round(time.time() - t, 1)

    # covariates for donor selection, from coarse reads
    progress("covariates", 0, 1)
    t = time.time()
    try:
        cov = fetch_covariates([area.utm] + grid.cells, area.epsg, cov_year, coarse=True)
    except Exception:
        cov = None
    timing["covariates_s"] = round(time.time() - t, 1)
    progress("covariates", 1, 1)

    # pass 2: donor cells, coarse, one window per bucket
    groups = []
    for gi, idxs in enumerate(buckets):
        t = time.time()
        cells = [grid.cells[i] for i in idxs]
        minx = min(c.bounds[0] for c in cells); miny = min(c.bounds[1] for c in cells)
        maxx = max(c.bounds[2] for c in cells); maxy = max(c.bounds[3] for c in cells)
        g_wgs = reproject(_box(minx, miny, maxx, maxy), area.epsg, 4326)
        tag = "" if len(buckets) == 1 else f" group {gi + 1}/{len(buckets)}"
        # Cells only, as in wide mode above. Here the ring surrounds the area so the
        # window barely changes, but keeping one convention means the donor series
        # has the same shape on both paths.
        s2_g, s1_g, counts_g = _fetch_group(cells, area.epsg, g_wgs, start, end, prov,
                                            s1_prov, sensors, progress, receipts, donor_res, False,
                                            " controls" + tag, cfg=cfg, bin_anchor=event_date)
        _despike_donors(s2_g, 0)
        groups.append({"cells_geojson": [mapping(reproject(c, area.epsg, 4326)) for c in cells],
                       "distance_m": [float(grid.distances_m[i]) for i in idxs],
                       "landcover": [int(cov.landcover[i + 1]) if cov else 0 for i in idxs],
                       "elevation": [float(cov.elevation[i + 1]) if cov and np.isfinite(cov.elevation[i + 1])
                                     else None for i in idxs],
                       "counts": counts_g, "s2": s2_g, "s1": s1_g, "seconds": round(time.time() - t, 1)})

    internal = [r for r in receipts if r["reason"] not in USER_RECEIPTS]
    receipts = sorted([r for r in receipts if r["reason"] in USER_RECEIPTS], key=lambda r: r["date"])
    n_cells = sum(len(g["cells_geojson"]) for g in groups)
    summary = {"mode": "ring", "profile": "live", "inner_m": inner_m, "outer_m": outer_m,
               "donor_res_m": donor_res, "max_cloud": cfg["max_cloud"], "per_bin": cfg["per_bin"],
               "s2_scenes_found": counts_t["s2_found"], "s2_scenes_covering": counts_t["s2_covering"],
               "s2_scenes_read": counts_t["s2_read"],
               "s2_observations": s2_t.n_obs if s2_t else 0,
               "s1_scenes_found": counts_t["s1_found"], "s1_scenes_covering": counts_t["s1_covering"],
               "s1_observations": s1_t.n_obs if s1_t else 0, "s1_orbit": counts_t["orbit"],
               "n_donor_cells": n_cells, "n_groups": len(groups), "cell_m": round(grid.cell_m),
               "treated_landcover": int(cov.landcover[0]) if cov else 0,
               "internal_receipts": len(internal),
               "receipts": {r: sum(1 for x in receipts if x["reason"] == r)
                            for r in sorted({x["reason"] for x in receipts})}}
    timing["total_s"] = round(time.time() - t0, 1)
    all_cells = [c for g in groups for c in g["cells_geojson"]]
    all_d = [d for g in groups for d in g["distance_m"]]
    data = AreaData(area_geojson=area.geojson, area_ha=round(area.area_ha, 2), epsg=area.epsg,
                    cells_geojson=all_cells, cell_distance_m=all_d, start=start, end=end,
                    s2=s2_t, s1=s1_t, receipts=receipts, summary=summary, timing=timing,
                    mode="ring", groups=groups)
    if use_cache:
        data.save(cdir)
    return data
