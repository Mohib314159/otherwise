"""Run one live verdict and report peak RSS. Used to prove a live run fits the
free tier: `docker run --memory=512m ... python -m scripts.memtest`.

Prints peak resident set size sampled from /proc, plus the run's own timing and
scene counts, so a failure says which of the two budgets was blown.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

PEAK = {"rss": 0}
_stop = threading.Event()


def _sample():
    while not _stop.is_set():
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmHWM:"):
                        PEAK["rss"] = max(PEAK["rss"], int(line.split()[1]) * 1024)
                        break
        except OSError:
            pass
        time.sleep(0.2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--geojson", help="path to a GeoJSON polygon; defaults to the Grunheide showcase area")
    ap.add_argument("--event-date", default="2020-02-17")
    ap.add_argument("--change-type", default="clearing")
    ap.add_argument("--post-months", type=int, default=12)
    ap.add_argument("--profile", default="live", choices=("live", "full"))
    ap.add_argument("--mode", default="ring", choices=("ring", "wide", "auto"))
    ap.add_argument("--budget-mb", type=float, default=400.0)
    ap.add_argument("--out", default="")
    ap.add_argument("--rlimit-mb", type=float, default=0.0,
                    help="hard cap on address space (RLIMIT_AS) before the run, in MB; "
                         "0 disables. Use 512 to reproduce the free tier's ceiling.")
    a = ap.parse_args()

    if a.geojson:
        with open(a.geojson) as f:
            gj = json.load(f)
        gj = gj.get("geometry", gj)
    else:
        with open(os.path.join("showcase", "5a5f8d14423c28f0.json")) as f:
            gj = json.load(f)["area"]["geojson"]

    # Imported before the cap is applied: RLIMIT_AS counts reserved address space,
    # and numpy/scipy/GDAL reserve far more VA at import than they ever make
    # resident, so capping first fails on imports rather than on the workload.
    from src.app.run import run_verdict
    import rasterio  # noqa: F401  (pull GDAL's own reservations in too)

    if a.rlimit_mb:
        import resource
        b = int(a.rlimit_mb * 1024 * 1024)
        resource.setrlimit(resource.RLIMIT_AS, (b, b))
        print(f"    RLIMIT_AS capped at {a.rlimit_mb:.0f} MB after imports", flush=True)

    t = threading.Thread(target=_sample, daemon=True)
    t.start()
    t0 = time.time()
    last = [""]

    def progress(stage, done, total):
        if stage != last[0]:
            print(f"    [{time.time() - t0:6.1f}s] {stage} ({total} to read)", flush=True)
            last[0] = stage

    try:
        out = run_verdict(gj, a.event_date, a.change_type, a.post_months,
                          progress=progress, save=False, mode=a.mode, profile=a.profile)
    finally:
        _stop.set()
        time.sleep(0.3)

    peak_mb = PEAK["rss"] / 1e6
    ds = out["data_summary"]
    print(json.dumps({
        "profile": a.profile, "mode": out["mode"], "verdict": out["verdict"]["status"],
        "lead_signal": out["verdict"]["lead_signal"],
        "peak_rss_mb": round(peak_mb, 1), "budget_mb": a.budget_mb,
        "wall_s": round(time.time() - t0, 1),
        "s2_found": ds.get("s2_scenes_found"), "s2_covering": ds.get("s2_scenes_covering"),
        "s2_read": ds.get("s2_scenes_read"), "s2_observations": ds.get("s2_observations"),
        "s1_observations": ds.get("s1_observations"),
        "donor_cells": ds.get("n_donor_cells"), "donor_res_m": ds.get("donor_res_m"),
        "timing": out["timing"],
    }, indent=2), flush=True)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(out, f)
    if peak_mb > a.budget_mb:
        print(f"FAIL: peak RSS {peak_mb:.0f} MB over the {a.budget_mb:.0f} MB budget", file=sys.stderr)
        return 1
    print(f"OK: peak RSS {peak_mb:.0f} MB within the {a.budget_mb:.0f} MB budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
