"""Run the pixel-level change test on a stored showcase run.

    python -m scripts.pixel_change <showcase_id> [<showcase_id> ...]

Reads showcase/<id>.json (area.geojson, event_date, change_type, post_months),
writes showcase/<id>_change.png and showcase/<id>_change.json, prints the result.
"""
from __future__ import annotations

import json
import sys
import time

from src.app.pixels import compute_pixel_change


def main(ids: list[str]) -> None:
    for sid in ids:
        r = json.load(open(f"showcase/{sid}.json"))
        t0 = time.time()
        out = compute_pixel_change(r["area"]["geojson"], r["event_date"], r["change_type"],
                                   int(r["post_months"]), out_dir="showcase", run_id=sid)
        out["_seconds"] = round(time.time() - t0, 1)
        print(sid, r.get("label", ""))
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
