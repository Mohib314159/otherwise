"""Benchmark: server-side (PC titiler) control-ring reads vs the live profile's local reads.

For each showcase site this rebuilds the live profile's control ring exactly as
`fetch._fetch_live_ring` does (donor_grid with the live max_cells, the donor
read resolution from `choose_donor_res`, the live scene pre-filters), samples
N scenes evenly from the resulting scene list, then for every scene:

  local : s2.process_scene(scene, zones, sign, res=40, require_zone0=False)
  remote: remote_s2.fetch_scene_cells(scene, ..., res_m=40, index="NDVI")
          (then again with index=("NDWI", "NBR") for the accuracy check only)

and reports per-cell agreement, CLEAR_MIN agreement, wall time and process CPU
seconds per scene (remote sequential, and with 8 / 16 concurrent requests).

    nice -n 19 env OPENBLAS_NUM_THREADS=1 python -m scripts.bench_remote_s2 \
        --sites f8b923727d8e96f4 5a5f8d14423c28f0 0423e078c5f38593 --n 30 --out bench.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app import remote_s2 as R  # noqa: E402
from src.app import s2 as s2mod  # noqa: E402
from src.app.extract import Zones  # noqa: E402
from src.app.fetch import (PROFILES, _covering, _latest_processing, best_tile_per_minute,  # noqa: E402
                           cap_per_bin, choose_donor_res)
from src.app.geometry import donor_grid, reproject, validate_polygon  # noqa: E402
from src.app.providers import PlanetaryComputer  # noqa: E402

INDICES = ("NDVI", "NDWI", "NBR")


def live_ring(site_id: str):
    r = json.load(open(f"showcase/{site_id}.json"))
    from shapely.geometry import box
    area = validate_polygon(r["area"]["geojson"])
    cfg = PROFILES["live"]
    grid = donor_grid(area, inner_m=1000.0, outer_m=12000.0, max_cells=cfg["max_cells"])
    res = choose_donor_res([area.utm] + grid.cells)
    cells = grid.cells
    minx = min(c.bounds[0] for c in cells); miny = min(c.bounds[1] for c in cells)
    maxx = max(c.bounds[2] for c in cells); maxy = max(c.bounds[3] for c in cells)
    g_wgs = reproject(box(minx, miny, maxx, maxy), area.epsg, 4326)
    return r, area, grid, res, g_wgs, cfg


def live_scenes(prov, g_wgs, start, end, event, cfg):
    found = prov.search_s2([float(v) for v in g_wgs.bounds], start, end, max_cloud=cfg["max_cloud"])
    sc = _latest_processing(_covering(found, g_wgs))
    sc, _ = best_tile_per_minute(sc, g_wgs)
    sc, _ = cap_per_bin(sc, event, 10, cfg["per_bin"])
    return found, sc


def attach_tile_bounds(scenes):
    """Scene objects carry no tile extent; the local read clips its window to
    the tile, so fetch each item's SCL proj:bbox (one STAC call per 100 ids)."""
    import requests
    from src.app.providers import PC_STAC
    tb = {}
    ids = [s.id for s in scenes]
    for i in range(0, len(ids), 100):
        r = requests.post(f"{PC_STAC}/search", json={"collections": ["sentinel-2-l2a"], "ids": ids[i:i + 100],
                                                    "limit": 100}, timeout=90)
        r.raise_for_status()
        for it in r.json()["features"]:
            tb[it["id"]] = it["assets"]["SCL"].get("proj:bbox")
    for s in scenes:
        if tb.get(s.id):
            s.props["tile_bounds"] = tuple(tb[s.id])


def local_one(sc, zones, sign, res):
    t0, c0 = time.perf_counter(), time.process_time()
    o, rec = s2mod.process_scene(sc, zones, sign, res=res, require_zone0=False)
    return o, rec, time.perf_counter() - t0, time.process_time() - c0


def remote_batch(scenes, zones_by_epsg, area_epsg, cells, res, workers, indices=("NDVI",), keep_raw=False):
    out = {}
    t0, c0 = time.perf_counter(), time.process_time()

    def one(sc):
        try:
            return sc.id, R.fetch_scene_cells(sc, area_epsg, cells, res, index=indices,
                                              zones=zones_by_epsg[sc.epsg], keep_raw=keep_raw), None
        except Exception as e:      # recorded, not fatal
            return sc.id, None, repr(e)[:300]

    if workers == 1:
        res_list = [one(sc) for sc in scenes]
    else:
        with ThreadPoolExecutor(workers) as ex:
            res_list = list(ex.map(one, scenes))
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    for sid, sc_cells, err in res_list:
        out[sid] = (sc_cells, err)
    return out, wall, cpu


def compare(local, remote, indices=INDICES):
    """Per-cell comparison over scenes where both sides returned something."""
    d = {k: [] for k in indices}
    cf_d, clear_agree, n_cells_cmp, npx_eq = [], [], 0, []
    kept_agree = []
    diff_scenes = []
    for sid, (o, _rec, _w, _c) in local.items():
        rc, err = remote.get(sid, (None, "missing"))
        if rc is None:
            continue
        r_kept = bool(np.any(rc.clear_frac >= s2mod.CLEAR_MIN))
        kept_agree.append((o is not None) == r_kept)
        if o is None:
            continue
        cf_d.append(np.abs(rc.clear_frac - o.clear_frac))
        clear_agree.append((rc.clear_frac >= s2mod.CLEAR_MIN) == (o.clear_frac >= s2mod.CLEAR_MIN))
        npx_eq.append(rc.n_px == o.n_pixels)
        n_cells_cmp += len(o.clear_frac)
        for k in indices:
            a, b = rc.values[k], o.values[k]
            both = np.isfinite(a) & np.isfinite(b)
            d[k].append(np.abs(a[both] - b[both]))
            nbad = int(np.sum(np.abs(a[both] - b[both]) > 1e-4))
            if nbad:
                diff_scenes.append((sid[:60], k, o.props.get("baseline"), nbad,
                                    float(np.max(np.abs(a[both] - b[both])))))
            # a value on one side only (should not happen when CLEAR_MIN agrees)
    summ = {}
    one_sided = 0
    for sid, (o, _rec, _w, _c) in local.items():
        rc = remote.get(sid, (None,))[0]
        if o is not None and rc is not None:
            for k in indices:
                one_sided += int(np.sum(np.isfinite(rc.values[k]) != np.isfinite(o.values[k])))
    summ["value_on_one_side_only"] = one_sided
    for k in indices:
        x = np.concatenate(d[k]) if d[k] else np.array([])
        summ[k] = {"n": int(x.size), "median_abs": float(np.median(x)) if x.size else None,
                   "p95_abs": float(np.percentile(x, 95)) if x.size else None,
                   "max_abs": float(x.max()) if x.size else None,
                   "exact_frac_1e-6": float(np.mean(x < 1e-6)) if x.size else None}
    cf = np.concatenate(cf_d) if cf_d else np.array([])
    ca = np.concatenate(clear_agree) if clear_agree else np.array([])
    ne = np.concatenate(npx_eq) if npx_eq else np.array([])
    summ["clear_frac"] = {"median_abs": float(np.median(cf)) if cf.size else None,
                          "max_abs": float(cf.max()) if cf.size else None}
    summ["clear_min_agreement"] = float(ca.mean()) if ca.size else None
    summ["clear_min_disagree_cells"] = int((~ca).sum()) if ca.size else None
    summ["cells_compared"] = int(ca.size)
    summ["n_px_equal_frac"] = float(ne.mean()) if ne.size else None
    summ["scene_kept_agreement"] = float(np.mean(kept_agree)) if kept_agree else None
    summ["scenes_compared"] = len(kept_agree)
    summ["cells_over_1e-4"] = sum(x[3] for x in diff_scenes)
    summ["scenes_with_cells_over_1e-4"] = diff_scenes
    return summ


def run_site(site_id, n, prov, workers_list, skip_local=False, extra_indices=True):
    r, area, grid, res, g_wgs, cfg = live_ring(site_id)
    start, end = r["window"]
    found, scenes = live_scenes(prov, g_wgs, start, end, r["event_date"], cfg)
    idx = np.unique(np.linspace(0, len(scenes) - 1, min(n, len(scenes))).round().astype(int))
    sample = [scenes[i] for i in idx]
    epsgs = {sc.epsg for sc in sample}
    zones = {e: Zones.build(grid.cells, area.epsg, e) for e in epsgs}
    info = {"site": site_id, "label": r["label"], "area_ha": round(area.area_ha, 1),
            "n_cells": len(grid.cells), "donor_res": res, "scenes_found": len(found),
            "scenes_live": len(scenes), "sampled": len(sample), "epsg": sorted(epsgs),
            "window_px_40m": {e: R.output_grid(z.bounds, res) for e, z in zones.items()}}
    print(json.dumps(info), flush=True)
    prov.sign(sample[0].hrefs["SCL"])        # warm the token cache outside timing
    attach_tile_bounds(sample)

    local = {}
    if not skip_local:
        for sc in sample:
            local[sc.id] = local_one(sc, zones[sc.epsg], prov.sign, res)
        lw = np.array([v[2] for v in local.values()]); lc = np.array([v[3] for v in local.values()])
        kept = np.array([v[0] is not None for v in local.values()])
        info["local"] = {"wall_s_total": float(lw.sum()), "cpu_s_total": float(lc.sum()),
                         "kept": int(kept.sum()),
                         "cpu_s_per_kept_scene_median": float(np.median(lc[kept])) if kept.any() else None,
                         "cpu_s_per_rejected_scene_median": float(np.median(lc[~kept])) if (~kept).any() else None,
                         "wall_s_per_kept_scene_median": float(np.median(lw[kept])) if kept.any() else None,
                         "wall_s_per_rejected_scene_median": float(np.median(lw[~kept])) if (~kept).any() else None}
        print("local", json.dumps(info["local"]), flush=True)

    info["remote"] = {}
    first = None
    for w in workers_list:
        R._label_cache.clear()
        out, wall, cpu = remote_batch(sample, zones, area.epsg, grid.cells, res, w)
        ok = [v[0] for v in out.values() if v[0] is not None]
        errs = [v[1] for v in out.values() if v[1]]
        st = [o.stats for o in ok]
        entry = {"workers": w, "wall_s_total": wall, "cpu_s_total": cpu,
                 "wall_s_per_scene": wall / len(sample), "cpu_s_per_scene": cpu / len(sample),
                 "n_ok": len(ok), "n_err": len(errs), "errors": errs[:3],
                 "retries": int(sum(s["attempts"] - 1 for s in st)),
                 "statuses_non200": sorted({str(x) for s in st for x in s["statuses"] if x != 200}),
                 "req_s_median": float(np.median([s["net_s"] for s in st])) if st else None,
                 "req_s_p90": float(np.percentile([s["net_s"] for s in st], 90)) if st else None,
                 "req_s_max": float(max(s["net_s"] for s in st)) if st else None,
                 "bytes_median": float(np.median([s["bytes"] for s in st])) if st else None}
        if w == 1:
            entry["cpu_s_per_scene_median_seq"] = float(np.median([s["cpu_s"] for s in st])) if st else None
        info["remote"][str(w)] = entry
        print("remote", json.dumps(entry), flush=True)
        if first is None:
            first = out
    if local and first:
        info["compare"] = compare(local, first, ("NDVI",))
        print("compare", json.dumps(info["compare"]), flush=True)
        # the same scenes labelled on the grid the server really sampled
        R._label_cache.clear()
        tg = {}
        for sc in sample:
            try:
                tg[sc.id] = (R.fetch_scene_cells(sc, area.epsg, grid.cells, res, index="NDVI",
                                                 zones=zones[sc.epsg], true_grid=True), None)
            except Exception as e:
                tg[sc.id] = (None, repr(e))
        info["compare_true_grid"] = compare(local, tg, ("NDVI",))
        print("compare_true_grid", json.dumps(info["compare_true_grid"]), flush=True)
        if extra_indices:
            R._label_cache.clear()
            out, wall, cpu = remote_batch(sample, zones, area.epsg, grid.cells, res, 4, indices=("NDWI", "NBR"))
            st = [v[0].stats for v in out.values() if v[0] is not None]
            info["compare_ndwi_nbr"] = compare(local, out, ("NDWI", "NBR"))
            info["compare_ndwi_nbr"]["bytes_median"] = float(np.median([x["bytes"] for x in st])) if st else None
            info["compare_ndwi_nbr"]["cpu_s_per_scene"] = cpu / len(sample)
            print("compare_ndwi_nbr", json.dumps(info["compare_ndwi_nbr"]), flush=True)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 8, 16])
    ap.add_argument("--skip-local", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    prov = PlanetaryComputer()
    results = []
    for s in a.sites:
        results.append(run_site(s, a.n, prov, a.workers, a.skip_local))
        if a.out:
            json.dump(results, open(a.out, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
