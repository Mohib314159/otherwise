"""Fetch and clean Sentinel-1 + Sentinel-2 for one polygon. Milestone 1 CLI.

    python -m scripts.fetch_area --bbox -1.29,52.905,-1.28,52.912 --start 2021-01-01 --end 2023-12-31
    python -m scripts.fetch_area --geojson area.geojson --start ... --end ... --cells 100
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np
from shapely.geometry import box, mapping

from src.app.fetch import fetch_area


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", help="minlon,minlat,maxlon,maxlat")
    ap.add_argument("--geojson", help="path to a GeoJSON polygon/feature")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--cells", type=int, default=200)
    ap.add_argument("--provider", default="pc", choices=["pc", "es"])
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--s2-only", action="store_true")
    ap.add_argument("--out", help="write a CSV of the treated-area series here")
    a = ap.parse_args(argv)
    if a.bbox:
        geo = mapping(box(*[float(v) for v in a.bbox.split(",")]))
    else:
        with open(a.geojson) as f:
            geo = json.load(f)
            if geo.get("type") == "FeatureCollection":
                geo = geo["features"][0]

    last = {"t": time.time()}
    def progress(stage, done, total):
        if time.time() - last["t"] > 2 or done == total:
            print(f"  {stage}: {done}/{total}", file=sys.stderr, flush=True)
            last["t"] = time.time()

    d = fetch_area(geo, a.start, a.end, max_cells=a.cells, providers=a.provider,
                   use_cache=not a.no_cache, progress=progress,
                   sensors=("S2",) if a.s2_only else ("S2", "S1"))
    print(json.dumps({"area_ha": d.area_ha, "summary": d.summary, "timing": d.timing}, indent=2))
    for name, ss in (("S2", d.s2), ("S1", d.s1)):
        if ss is None:
            continue
        keys = [k for k in ss.values if k not in ("clear_frac", "valid_frac")]
        print(f"\n{name}: {ss.n_obs} observations {ss.dates[0]} .. {ss.dates[-1]}  {ss.meta}")
        for k in keys:
            t = ss.treated(k)
            dn = ss.donors(k)
            print(f"  {k:6s} treated mean {np.nanmean(t):+.3f}  sd {np.nanstd(t):.3f} | "
                  f"donor cells with >=80% coverage: {int(np.mean(np.isfinite(dn), axis=0).__ge__(0.8).sum())}/{dn.shape[1]}")
    print("\nReceipts (first 12):")
    for r in d.receipts[:12]:
        print(f"  {r['sensor']} {r['date']} {r['reason']:10s} {r['detail']}")
    if a.out and d.s2 is not None:
        import csv
        with open(a.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "sensor"] + [k for k in d.s2.values])
            for i, dt in enumerate(d.s2.dates):
                w.writerow([dt, "S2"] + [f"{d.s2.values[k][i, 0]:.4f}" for k in d.s2.values])
            if d.s1 is not None:
                w.writerow([]); w.writerow(["date", "sensor"] + list(d.s1.values))
                for i, dt in enumerate(d.s1.dates):
                    w.writerow([dt, "S1"] + [f"{d.s1.values[k][i, 0]:.4f}" for k in d.s1.values])
    return 0


if __name__ == "__main__":
    sys.exit(main())
