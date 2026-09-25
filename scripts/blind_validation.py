"""Run the Otherwise verdict on every item of a blind sample and tabulate the results.

    python -m scripts.blind_validation --sample showcase/blind/sample.json --parallel 3 --out showcase/blind/
    python -m scripts.blind_validation ... --ids ev-hansen-001 nl-hansen-001      # subset (smoke run)
    python -m scripts.blind_validation ... --summary-only                        # just rebuild the tables

Each item runs in its own worker process (multiprocessing, maxtasksperchild=1 so
memory is released) with APP_FETCH_WORKERS=8 and APP_CACHE_DIR=data/cache_blind
set before src.app is imported. Results are cached by run id under
<out>/runs/, so re-running only processes the items that have no result yet.
Every finished item appends one row to <out>/results.jsonl and rewrites
<out>/summary.json and docs/BLIND_VALIDATION.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
import traceback

ROW_FIELDS = ["id", "label", "source", "type", "expected", "status", "lead", "point", "lo", "hi",
              "placebo_p", "n_pre", "n_post", "n_donors", "mode", "seconds", "error"]
SIZE_BUCKETS = ["<50 ha", "50-150 ha", ">150 ha"]
CLIMATES = ["tropical", "temperate", "boreal", "dry"]
TIMEOUT_S = 25 * 60
RUN_ORDER_SEED = [None]          # set from --shuffle-seed, recorded in summary.json


# ----------------------------------------------------------------------------
# worker
# ----------------------------------------------------------------------------

def _worker(args: dict) -> dict:
    """Runs in a fresh process. Sets the app environment before importing src.app."""
    os.environ.setdefault("APP_FETCH_WORKERS", "8")
    os.environ.setdefault("APP_CACHE_DIR", "data/cache_blind")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    item, runs_dir = args["item"], args["runs_dir"]
    t0 = time.time()
    try:
        from src.app.run import run_verdict
        out = run_verdict(item["geojson"], item["event_date"], item["change_type"], int(item["post_months"]),
                          label=item["label"], progress=lambda s, d, t: None, save=True,
                          runs_dir=runs_dir, mode="auto")
        return {"id": item["id"], "run_id": out["id"], "seconds": round(time.time() - t0, 1), "error": None}
    except Exception as e:                                # noqa: BLE001
        return {"id": item["id"], "run_id": None, "seconds": round(time.time() - t0, 1),
                "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-2000:]}


def _proc_entry(args: dict, q) -> None:
    q.put(_worker(args))


def run_bounded(todo: list[dict], runs_dir: str, parallel: int, timeout: float, worker=None):
    """Yield (item, result) with at most `parallel` items running at once.

    Each item runs in its own process and its timeout is measured from the
    moment it STARTS. An item that overruns is terminated, so it neither keeps
    burning CPU nor finishes unrecorded. (The earlier pool submitted every item
    at once and timed each one from submission, so after one timeout period
    every item still queued was recorded as "timeout" without ever running.)"""
    ctx = mp.get_context("spawn")
    target = worker or _proc_entry
    global queue, running
    queue, running = list(todo), {}
    while queue or running:
        while queue and len(running) < parallel:
            it = queue.pop(0)
            q = ctx.Queue()
            pr = ctx.Process(target=target, args=({"item": it, "runs_dir": runs_dir}, q), daemon=True)
            pr.start()
            running[it["id"]] = (it, pr, q, time.time())
        time.sleep(0.2 if worker else 5)
        for iid in list(running):
            it, pr, q, t0 = running[iid]
            res = None
            try:
                res = q.get_nowait()
            except Exception:                          # noqa: BLE001  (queue.Empty)
                if not pr.is_alive():
                    res = {"id": iid, "run_id": None, "seconds": round(time.time() - t0, 1),
                           "error": f"worker exited with code {pr.exitcode} and no result"}
                elif time.time() - t0 > timeout:
                    pr.terminate()
                    res = {"id": iid, "run_id": None, "seconds": round(time.time() - t0, 1),
                           "error": f"timeout after {timeout:.0f} s (terminated)"}
            if res is None:
                continue
            pr.join(timeout=10)
            del running[iid]
            yield it, res


queue: list = []
running: dict = {}


def run_id_for(item: dict) -> str:
    """The cache key run_verdict will use (mirrors src.app.run.run_id without fetching)."""
    from src.app.run import run_id
    from src.app.verdict import SIGNALS
    ct = item["change_type"] if item["change_type"] in SIGNALS else "other"
    pm = int(min(max(int(item["post_months"]), 1), 18))
    return run_id(item["geojson"], item["event_date"], ct, pm)


# ----------------------------------------------------------------------------
# rows and summary
# ----------------------------------------------------------------------------

def row_from_result(item: dict, res: dict | None, run_json: dict | None, seconds: float | None,
                    error: str | None) -> dict:
    row = {k: None for k in ROW_FIELDS}
    row.update({"id": item["id"], "label": item["label"], "source": item["source"], "type": item["change_type"],
                "expected": item["expected"], "seconds": seconds, "error": error,
                "climate": item.get("climate"), "size_bucket": item.get("size_bucket"), "box_ha": item.get("box_ha"),
                "event_date": item["event_date"], "date_precision": item.get("date_precision"),
                "lon": item.get("lon"), "lat": item.get("lat")})
    if run_json is not None:
        v = run_json["verdict"]
        lead = v["lead_signal"]
        sig = run_json["signals"].get(lead, {})
        row.update({"status": v["status"], "lead": lead, "point": sig.get("point"), "lo": sig.get("lo"),
                    "hi": sig.get("hi"), "placebo_p": sig.get("placebo_p"), "n_pre": sig.get("n_pre"),
                    "n_post": sig.get("n_post"), "n_donors": sig.get("n_donors"), "mode": run_json.get("mode"),
                    "run_id": run_json["id"], "headline": v["headline"], "reasons": v.get("reasons"),
                    "escalation": run_json.get("escalation"), "area_ha": run_json["area"]["ha"],
                    "landcover": run_json["area"].get("landcover"),
                    "optical_status": run_json.get("evidence", {}).get("optical"),
                    "radar_status": run_json.get("evidence", {}).get("radar")})
        for k in ("point", "lo", "hi", "placebo_p"):
            if row[k] is not None:
                row[k] = round(float(row[k]), 4)
    elif error:
        row["status"] = "error"
    return row


def outcome(row: dict) -> str:
    """hit | miss | false_alarm | correct_null | cant_tell | error."""
    st, exp = row.get("status"), row.get("expected")
    if st in (None, "error"):
        return "error"
    if st == "CANT_TELL":
        return "cant_tell"
    if exp == "REAL":
        return "hit" if st == "REAL" else "miss"
    return "false_alarm" if st == "REAL" else "correct_null"


def _counts(rows: list[dict]) -> dict:
    ev = [r for r in rows if r["expected"] == "REAL"]
    nl = [r for r in rows if r["expected"] == "NOT_REAL"]
    oc = [outcome(r) for r in rows]
    ev_oc = [outcome(r) for r in ev]
    nl_oc = [outcome(r) for r in nl]
    ev_done = [o for o in ev_oc if o != "error"]
    nl_done = [o for o in nl_oc if o != "error"]

    def rate(k, pool):
        return round(pool.count(k) / len(pool), 3) if pool else None

    return {
        "n": len(rows), "n_events": len(ev), "n_nulls": len(nl), "errors": oc.count("error"),
        "events": {"n": len(ev_done), "hit": ev_oc.count("hit"), "miss": ev_oc.count("miss"),
                   "cant_tell": ev_oc.count("cant_tell"), "error": ev_oc.count("error"),
                   "detection_rate": rate("hit", ev_done), "miss_rate": rate("miss", ev_done),
                   "cant_tell_rate": rate("cant_tell", ev_done)},
        "nulls": {"n": len(nl_done), "false_alarm": nl_oc.count("false_alarm"), "correct": nl_oc.count("correct_null"),
                  "cant_tell": nl_oc.count("cant_tell"), "error": nl_oc.count("error"),
                  "false_alarm_rate": rate("false_alarm", nl_done), "correct_rate": rate("correct_null", nl_done),
                  "cant_tell_rate": rate("cant_tell", nl_done)},
    }


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:                                     # noqa: BLE001
        return None


def build_summary(sample: dict, rows: list[dict]) -> dict:
    by = {}
    for key, values in (("type", sorted({r["type"] for r in rows})),
                        ("source", sorted({r["source"] for r in rows})),
                        ("size_bucket", SIZE_BUCKETS), ("climate", CLIMATES)):
        by[key] = {v: _counts([r for r in rows if r.get(key) == v]) for v in values
                   if any(r.get(key) == v for r in rows)}
    by["date_precision"] = {v: _counts([r for r in rows if r.get("date_precision") == v])
                            for v in sorted({r.get("date_precision") or "unknown" for r in rows})}
    done = [r for r in rows if r.get("seconds") is not None]
    return {
        "seed": sample.get("seed"), "sample_generated": sample.get("generated"), "sample_n": sample.get("n_items"),
        "sample_git_commit": sample.get("git_commit"), "git_commit": git_commit(),
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "completed": len(rows), "pending": sample.get("n_items", 0) - len(rows),
        "median_seconds": (sorted(r["seconds"] for r in done)[len(done) // 2] if done else None),
        "overall": _counts(rows), "by": by,
        "run_order_seed": RUN_ORDER_SEED[0],
        "definitions": {"detection_rate": "REAL verdicts / finished event runs",
                        "miss_rate": "NOT_REAL verdicts / finished event runs",
                        "false_alarm_rate": "REAL verdicts / finished null runs",
                        "correct_rate": "NOT_REAL verdicts / finished null runs",
                        "cant_tell_rate": "CAN'T TELL verdicts / finished runs of that kind",
                        "error": "the run raised or timed out; excluded from the rates"},
    }


# ----------------------------------------------------------------------------
# docs/BLIND_VALIDATION.md
# ----------------------------------------------------------------------------

def _pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def _ci(k, n) -> str:
    """"k of n (rate, 95% CI lo-hi)", or "not measured" when n is 0.

    Wilson score interval (`src.app.review.wilson`): these denominators are
    small and the rates sit near 0 and 1, where the normal approximation
    leaves the unit interval."""
    from src.app.review import wilson
    if not n:
        return "not measured (no finished runs of this kind)"
    ci = wilson(k, n)
    return f"{k} of {n} = {100 * k / n:.1f}% (95% CI {100 * ci[0]:.1f}-{100 * ci[1]:.1f}%)"


def _gap_note(o: dict) -> str:
    """Say plainly, in the doc, when a rate has no runs behind it yet."""
    if o["nulls"]["n"] == 0 and o["events"]["n"] > 0:
        return (" No control (no-change) item has finished yet, so the false-alarm rate "
                "below is not measured. Until it is, the detection rate on its own says "
                "nothing about how often the tool cries wolf, and should not be quoted alone.")
    if o["events"]["n"] == 0:
        return " No event item has finished yet, so the detection rate is not measured."
    return ""


def _table(title: str, groups: dict) -> str:
    lines = [f"**{title}**", "",
             "| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |",
             "|---|---|---|---|---|---|---|---|---|"]
    for g, c in groups.items():
        e, n = c["events"], c["nulls"]
        lines.append(f"| {g} | {e['n']} | {e['hit']} ({_pct(e['detection_rate'])}) | {e['miss']} ({_pct(e['miss_rate'])}) | "
                     f"{e['cant_tell']} ({_pct(e['cant_tell_rate'])}) | {n['n']} | {n['false_alarm']} ({_pct(n['false_alarm_rate'])}) | "
                     f"{n['correct']} ({_pct(n['correct_rate'])}) | {n['cant_tell']} ({_pct(n['cant_tell_rate'])}) |")
    return "\n".join(lines) + "\n"


def write_doc(path: str, sample: dict, summary: dict, rows: list[dict], sample_path: str, out_dir: str,
              parallel: int) -> None:
    crit = sample.get("criteria", {})
    h = sample.get("hansen", {})
    st = sample.get("stats", {})
    mt = st.get("mtbs", {})
    o = summary["overall"]
    n_items = sample.get("n_items", 0)
    kinds = {}
    for it in sample.get("items", []):
        kinds[(it["source"], it["kind"])] = kinds.get((it["source"], it["kind"]), 0) + 1
    kinds_txt = ", ".join(f"{v} {s} {k}s" for (s, k), v in sorted(kinds.items()))
    errors = [r for r in rows if outcome(r) == "error"]

    md = f"""# Blind validation of the Otherwise verdict

*Generated {summary['generated']} by `scripts/blind_validation.py` at commit `{summary['git_commit']}`.
This file is rewritten after every finished item; the numbers below cover
{summary['completed']} of {n_items} sampled items ({summary['pending']} still pending).*

## Why a blind sample

The known-answer sites in `SITES.md` were chosen by hand, which is fine for
checking that the method works at all but says nothing about how it behaves
on events nobody picked. This track draws events and no-change areas at
random from public ground-truth datasets with a fixed seed, runs the
unchanged verdict pipeline on each, and reports the hit rate, the miss rate,
the false-alarm rate and the "can't tell" rate. Nothing is filtered after the
fact; every drawn item is listed, misses and errors included.

## Ground truth and sampling

Seed **{sample.get('seed')}**, sample drawn {sample.get('generated')} at commit
`{summary.get('sample_git_commit')}`: {kinds_txt} ({n_items} items). The draw is
scripted and seeded end to end; no item was hand-picked, kept or dropped after
being seen. Re-running `scripts/blind_sample.py` with the same seed against the
same fixed dataset releases reproduces it.

**Hansen Global Forest Change {h.get('version', '')}** (Hansen et al. 2013, updated; 30 m
`lossyear` and `treecover2000` tiles read as windows from Google Cloud Storage).
Tiles used: {', '.join(h.get('tiles_open', []))}{(' (failed to open: ' + ', '.join(h['tiles_failed']) + ')') if h.get('tiles_failed') else ''}.
Climate class is a fixed per-tile mapping: {', '.join(f'{t} = {c}' for t, c in h.get('climate_by_tile', {}).items())}.

- *Events (clearing, expected REAL).* Each attempt draws a tile, a band of
  {crit.get('window_px')} rows and a loss year uniformly (years {h.get('years')}). The
  {crit.get('window_px')} x {crit.get('window_px')} pixel window is drawn uniformly among the windows of
  that band holding at least {crit.get('component_ha', ['?'])[0]} ha of that year's loss. Connected
  components (8-connectivity) of `lossyear == year` with `treecover2000 >= {crit.get('treecover_event')}`
  are labelled; those of {crit.get('component_ha', ['?', '?'])[0]}-{crit.get('component_ha', ['?', '?'])[1]} ha not touching the
  window edge are candidates and one is picked uniformly. The polygon is the
  component's bounding box shrunk by one pixel per side, cropped symmetrically
  around the component centroid to at most {crit.get('max_box_ha')} ha, and kept only if at
  least {int(100 * crit.get('min_loss_fraction', 0))}% of its pixels belong to the component. Attempts that
  produce nothing are discarded; the sample file records every accepted draw
  with its tile, band, window, component size and loss fraction.
- *Year-only dates.* Hansen gives the loss **year**, not the day. The event
  date passed to the tool is `{{year}}-01-01` with `post_months = {crit.get('post_months_clearing')}`, so the
  post-event window spans the whole loss year and the first half of the next.
  A clearing late in the year therefore contributes only a few post-event
  months of signal and dilutes the average effect; this is a known handicap
  of the label, not of the site, and is reported as such.
- *Nulls (expected NOT REAL).* Same tiles, same band design. A box whose size
  is drawn from the accepted events' box sizes (in metres) is placed uniformly
  where `treecover2000 >= {crit.get('treecover_null')}` over the whole box and `lossyear == 0`
  over the box plus a {crit.get('null_buffer_m')} m buffer (no mapped loss 2001-2023). The
  fake event date is drawn from the events' year distribution.

**MTBS burned-area perimeters** (USGS/USFS Monitoring Trends in Burn Severity,
`mtbs_perimeter_data.zip`): {'used' if mt.get('used') else 'not used'}{(' (' + str(mt.get('error')) + ')') if mt.get('error') else ''}.
{'Events are wildfires (Incid_Type = Wildfire) with ignition date between ' + ' and '.join(crit.get('mtbs', {}).get('dates', ['?', '?'])) + ' and ' + '-'.join(str(x) for x in crit.get('mtbs', {}).get('acres', ['?', '?'])) + ' acres, drawn uniformly (' + str(mt.get('eligible')) + ' eligible). The polygon is a box centred on the largest part of the perimeter shrunk by ' + str(crit.get('mtbs', {}).get('shrink_m')) + ' m, capped at ' + str(crit.get('max_box_ha')) + ' ha and shrunk further until at least ' + str(int(100 * crit.get('mtbs', {}).get('min_inside', 0))) + '% of it lies inside the perimeter; the event date is the MTBS ignition date (day precision) with post_months = ' + str(crit.get('mtbs', {}).get('post_months_burn')) + '. Nulls are boxes of the same sizes placed 10-120 km from a sampled fire, at least ' + str(crit.get('mtbs', {}).get('null_min_dist_m')) + ' m from every MTBS perimeter of any year, with at least 80% of pixels tree-covered (Hansen treecover2000 >= 30) and no Hansen loss in the box or its 300 m buffer. Climate: latitude >= 55 N is boreal (Alaska), longitude 118 W-100 W is dry (interior West), else temperate.' if mt.get('used') else ''}

**Sources considered and not used**, so a reader knows what is missing rather
than assuming it was tried:

- *Copernicus EMS rapid mapping* (floods). Not used: the delineation products
  are per-activation archives meant for manual download, with no stable
  programmatic index that a seeded sampler could draw from mechanically. One
  EMS flood (Sindh 2022) is in the hand-picked known-answer set instead.
- *EFFIS / GWIS burnt areas* (Europe). Not used: the download endpoint
  redirected to an interactive request form and the WFS endpoint timed out from
  this environment on 2026-09-18, so nothing could be scripted against it.
  MTBS covers burns instead, for the USA only.
- *JRC Global Surface Water* (water change and stable-water/stable-land
  controls). Reachable -- the public bucket lists
  `downloads2021/change/change_<lon>_<lat>v1_4_2021.tif` -- but not used: the
  change and transitions layers describe 1984-2021 as a whole and carry no
  event year, so they cannot give a dated event the tool can be asked about.
  The yearly-classification product could, and is the obvious next source to
  add; it was not implemented here.

Water and flood events are therefore **absent from this blind sample**, and the
numbers below say nothing about how the tool behaves on them.

## Commands

```
python -m scripts.blind_sample --seed {sample.get('seed')} --n-events 60 --n-null 60 --out {sample_path}{' --mtbs <path>/mtbs_perimeter_data.zip' if mt.get('used') else ''}
python -m scripts.blind_validation --sample {sample_path} --parallel {parallel} --out {out_dir}
```

The outstanding items are run in a seeded random order (`--shuffle-seed`,
recorded as `run_order_seed` in `summary.json`), so a run stopped part-way
leaves a random subsample of the draw rather than, say, every event and no
control. **The verdicts are tied to the commit above**: another track was
changing the fetch and estimator path in parallel, so re-running at a later
commit can legitimately give different numbers.

Each item calls `run_verdict(geojson, event_date, change_type, post_months, mode="auto")`
unchanged, in its own process with `APP_FETCH_WORKERS=8` and `APP_CACHE_DIR=data/cache_blind`,
with a 25-minute timeout. Results are cached by run id in `{out_dir}runs/`, so
re-running the command only processes items without a result. The second
command with `--summary-only` rebuilds the tables from `results.jsonl`.

## What the outcomes mean

| Item kind | REAL | NOT REAL | CAN'T TELL |
|---|---|---|---|
| Event (documented loss/burn) | hit (detected) | miss | can't tell |
| Null (no documented change) | false alarm | correct | can't tell |

Rates are over finished runs of that kind; runs that raised or timed out are
counted separately as errors. "Can't tell" is not a miss: the tool declined
to answer, and the reason is stored with every run.

## Results so far ({summary['completed']} of {n_items} items; median run {summary['median_seconds']} s)

Tool alone, over finished runs only, with 95% Wilson intervals:

| Rate | Value |
|---|---|
| Detection (REAL on an event) | {_ci(o['events']['hit'], o['events']['n'])} |
| Miss (NOT REAL on an event) | {_ci(o['events']['miss'], o['events']['n'])} |
| Can't tell on an event | {_ci(o['events']['cant_tell'], o['events']['n'])} |
| False alarm (REAL on a control) | {_ci(o['nulls']['false_alarm'], o['nulls']['n'])} |
| Correct on a control | {_ci(o['nulls']['correct'], o['nulls']['n'])} |
| Can't tell on a control | {_ci(o['nulls']['cant_tell'], o['nulls']['n'])} |

{o['errors']} of the items attempted so far produced no verdict (raised or timed
out); they are excluded from every rate above and listed below. A rate shown as
"not measured" has no finished runs behind it and no number is invented for it.

So far {o['n_events']} event items and {o['n_nulls']} control items have been
attempted, of which {o['events']['n']} and {o['nulls']['n']} finished.{_gap_note(o)}

{_table('By change type', summary['by']['type'])}
{_table('By source and date precision', {**{f'{k} (source)': v for k, v in summary['by']['source'].items()}, **{f'{k} (date precision)': v for k, v in summary['by']['date_precision'].items()}})}
{_table('By polygon size', summary['by']['size_bucket'])}
{_table('By climate', summary['by']['climate'])}
"""
    if errors:
        md += "\n**Errors**\n\n| Item | Error |\n|---|---|\n"
        for r in errors:
            md += f"| {r['id']} | {(r.get('error') or '')[:160]} |\n"
    md += "\n## Every item\n\n| Item | Type | Expected | Verdict | Lead | Effect (90% interval) | Placebo p | Pre/post bins | Donors | Size | Climate | Date | Seconds |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    for r in sorted(rows, key=lambda r: r["id"]):
        eff = "-" if r.get("point") is None else f"{r['point']:+.3f} ({r['lo']:+.3f} to {r['hi']:+.3f})"
        pp = "-" if r.get("placebo_p") is None else f"{r['placebo_p']:.2f}"
        md += (f"| {r['id']} | {r['type']} | {r['expected']} | {r.get('status')} | {r.get('lead') or '-'} | {eff} | {pp} | "
               f"{r.get('n_pre') or '-'}/{r.get('n_post') or '-'} | {r.get('n_donors') or '-'} | {r.get('box_ha')} ha | "
               f"{r.get('climate')} | {r.get('event_date')} | {r.get('seconds')} |\n")
    md += ("\n*Sources: Hansen, M. C. et al. (2013) High-Resolution Global Maps of 21st-Century Forest Cover Change, "
           "Science 342, 850-853; data GFC-2023 v1.11. MTBS: Monitoring Trends in Burn Severity, USGS/USFS, "
           "burned area boundaries dataset.*\n")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(md)


# ----------------------------------------------------------------------------
# orchestration
# ----------------------------------------------------------------------------

def load_rows(path: str) -> dict[str, dict]:
    rows = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line:
                r = json.loads(line)
                rows[r["id"]] = r                        # last row per id wins
    return rows


def refresh(sample: dict, rows: dict[str, dict], out_dir: str, sample_path: str, parallel: int, doc_path: str):
    """Rebuild summary.json and the doc. Rows on disk are merged in first, so a
    second runner working on other items does not erase them from the tables."""
    merged = load_rows(os.path.join(out_dir, "results.jsonl"))
    merged.update(rows)
    lst = list(merged.values())
    summary = build_summary(sample, lst)
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    write_doc(doc_path, sample, summary, lst, sample_path, out_dir, parallel)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sample", required=True)
    ap.add_argument("--out", default="showcase/blind/")
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--ids", nargs="*", default=None, help="only these item ids")
    ap.add_argument("--limit", type=int, default=None, help="stop after this many new items")
    ap.add_argument("--shuffle-seed", type=int, default=None,
                    help="run the outstanding items in this seeded random order. Runs take minutes "
                         "each, so a run is normally stopped before the sample is exhausted; a "
                         "seeded shuffle makes the finished subset a random subsample of the draw "
                         "(rather than all events, or all of one tile) so the rates stay unbiased.")
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--timeout", type=int, default=TIMEOUT_S)
    ap.add_argument("--doc", default="docs/BLIND_VALIDATION.md")
    a = ap.parse_args(argv)

    RUN_ORDER_SEED[0] = a.shuffle_seed
    out_dir = a.out if a.out.endswith("/") else a.out + "/"
    runs_dir = os.path.join(out_dir, "runs")
    os.makedirs(runs_dir, exist_ok=True)
    sample = json.load(open(a.sample))
    items = sample["items"]
    if a.ids:
        items = [it for it in items if it["id"] in set(a.ids)]
    results_path = os.path.join(out_dir, "results.jsonl")
    rows = load_rows(results_path)
    log = lambda s: print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {s}", flush=True)   # noqa: E731

    # items that already have a cached run json but no row (e.g. a previous crash): adopt them
    for it in items:
        if it["id"] in rows and rows[it["id"]].get("status") not in (None, "error"):
            continue
        p = os.path.join(runs_dir, run_id_for(it) + ".json")
        if os.path.exists(p):
            rj = json.load(open(p))
            rows[it["id"]] = row_from_result(it, None, rj, rj.get("timing", {}).get("run_s"), None)
            with open(results_path, "a") as f:
                f.write(json.dumps(rows[it["id"]]) + "\n")

    if a.summary_only:
        s = refresh(sample, rows, out_dir, a.sample, a.parallel, a.doc)
        log(json.dumps(s["overall"]))
        return

    todo = [it for it in items if it["id"] not in rows or rows[it["id"]].get("status") in (None, "error")]
    if a.shuffle_seed is not None:
        import random as _random
        _random.Random(a.shuffle_seed).shuffle(todo)
    if a.limit:
        todo = todo[:a.limit]
    log(f"{len(items)} items in scope, {len(rows)} rows already, {len(todo)} to run, parallel={a.parallel}")
    refresh(sample, rows, out_dir, a.sample, a.parallel, a.doc)
    if not todo:
        return

    t_all = time.time()

    def record(it, res):
        rj = None
        if res.get("run_id"):
            p = os.path.join(runs_dir, res["run_id"] + ".json")
            rj = json.load(open(p)) if os.path.exists(p) else None
        row = row_from_result(it, res, rj, res["seconds"], res.get("error"))
        rows[it["id"]] = row
        with open(results_path, "a") as f:
            f.write(json.dumps(row) + "\n")
        s = refresh(sample, rows, out_dir, a.sample, a.parallel, a.doc)
        o = s["overall"]
        eff = "" if row.get("point") is None else f" {row['lead']} {row['point']:+.3f} [{row['lo']:+.3f},{row['hi']:+.3f}] p={row['placebo_p']}"
        log(f"{it['id']} {row['expected']:8s} -> {row.get('status')}{eff} {row['seconds']}s"
            f"{(' ERROR ' + row['error'][:120]) if row.get('error') else ''}"
            f" | events {o['events']['hit']}/{o['events']['n']} hit, nulls {o['nulls']['false_alarm']}/{o['nulls']['n']} FA,"
            f" {len(queue) + len(running)} pending, {(time.time() - t_all) / 60:.0f} min")

    for it, res in run_bounded(todo, runs_dir, a.parallel, a.timeout):
        record(it, res)
    log("done")


if __name__ == "__main__":
    main()
