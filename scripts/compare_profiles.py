"""Compare the memory-bounded "live" profile against "full" on the known-answer sites.

Full mode reads the drawn area and every control cell from one window at 10 m.
Live mode reads the area alone at 10 m and its controls separately at 40 m, with
the scene list pre-filtered. That is a real methodological difference -- it gives
up co-observation between treated and control -- so the question is not whether
live mode is cheaper (it is, by construction) but what it costs in accuracy.

The full arm is taken from the committed `showcase/*.json`, which are full-mode
runs; re-running them here would cost hours and change nothing. The live arm is
run now, site by site, and checkpointed after each one so an interrupted run
loses nothing.

    python -m scripts.compare_profiles                 # all sites
    python -m scripts.compare_profiles --only grunheide austin
    python -m scripts.compare_profiles --table         # rebuild the table from disk

Writes showcase/profile_comparison.json (rows) and prints a Markdown table.
Every number in the table comes from a run on disk; sites that did not run are
printed as "not run", never estimated.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import traceback

SHOWCASE = "showcase"
OUT = os.path.join(SHOWCASE, "profile_comparison.json")


def _index() -> list[dict]:
    with open(os.path.join(SHOWCASE, "index.json")) as f:
        return json.load(f)


def _load(rid: str) -> dict | None:
    p = os.path.join(SHOWCASE, f"{rid}.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def _lead(run: dict) -> tuple[str | None, dict]:
    lead = (run.get("verdict") or {}).get("lead_signal")
    return lead, ((run.get("signals") or {}).get(lead) or {})


def _row(key: str, full: dict, live: dict | None, err: str | None, seconds: float | None) -> dict:
    fl, fs = _lead(full)
    row = {
        "key": key, "label": full.get("label", ""),
        "expected": None,
        "full": {
            "verdict": full["verdict"]["status"], "mode": full.get("mode"), "lead": fl,
            "point": fs.get("point"), "lo": fs.get("lo"), "hi": fs.get("hi"),
            "width": (None if fs.get("lo") is None or fs.get("hi") is None
                      else round(float(fs["hi"]) - float(fs["lo"]), 4)),
            "placebo_p": fs.get("placebo_p"), "n_donors": fs.get("n_donors"),
            "n_pre": fs.get("n_pre"), "n_post": fs.get("n_post"),
        },
        "live": None, "error": err, "live_seconds": seconds,
    }
    if live is not None:
        ll, ls = _lead(live)
        row["live"] = {
            "verdict": live["verdict"]["status"], "mode": live.get("mode"), "lead": ll,
            "point": ls.get("point"), "lo": ls.get("lo"), "hi": ls.get("hi"),
            "width": (None if ls.get("lo") is None or ls.get("hi") is None
                      else round(float(ls["hi"]) - float(ls["lo"]), 4)),
            "placebo_p": ls.get("placebo_p"), "n_donors": ls.get("n_donors"),
            "n_pre": ls.get("n_pre"), "n_post": ls.get("n_post"),
            "donor_res_m": (live.get("data_summary") or {}).get("donor_res_m"),
            "scenes_read": (live.get("data_summary") or {}).get("s2_scenes_read"),
            "scenes_covering": (live.get("data_summary") or {}).get("s2_scenes_covering"),
            "peak_note": "peak RSS is measured by scripts/memtest.py, not here",
        }
    return row


def _fmt(v, nd=3):
    return "—" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def table(rows: list[dict]) -> str:
    out = ["| Site | Expected | Full verdict | Live verdict | Agree | Full effect | Live effect | "
           "Full 90% width | Live 90% width | Full placebo p | Live placebo p | Full donors | Live donors |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        f, l = r["full"], r["live"]
        if l is None:
            out.append(f"| {r['key']} | {r.get('expected') or '—'} | {f['verdict']} | "
                       f"not run{' (' + r['error'][:40] + ')' if r.get('error') else ''} "
                       f"| — | {_fmt(f['point'])} | — | {_fmt(f['width'])} | — | "
                       f"{_fmt(f['placebo_p'], 3)} | — | {_fmt(f['n_donors'], 0)} | — |")
            continue
        agree = "yes" if f["verdict"] == l["verdict"] else "**no**"
        out.append(f"| {r['key']} | {r.get('expected') or '—'} | {f['verdict']} | {l['verdict']} | {agree} | "
                   f"{_fmt(f['point'])} | {_fmt(l['point'])} | {_fmt(f['width'])} | {_fmt(l['width'])} | "
                   f"{_fmt(f['placebo_p'], 3)} | {_fmt(l['placebo_p'], 3)} | "
                   f"{_fmt(f['n_donors'], 0)} | {_fmt(l['n_donors'], 0)} |")
    done = [r for r in rows if r["live"]]
    if done:
        agree = sum(1 for r in done if r["full"]["verdict"] == r["live"]["verdict"])
        out += ["", f"**{agree} of {len(done)} sites agree** on the verdict "
                    f"({len(rows) - len(done)} of {len(rows)} not run)."]
        widths = [(r["full"]["width"], r["live"]["width"]) for r in done
                  if r["full"]["width"] and r["live"]["width"]]
        if widths:
            wider = sum(1 for a, b in widths if b > a)
            ratio = sum(b / a for a, b in widths) / len(widths)
            out.append(f"Live intervals are wider on {wider} of {len(widths)} sites; "
                       f"mean live/full width ratio {ratio:.2f}.")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None, help="site keys to run")
    ap.add_argument("--table", action="store_true", help="rebuild the table from disk, run nothing")
    ap.add_argument("--runs-dir", default="data/runs/live_compare")
    a = ap.parse_args()

    entries = _index()
    prev = {}
    if os.path.exists(OUT):
        with open(OUT) as f:
            prev = {r["key"]: r for r in json.load(f).get("rows", [])}

    rows = []
    for e in entries:
        key = e["key"]
        full = _load(e["id"])
        if full is None:
            continue
        if a.table or (a.only and key not in a.only):
            r = prev.get(key) or _row(key, full, None, None, None)
            r["expected"] = e.get("expected")
            rows.append(r)
            continue

        from src.app.run import run_verdict
        os.makedirs(a.runs_dir, exist_ok=True)
        print(f"--- {key}: live mode", flush=True)
        t0 = time.time()
        live, err = None, None
        try:
            # Hold the control geometry constant and vary only the profile. With
            # mode="auto" the live arm could escalate to wide while the full arm
            # was ring, and the comparison would then be measuring mode and
            # profile together. Rhodes' full run is wide, so its live arm is wide
            # too, with the same radii.
            mode = full.get("mode") or "ring"
            ctrl = full.get("controls") or {}
            live = run_verdict(full["area"]["geojson"], full["event_date"], full["change_type"],
                               full["post_months"], label=full.get("label", ""), save=True,
                               runs_dir=a.runs_dir, mode=mode, profile="live",
                               inner_m=ctrl.get("inner_m") if mode == "wide" else None,
                               outer_m=ctrl.get("outer_m") if mode == "wide" else None)
        except Exception as ex:
            err = f"{type(ex).__name__}: {ex}"
            traceback.print_exc()
        r = _row(key, full, live, err, round(time.time() - t0, 1))
        r["expected"] = e.get("expected")
        rows.append(r)
        # checkpoint after every site
        merged = {**prev, **{x["key"]: x for x in rows}}
        with open(OUT, "w") as f:
            json.dump({"rows": [merged[k] for k in merged], "generated": time.time()}, f, indent=1)
        print(f"    {key}: mode={full.get('mode') or 'ring'} full={r['full']['verdict']} live="
              f"{r['live']['verdict'] if r['live'] else 'ERROR'} ({r['live_seconds']}s)", flush=True)

    merged = {**prev, **{x["key"]: x for x in rows}}
    ordered = [merged[e["key"]] for e in entries if e["key"] in merged]
    with open(OUT, "w") as f:
        json.dump({"rows": ordered, "generated": time.time()}, f, indent=1)
    print()
    print(table(ordered))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
