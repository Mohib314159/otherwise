"""FastAPI backend: live runs as background jobs, results as permalinks, showcase list.

    uvicorn src.app.server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time
import traceback
import uuid
from collections import OrderedDict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .geometry import PolygonError, validate_polygon
from .report import render_report, fmt_p, fmt_signal, interval_str as report_interval
from .run import RUNS_DIR, run_id, run_verdict
from .verdict import SIGNALS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEB_DIR = os.path.join(ROOT, "web")
SHOWCASE_DIR = os.path.join(ROOT, "showcase")
MAX_LIVE_JOBS = int(os.environ.get("APP_MAX_LIVE_JOBS", "1"))
LIVE_RUNS_ENABLED = os.environ.get("APP_LIVE_RUNS", "1") == "1"

app = FastAPI(title="Otherwise", docs_url=None, redoc_url=None)

_jobs: "OrderedDict[str, dict]" = OrderedDict()
_lock = threading.Lock()
_sem = threading.Semaphore(MAX_LIVE_JOBS)


class RunRequest(BaseModel):
    geojson: dict
    event_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    change_type: str = "other"
    post_months: int = 12
    label: str = ""


def _find_run(rid: str) -> str | None:
    for d in (RUNS_DIR, SHOWCASE_DIR):
        p = os.path.join(d, f"{rid}.json")
        if os.path.exists(p):
            return p
    return None


def _load_run(rid: str) -> dict:
    p = _find_run(rid)
    if not p:
        raise HTTPException(404, "No such run")
    with open(p) as f:
        out = json.load(f)
    out["imagery"] = {}
    for d in (RUNS_DIR, SHOWCASE_DIR):
        cj = os.path.join(d, f"{rid}_change.json")
        if os.path.exists(cj) and os.path.exists(os.path.join(d, f"{rid}_change.png")):
            try:
                px = json.load(open(cj))
                px["map"] = f"/api/runs/{rid}/change.png"
                out["pixels"] = px
            except Exception:
                pass
            break
    for tag in ("before", "after"):
        for d in (RUNS_DIR, SHOWCASE_DIR):
            png = os.path.join(d, f"{rid}_{tag}.png")
            meta = os.path.join(d, f"{rid}_{tag}.json")
            if os.path.exists(png):
                info = json.load(open(meta)) if os.path.exists(meta) else {}
                out["imagery"][tag] = {"url": f"/api/runs/{rid}/{tag}.png", **{k: v for k, v in info.items() if k != "file"}}
                break
    return out


def _worker(job_id: str, req: RunRequest):
    job = _jobs[job_id]
    with _sem:
        job.update(status="running", stage="starting", done=0, total=1, started=time.time())

        def progress(stage, done, total):
            job.update(stage=stage, done=done, total=total)

        try:
            out = run_verdict(req.geojson, req.event_date, req.change_type, req.post_months,
                              label=req.label[:120], progress=progress)
            try:
                from .imagery import make_thumbnails
                progress("imagery", 0, 1)
                info = make_thumbnails(req.geojson, req.event_date, RUNS_DIR, out["id"])
                for tag, meta in info.items():
                    with open(os.path.join(RUNS_DIR, f"{out['id']}_{tag}.json"), "w") as f:
                        json.dump(meta, f)
            except Exception:
                traceback.print_exc()
            job.update(status="done", run_id=out["id"], stage="done", done=1, total=1)
        except Exception as e:
            traceback.print_exc()
            job.update(status="error", error=str(e)[:300], stage="error")


@app.post("/api/run")
def submit(req: RunRequest):
    if req.change_type not in SIGNALS:
        raise HTTPException(400, "Unknown change type")
    try:
        validate_polygon(req.geojson)
    except PolygonError as e:
        raise HTTPException(400, str(e))
    rid = run_id(req.geojson, req.event_date, req.change_type, int(min(max(req.post_months, 1), 18)))
    if _find_run(rid):
        return {"run_id": rid, "done": True}
    if not LIVE_RUNS_ENABLED:
        raise HTTPException(503, "Live runs are switched off on this deployment; the showcase examples still work.")
    with _lock:
        for jid, j in _jobs.items():
            if j.get("rid") == rid and j["status"] in ("queued", "running"):
                return {"job_id": jid, "run_id": rid, "done": False}
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {"status": "queued", "stage": "queued", "done": 0, "total": 1,
                         "rid": rid, "created": time.time()}
        while len(_jobs) > 200:
            _jobs.popitem(last=False)
    threading.Thread(target=_worker, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id, "run_id": rid, "done": False}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, "No such job")
    ahead = sum(1 for k, o in _jobs.items() if o["status"] == "queued" and o["created"] < j["created"])
    return {**{k: v for k, v in j.items() if k not in ("rid",)}, "queue_position": ahead if j["status"] == "queued" else 0}


@app.get("/api/runs/{rid}")
def get_run(rid: str):
    return _load_run(rid)


@app.get("/api/runs/{rid}/frames")
def get_frames(rid: str):
    for d in (RUNS_DIR, SHOWCASE_DIR):
        p = os.path.join(d, f"{rid}_frames.json")
        if os.path.exists(p):
            return json.load(open(p))
    return []


@app.get("/api/runs/{rid}/{tag}.png")
def get_thumb(rid: str, tag: str):
    import re as _re
    if tag not in ("before", "after", "change") and not _re.fullmatch(r"t\d{1,2}", tag):
        raise HTTPException(404)
    for d in (RUNS_DIR, SHOWCASE_DIR):
        p = os.path.join(d, f"{rid}_{tag}.png")
        if os.path.exists(p):
            return FileResponse(p, media_type="image/png")
    raise HTTPException(404)


def _showcase_index() -> list[dict]:
    p = os.path.join(SHOWCASE_DIR, "index.json")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return json.load(f)


@app.get("/api/showcase")
def showcase():
    out = []
    for entry in _showcase_index():
        p = _find_run(entry["id"])
        if not p:
            continue
        r = json.load(open(p))
        out.append({"id": r["id"], "label": entry.get("label") or r["label"], "blurb": entry.get("blurb", ""),
                    "status": r["verdict"]["status"], "headline": r["verdict"]["headline"],
                    "change_type": r["change_type"], "event_date": r["event_date"],
                    "area": r["area"], "thumb": f"/api/runs/{r['id']}/after.png"
                    if os.path.exists(os.path.join(SHOWCASE_DIR, f"{r['id']}_after.png")) else None,
                    "expected": entry.get("expected"), "source": entry.get("source")})
    return out


@app.get("/api/track-record")
def track_record():
    p = os.path.join(SHOWCASE_DIR, "track_record.json")
    if not os.path.exists(p):
        return {"runs": [], "summary": None}
    return json.load(open(p))


@app.get("/api/health")
def health():
    return {"ok": True, "live_runs": LIVE_RUNS_ENABLED}


# ---- pages -----------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/v/{rid}")
def verdict_page(rid: str):
    return FileResponse(os.path.join(WEB_DIR, "verdict.html"))


@app.get("/track-record")
def track_page():
    return FileResponse(os.path.join(WEB_DIR, "track.html"))


# ---- reports, downloads, batch runs ----------------------------------------

_batches: "dict[str, dict]" = {}
MAX_BATCH_FEATURES = 25


def _run_json(rid: str) -> dict | None:
    p = _find_run(rid)
    if not p:
        return None
    with open(p) as f:
        return json.load(f)


@app.get("/api/runs/{rid}/report.md")
def run_report(rid: str):
    run = _run_json(rid)
    if run is None:
        raise HTTPException(404, "No such run")
    md = render_report(run)
    return Response(content=md, media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="otherwise-{rid}.md"'})


@app.get("/api/runs/{rid}/run.json")
def run_json_download(rid: str):
    p = _find_run(rid)
    if not p:
        raise HTTPException(404, "No such run")
    return FileResponse(p, media_type="application/json", filename=f"otherwise-{rid}.json")


class BatchRequest(BaseModel):
    features: list[dict]
    default_change_type: str = "other"
    default_post_months: int = 12
    default_event_date: str | None = None


def _batch_item_status(item: dict) -> dict:
    """A batch item plus its current status, computed live (never stored)."""
    it = dict(item)
    if it.get("error"):
        it["status"] = "error"
        return it
    if it.get("done") or (it.get("run_id") and _find_run(it["run_id"])):
        it["status"], it["done"] = "done", True
        return it
    job = _jobs.get(it.get("job_id")) if it.get("job_id") else None
    if job:
        it["status"] = job.get("status", "queued")
        it["stage"] = job.get("stage")
        if it["status"] == "done":
            it["done"] = True
    else:
        it["status"] = "unknown"
    return it


@app.post("/api/batch")
def submit_batch(req: BatchRequest):
    if len(req.features) > MAX_BATCH_FEATURES:
        raise HTTPException(413, f"At most {MAX_BATCH_FEATURES} features per batch.")
    items = []
    for i, feat in enumerate(req.features):
        props = (feat.get("properties") or {}) if isinstance(feat, dict) else {}
        label = str(props.get("label", "") or "")[:120]
        item = {"index": i, "label": label, "run_id": None, "job_id": None, "done": False, "error": None}
        try:
            event_date = props.get("event_date") or req.default_event_date
            if not event_date:
                raise ValueError("event_date is required, per feature or as default_event_date")
            change_type = props.get("change_type") or req.default_change_type
            post_months = props.get("post_months", req.default_post_months)
            run_req = RunRequest(geojson=feat, event_date=str(event_date), change_type=str(change_type),
                                 post_months=int(post_months), label=label)
            result = submit(run_req)
            item["run_id"] = result.get("run_id")
            item["job_id"] = result.get("job_id")
            item["done"] = bool(result.get("done", False))
        except HTTPException as e:
            item["error"] = str(e.detail)
        except (ValidationError, PolygonError, ValueError) as e:
            item["error"] = str(e)
        except Exception as e:
            item["error"] = str(e)[:300]
        items.append(item)
    batch_id = uuid.uuid4().hex[:12]
    with _lock:
        _batches[batch_id] = {"items": items, "created": time.time()}
    return {"batch_id": batch_id, "items": items}


@app.get("/api/batch/{batch_id}")
def batch_status(batch_id: str):
    b = _batches.get(batch_id)
    if not b:
        raise HTTPException(404, "No such batch")
    return {"batch_id": batch_id, "items": [_batch_item_status(it) for it in b["items"]]}


@app.get("/api/batch/{batch_id}/report.md")
def batch_report(batch_id: str):
    b = _batches.get(batch_id)
    if not b:
        raise HTTPException(404, "No such batch")
    items = [_batch_item_status(it) for it in b["items"]]
    lines = ["# Otherwise — batch report", "",
             f"Batch `{batch_id}`, {len(items)} feature(s).", "",
             "| Label | Verdict | Lead signal | Effect | 90% interval | Placebo p | Link |",
             "|---|---|---|---|---|---|---|"]
    full_reports = []
    for it in items:
        label = it.get("label") or f"Feature {it['index']}"
        if it.get("error"):
            lines.append(f"| {label} | error | — | — | — | — | {it['error']} |")
            continue
        run = _run_json(it["run_id"]) if it.get("status") == "done" and it.get("run_id") else None
        if run is None:
            lines.append(f"| {label} | pending | — | — | — | — | — |")
            continue
        verdict = run.get("verdict") or {}
        lead = verdict.get("lead_signal")
        sig = (run.get("signals") or {}).get(lead) or {}
        effect = fmt_signal(lead, sig.get("point"))
        interval = report_interval(lead, sig.get("lo"), sig.get("hi"))
        pval = fmt_p(sig.get("placebo_p"))
        permalink = f"/v/{run.get('id')}"
        lines.append(f"| {label} | {verdict.get('status', 'n/a')} | {lead or 'n/a'} | {effect} | "
                     f"{interval} | {pval} | [{permalink}]({permalink}) |")
        full_reports.append(render_report(run))
    md = "\n".join(lines) + "\n"
    if full_reports:
        md += "\n---\n\n" + "\n\n---\n\n".join(full_reports)
    return Response(content=md, media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="otherwise-batch-{batch_id}.md"'})


@app.get("/batch")
def batch_page():
    return FileResponse(os.path.join(WEB_DIR, "batch.html"))


if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
