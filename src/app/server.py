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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .geometry import PolygonError, validate_polygon
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


@app.get("/api/runs/{rid}/{tag}.png")
def get_thumb(rid: str, tag: str):
    if tag not in ("before", "after"):
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


if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
