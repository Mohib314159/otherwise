"""Benchmark: server-side (PC data API) Sentinel-1 RTC donor reads vs the live profile's local reads.

Rebuilds the live control ring (as scripts/bench_remote_s2.py does), selects S1
scenes exactly as `fetch._fetch_group` does for a donor group (main relative
orbit over the group, at most `per_bin` per analysis bin), samples N evenly,
and for each scene compares

  local : s1.process_scene(scene, zones, sign, res=40, require_zone0=False)
  remote: remote_s1.fetch_scene_cells(scene, ..., res_m=40)

    nice -n 19 env OPENBLAS_NUM_THREADS=1 python -m scripts.bench_remote_s1 \
        --sites f8b923727d8e96f4 5a5f8d14423c28f0 0423e078c5f38593 --n 30 --out bench_s1.json
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

from scripts.bench_remote_s2 import live_ring  # noqa: E402
from src.app import remote_s1 as R1  # noqa: E402
from src.app import remote_s2 as R2  # noqa: E402
from src.app import s1 as s1mod  # noqa: E402
from src.app.extract import Zones  # noqa: E402
from src.app.fetch import cap_per_bin  # noqa: E402
from src.app.providers import PlanetaryComputer  # noqa: E402

KEYS = ("VV", "VH", "RATIO")


def live_s1_scenes(prov, g_wgs, start, end, event, cfg):
    found = prov.search_s1([float(v) for v in g_wgs.bounds], start, end)
    sc, _rec, orbit = s1mod.select_orbit_scenes(found, g_wgs)
    sc, _ = cap_per_bin(sc, event, 10, cfg["per_bin"])
    return found, sc, orbit


def compare(local, remote):
    d = {k: [] for k in KEYS}
    vf_d, agree, npx_eq, kept_agree, one_sided, diff_scenes = [], [], [], [], 0, []
    for sid, (o, _rec, _w, _c) in local.items():
        rc, err = remote.get(sid, (None, "missing"))
        if rc is None:
            continue
        kept_agree.append((o is not None) == bool(np.any(rc.clear_frac >= s1mod.VALID_MIN)))
        if o is None:
            continue
        vf_d.append(np.abs(rc.clear_frac - o.valid_frac))
        agree.append((rc.clear_frac >= s1mod.VALID_MIN) == (o.valid_frac >= s1mod.VALID_MIN))
        npx_eq.append(rc.n_px == o.n_pixels)
        for k in KEYS:
            a, b = rc.values[k], o.values[k]
            one_sided += int(np.sum(np.isfinite(a) != np.isfinite(b)))
            both = np.isfinite(a) & np.isfinite(b)
            x = np.abs(a[both] - b[both])
            d[k].append(x)
            if x.size and x.max() > 0.01:
                diff_scenes.append((sid[:60], k, int((x > 0.01).sum()), float(x.max())))
    s = {"value_on_one_side_only": one_sided}
    for k in KEYS:
        x = np.concatenate(d[k]) if d[k] else np.array([])
        s[k + "_dB"] = {"n": int(x.size), "median_abs": float(np.median(x)) if x.size else None,
                        "p95_abs": float(np.percentile(x, 95)) if x.size else None,
                        "max_abs": float(x.max()) if x.size else None,
                        "frac_within_0.001dB": float(np.mean(x <= 1e-3)) if x.size else None}
    vf = np.concatenate(vf_d) if vf_d else np.array([])
    ag = np.concatenate(agree) if agree else np.array([])
    ne = np.concatenate(npx_eq) if npx_eq else np.array([])
    s["valid_frac"] = {"median_abs": float(np.median(vf)) if vf.size else None,
                       "max_abs": float(vf.max()) if vf.size else None}
    s["valid_min_agreement"] = float(ag.mean()) if ag.size else None
    s["valid_min_disagree_cells"] = int((~ag).sum()) if ag.size else None
    s["cells_compared"] = int(ag.size)
    s["n_px_equal_frac"] = float(ne.mean()) if ne.size else None
    s["scene_kept_agreement"] = float(np.mean(kept_agree)) if kept_agree else None
    s["scenes_compared"] = len(kept_agree)
    s["scenes_with_cells_over_0.01dB"] = diff_scenes
    return s


def run_site(site_id, n, prov, workers_list):
    r, area, grid, res, g_wgs, cfg = live_ring(site_id)
    start, end = r["window"]
    found, scenes, orbit = live_s1_scenes(prov, g_wgs, start, end, r["event_date"], cfg)
    idx = np.unique(np.linspace(0, len(scenes) - 1, min(n, len(scenes))).round().astype(int))
    sample = [scenes[i] for i in idx]
    zones = {e: Zones.build(grid.cells, area.epsg, e) for e in {sc.epsg for sc in sample}}
    info = {"site": site_id, "label": r["label"], "n_cells": len(grid.cells), "donor_res": res,
            "s1_found": len(found), "s1_live": len(scenes), "orbit": orbit, "sampled": len(sample),
            "epsg": sorted(zones), "with_grid_bounds": sum(1 for s in sample if s.props.get("grid_bounds"))}
    print(json.dumps(info), flush=True)
    prov.sign(sample[0].hrefs["VV"])

    local = {}
    for sc in sample:
        t0, c0 = time.perf_counter(), time.process_time()
        o, rec = s1mod.process_scene(sc, zones[sc.epsg], prov.sign, res=res, require_zone0=False)
        local[sc.id] = (o, rec, time.perf_counter() - t0, time.process_time() - c0)
    lw = np.array([v[2] for v in local.values()]); lc = np.array([v[3] for v in local.values()])
    info["local"] = {"kept": int(sum(v[0] is not None for v in local.values())),
                     "wall_s_total": float(lw.sum()), "cpu_s_total": float(lc.sum()),
                     "cpu_s_per_scene_median": float(np.median(lc)), "cpu_s_per_scene_mean": float(lc.mean()),
                     "wall_s_per_scene_median": float(np.median(lw))}
    print("local", json.dumps(info["local"]), flush=True)

    info["remote"] = {}
    first = None
    for w in workers_list:
        R2._label_cache.clear()

        def one(sc):
            try:
                return sc.id, R1.fetch_scene_cells(sc, area.epsg, grid.cells, res, zones=zones[sc.epsg]), None
            except Exception as e:
                return sc.id, None, repr(e)[:300]
        t0, c0 = time.perf_counter(), time.process_time()
        if w == 1:
            res_list = [one(sc) for sc in sample]
        else:
            with ThreadPoolExecutor(w) as ex:
                res_list = list(ex.map(one, sample))
        wall, cpu = time.perf_counter() - t0, time.process_time() - c0
        out = {sid: (sc_, err) for sid, sc_, err in res_list}
        st = [v[0].stats for v in out.values() if v[0] is not None]
        errs = [v[1] for v in out.values() if v[1]]
        e = {"workers": w, "wall_s_total": wall, "cpu_s_total": cpu, "wall_s_per_scene": wall / len(sample),
             "cpu_s_per_scene": cpu / len(sample), "n_ok": len(st), "n_err": len(errs), "errors": errs[:3],
             "retries": int(sum(s["attempts"] - 1 for s in st)),
             "statuses_non200": sorted({str(x) for s in st for x in s["statuses"] if x != 200}),
             "req_s_median": float(np.median([s["net_s"] for s in st])) if st else None,
             "req_s_max": float(max(s["net_s"] for s in st)) if st else None,
             "bytes_median": float(np.median([s["bytes"] for s in st])) if st else None,
             "clipped_px_total": int(sum(s["clipped_px"] for s in st))}
        info["remote"][str(w)] = e
        print("remote", json.dumps(e), flush=True)
        if first is None:
            first = out
    info["compare"] = compare(local, first)
    print("compare", json.dumps(info["compare"]), flush=True)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 8])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    prov = PlanetaryComputer()
    results = []
    for s in a.sites:
        results.append(run_site(s, a.n, prov, a.workers))
        if a.out:
            json.dump(results, open(a.out, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
