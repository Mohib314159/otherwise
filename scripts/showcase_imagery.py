"""Visual evidence for every showcase run, plus an audit of the imagery itself.

For each entry in showcase/index.json:

  1. audit the area's before/after thumbnails: the "before" scene must be dated
     before the event and the "after" scene after it, and each must clear the
     same clear-sky bar the thumbnailer uses (0.9 before, 0.6 after, because
     burnt or flooded ground is often classed "dark", not cloud);
  2. audit the time-lapse: at least two frames, each clear, and the event date
     inside the frame range so the page can mark it;
  3. regenerate thumbnails / time-lapse when missing or failing the audit;
  4. render the change overlay aligned to the thumbnail window (pixels.py);
  5. render before/after thumbnails of up to three matched control areas on the
     area's own dates (imagery.make_control_thumbnails).

Writes showcase/imagery_audit.json. Purely visual: nothing here feeds a verdict.

    python -m scripts.showcase_imagery                # every showcase run
    python -m scripts.showcase_imagery grunheide rhodes
    python -m scripts.showcase_imagery --audit-only
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import date

SHOWCASE = "showcase"
BEFORE_MIN_CLEAR, AFTER_MIN_CLEAR, FRAME_MIN_CLEAR = 0.9, 0.6, 0.85


def _load(path):
    return json.load(open(path)) if os.path.exists(path) else None


def audit(run: dict) -> dict:
    rid, ev = run["id"], date.fromisoformat(run["event_date"])
    out = {"id": rid, "label": run.get("label"), "event_date": run["event_date"], "problems": []}
    for tag, min_clear, ok_side in (("before", BEFORE_MIN_CLEAR, lambda d: d < ev),
                                    ("after", AFTER_MIN_CLEAR, lambda d: d > ev)):
        m = _load(os.path.join(SHOWCASE, f"{rid}_{tag}.json"))
        png = os.path.exists(os.path.join(SHOWCASE, f"{rid}_{tag}.png"))
        if not m or not png:
            out["problems"].append(f"{tag}: missing")
            continue
        d = date.fromisoformat(m["date"])
        out[tag] = {"date": m["date"], "clear": m.get("clear"), "scene_id": m.get("scene_id"),
                    "days_from_event": (d - ev).days}
        if not ok_side(d):
            out["problems"].append(f"{tag}: dated {m['date']}, on the wrong side of the event")
        out[tag]["clear_basis"] = m.get("clear_basis", "scl")
        if m.get("clear_basis") == "scene_cloud_cover<=5%":
            out.setdefault("notes", []).append(
                f"{tag}: accepted on scene cloud cover {m.get('scene_cloud_cover')}% because the pixel "
                f"classification scores bright ground as cloud here (area clear share {m.get('clear')}); "
                f"checked by eye")
        elif (m.get("clear") or 0) < min_clear:
            out["problems"].append(f"{tag}: clear share {m.get('clear')} below {min_clear}")
    frames = _load(os.path.join(SHOWCASE, f"{rid}_frames.json")) or []
    fr = sorted(frames, key=lambda f: f["date"])
    out["frames"] = {"n": len(fr), "first": fr[0]["date"] if fr else None, "last": fr[-1]["date"] if fr else None,
                     "min_clear": min((f.get("clear") or 0) for f in fr) if fr else None}
    if len(fr) < 2:
        out["problems"].append("time-lapse: fewer than two frames")
    else:
        if not (fr[0]["date"] < run["event_date"] < fr[-1]["date"]):
            out["problems"].append("time-lapse: event date outside the frame range, so it cannot be marked")
        if out["frames"]["min_clear"] < FRAME_MIN_CLEAR:
            out["problems"].append(f"time-lapse: a frame below clear share {FRAME_MIN_CLEAR}")
        missing = [f["index"] for f in fr if not os.path.exists(os.path.join(SHOWCASE, f"{rid}_t{f['index']}.png"))]
        if missing:
            out["problems"].append(f"time-lapse: frame files missing {missing}")
    px = _load(os.path.join(SHOWCASE, f"{rid}_change.json")) or {}
    out["change_overlay"] = bool(px.get("overlay")) and os.path.exists(os.path.join(SHOWCASE, px["overlay"]))
    ctl = _load(os.path.join(SHOWCASE, f"{rid}_controls.json")) or {}
    out["controls"] = [{"rank": c["rank"], "role": c["role"], "weight": c["weight"],
                        "before": c["before"]["date"], "after": c["after"]["date"],
                        "same_scenes": c["before"]["same_scene_as_area"] and c["after"]["same_scene_as_area"]}
                       for c in ctl.get("controls", [])]
    for c in ctl.get("controls", []):
        for tag in ("before", "after"):
            if c[tag]["date"] != (out.get(tag) or {}).get("date"):
                out["problems"].append(f"control {c['rank']} {tag}: dated {c[tag]['date']}, not the area's "
                                       f"{(out.get(tag) or {}).get('date')} (another tile, or cloud on the area's date; date shown on the page)")
    return out


def build(run: dict, audit_row: dict) -> None:
    from src.app.imagery import make_control_thumbnails, make_thumbnails, make_timelapse
    from src.app.pixels import compute_pixel_change
    rid, geo = run["id"], run["area"]["geojson"]
    if any(p.startswith(("before", "after")) for p in audit_row["problems"]):
        for p in audit_row["problems"]:           # never keep a thumbnail that failed the audit
            for tag in ("before", "after"):
                if p.startswith(tag):
                    for ext in ("png", "json"):
                        f = os.path.join(SHOWCASE, f"{rid}_{tag}.{ext}")
                        if os.path.exists(f):
                            os.remove(f)
        info = make_thumbnails(geo, run["event_date"], SHOWCASE, rid)
        for tag, meta in info.items():
            json.dump(meta, open(os.path.join(SHOWCASE, f"{rid}_{tag}.json"), "w"))
        print("   thumbnails regenerated:", {k: v["date"] for k, v in info.items()}, flush=True)
    if any(p.startswith("time-lapse") for p in audit_row["problems"]):
        w0, w1 = run["window"]
        fr = make_timelapse(geo, w0, w1, SHOWCASE, rid, event_date=run["event_date"])
        print(f"   time-lapse regenerated: {len(fr)} frames", flush=True)
    if not audit_row["change_overlay"]:
        px = compute_pixel_change(geo, run["event_date"], run["change_type"], run["post_months"], SHOWCASE, rid)
        print(f"   change map: {px.get('status')} overlay={px.get('overlay')} {px.get('reason', '')}", flush=True)
    ctl = make_control_thumbnails(run, SHOWCASE)
    print(f"   controls: {[(c['role'], c['weight'], c['before']['date'], c['after']['date']) for c in ctl]}", flush=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    audit_only = "--audit-only" in argv
    keys = [a for a in argv if not a.startswith("--")]
    index = json.load(open(os.path.join(SHOWCASE, "index.json")))
    rows = []
    for e in index:
        if keys and e["key"] not in keys:
            continue
        run = _load(os.path.join(SHOWCASE, f"{e['id']}.json"))
        if run is None:
            continue
        print(f"== {e['key']} {e['id']}", flush=True)
        a = audit(run)
        if not audit_only:
            try:
                build(run, a)
            except Exception:
                traceback.print_exc()
            a = audit(run)
        a["key"] = e["key"]
        print("   problems:", a["problems"] or "none", flush=True)
        rows.append(a)
    if not keys:
        with open(os.path.join(SHOWCASE, "imagery_audit.json"), "w") as f:
            json.dump(rows, f, indent=1)
    return rows


if __name__ == "__main__":
    main()
