"""Run one unlisted outreach verdict and write it to showcase/ so its permalink
(/v/<id>) survives on the free host once committed. The run is added to
showcase/index.json with "listed": false: it is served by id but never shown on
the landing page, the map, or the track record."""
from __future__ import annotations

import argparse
import json
import os
import traceback

from shapely.geometry import box, mapping

INDEX_PATH = "showcase/index.json"


def parse_bbox(text: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(x) for x in text.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError("--bbox must be minlon,minlat,maxlon,maxlat")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("--bbox must be minlon,minlat,maxlon,maxlat")
    minlon, minlat, maxlon, maxlat = parts
    if not (minlon < maxlon and minlat < maxlat):
        raise argparse.ArgumentTypeError("--bbox needs min < max for both axes")
    return minlon, minlat, maxlon, maxlat


def index_entry(run_id: str, label: str, change_type: str) -> dict:
    return {"key": f"outreach-{run_id}", "id": run_id, "label": label, "blurb": "",
            "expected": None, "source": "", "type": change_type,
            "confirmed": False, "listed": False}


def add_to_index(entry: dict, index_path: str = INDEX_PATH) -> None:
    index = json.load(open(index_path)) if os.path.exists(index_path) else []
    index = [e for e in index if e.get("id") != entry["id"]]
    index.append(entry)
    json.dump(index, open(index_path, "w"), indent=1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bbox", required=True, type=parse_bbox, help="minlon,minlat,maxlon,maxlat")
    ap.add_argument("--event", required=True, help="YYYY-MM-DD")
    ap.add_argument("--type", default="clearing", dest="change_type")
    ap.add_argument("--post", type=int, default=12, help="months after the event")
    ap.add_argument("--label", required=True)
    a = ap.parse_args(argv)

    from src.app.run import run_verdict
    geo = mapping(box(*a.bbox))
    out = run_verdict(geo, a.event, a.change_type, a.post, label=a.label,
                      progress=lambda st, d, tt: None, save=True, runs_dir="showcase")
    try:
        from src.app.imagery import make_thumbnails
        info = make_thumbnails(geo, a.event, "showcase", out["id"])
        for tag, meta in info.items():
            json.dump(meta, open(f"showcase/{out['id']}_{tag}.json", "w"))
    except Exception:
        traceback.print_exc()
    add_to_index(index_entry(out["id"], a.label, a.change_type))
    print(f"/v/{out['id']}  {out['verdict']['status']}  (unlisted)")


if __name__ == "__main__":
    main()
