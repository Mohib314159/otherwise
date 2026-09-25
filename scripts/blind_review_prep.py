"""Render the imagery a blind reviewer needs, for every finished blind run.

    python -m scripts.blind_review_prep --sample showcase/blind/sample.json --parallel 3
    python -m scripts.blind_review_prep ... --frames        # also the time-lapse frames
    python -m scripts.blind_review_prep ... --limit 20      # stop after 20 new cases

Writes `<blind dir>/runs/<run id>_before.png`, `_after.png` and, with
`--frames`, `_t<i>.png` plus `_frames.json`, beside the run JSON that
`scripts/blind_validation.py` produced. `src/app/review.py` serves these under
opaque case ids; a case only enters the review pool once both thumbnails exist.

Resumable: a case whose files are already on disk is skipped, so the command
can be re-run as more verdict runs finish. Nothing here decides anything --
it only fetches pictures -- so it is safe to run while the validation runner
is still going.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time
import traceback


def _worker(args: dict) -> dict:
    os.environ.setdefault("APP_CACHE_DIR", "data/cache/blind")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    item, run_id, runs_dir, frames = args["item"], args["run_id"], args["runs_dir"], args["frames"]
    t0 = time.time()
    out = {"id": item["id"], "run_id": run_id, "tags": [], "frames": 0, "error": None}
    try:
        from src.app.imagery import make_thumbnails, make_timelapse
        thumbs = make_thumbnails(item["geojson"], item["event_date"], runs_dir, run_id)
        out["tags"] = sorted(thumbs)
        if frames:
            rj = os.path.join(runs_dir, run_id + ".json")
            with open(rj) as f:
                run = json.load(f)
            start, end = run["window"]
            fr = make_timelapse(item["geojson"], start, end, runs_dir, run_id)
            out["frames"] = len(fr)
    except Exception as e:                                # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
        out["traceback"] = traceback.format_exc()[-800:]
    out["seconds"] = round(time.time() - t0, 1)
    return out


def rows_by_id(path: str) -> dict:
    rows = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    rows[r["id"]] = r
    return rows


def todo_items(sample: dict, rows: dict, runs_dir: str, frames: bool) -> list[tuple[dict, str]]:
    out = []
    for item in sample["items"]:
        row = rows.get(item["id"])
        if not row or not row.get("run_id"):
            continue
        rid = row["run_id"]
        have = all(os.path.exists(os.path.join(runs_dir, f"{rid}_{t}.png")) for t in ("before", "after"))
        if frames:
            have = have and os.path.exists(os.path.join(runs_dir, f"{rid}_frames.json"))
        if not have:
            out.append((item, rid))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sample", default="showcase/blind/sample.json")
    ap.add_argument("--out", default="showcase/blind/")
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--frames", action="store_true", help="also render the time-lapse frames")
    a = ap.parse_args(argv)

    out_dir = a.out if a.out.endswith("/") else a.out + "/"
    runs_dir = os.path.join(out_dir, "runs")
    with open(a.sample) as f:
        sample = json.load(f)
    rows = rows_by_id(os.path.join(out_dir, "results.jsonl"))
    todo = todo_items(sample, rows, runs_dir, a.frames)
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(rows)} finished runs, {len(todo)} need imagery, parallel={a.parallel}", flush=True)
    if not todo:
        return

    ctx = mp.get_context("spawn")
    done = 0
    t0 = time.time()
    with ctx.Pool(processes=a.parallel, maxtasksperchild=1) as pool:
        args = [{"item": it, "run_id": rid, "runs_dir": runs_dir, "frames": a.frames} for it, rid in todo]
        for res in pool.imap_unordered(_worker, args):
            done += 1
            print(f"[{done}/{len(todo)}] {res['id']} tags={res['tags']} frames={res['frames']} "
                  f"{res['seconds']}s{(' ERROR ' + res['error']) if res['error'] else ''} "
                  f"({(time.time() - t0) / 60:.0f} min)", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
