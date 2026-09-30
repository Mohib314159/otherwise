"""Blind human review of sampled cases, and the analyst layer on verdict pages.

Two things live here, both self-contained so `server.py` only has to do

    from .review import router as review_router
    app.include_router(review_router)

1. **Blind review** (`/review`). A reviewer is shown sampled cases one at a
   time, in a per-session random order, with the before/after imagery, the
   time-lapse frames and the two charts -- and *nothing* that could give the
   answer away: no ground truth, no site name, no label, no coordinates, no
   absolute dates, no change type, no signal name, and none of the statistical
   verdict or its numbers. The blind payload is built from an explicit
   whitelist (`blind_payload`), never by deleting keys from the run JSON, so a
   new field in the pipeline cannot leak by accident. `tests/test_app_review.py`
   asserts the payload carries no ground-truth key.

   Blinding is procedural, not cryptographic: the sample and the results are
   public in this repo, so a reviewer who wanted to cheat could recompute the
   mapping. That is the standing assumption of any visual-interpretation
   reference exercise -- the instrument stops the answer arriving by accident,
   the protocol asks the reviewer not to go looking for it.

2. **Analyst layer** (`/api/review/annotations/...`). A human annotation
   attached to a run: a call, a status, a note and links. It is stored and
   rendered *beside* the statistical verdict and never overrides it.

Storage is one SQLite file, `APP_REVIEW_DB` (default `<runs dir>/review.sqlite`).
Blind cases are read from `APP_BLIND_DIR` (default `showcase/blind`), which is
written by `scripts/blind_validation.py` and `scripts/blind_review_prep.py`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import random
import re
import sqlite3
import threading
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .ids import RUNS_DIR

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEB_DIR = os.path.join(ROOT, "web")
ANSWERS = {"changed", "not_changed", "unsure"}
CONFIDENCES = {"low", "medium", "high"}
Z95 = 1.959963984540054

router = APIRouter()
_lock = threading.Lock()
_cache: dict = {"key": None, "cases": [], "by_id": {}, "truth": {}, "tool": {}}


def blind_dir() -> str:
    """Read the env var per call so tests can point it at a fixture directory."""
    return os.environ.get("APP_BLIND_DIR", os.path.join(ROOT, "showcase", "blind"))


def review_db() -> str:
    return os.environ.get("APP_REVIEW_DB", os.path.join(RUNS_DIR, "review.sqlite"))


# ---------------------------------------------------------------------------
# rates and intervals
# ---------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for k successes in n trials. None when n == 0.

    Wilson rather than the normal approximation because these denominators are
    small and the rates sit near 0 and 1, where the normal interval leaves the
    unit interval and covers badly (Brown, Cai & DasGupta 2001)."""
    if n <= 0:
        return None
    p = k / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z / d) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(k: int, n: int) -> dict:
    """A proportion with its denominator and 95% Wilson interval. No n, no rate."""
    ci = wilson(k, n)
    return {"k": int(k), "n": int(n),
            "rate": (k / n if n else None),
            "lo": (ci[0] if ci else None), "hi": (ci[1] if ci else None)}


def rates_from_calls(calls: list[tuple[str, str]]) -> dict:
    """calls: (truth, call) pairs, truth in REAL/NOT_REAL, call in REAL/NOT_REAL/CANT_TELL.

    detection   = REAL calls / event cases
    miss        = NOT_REAL calls / event cases
    false alarm = REAL calls / control cases
    cant_tell   = CAN'T TELL calls / cases of that kind
    Every decided case is counted, so the three rates of each row sum to 1."""
    ev = [c for t, c in calls if t == "REAL"]
    nl = [c for t, c in calls if t == "NOT_REAL"]
    return {
        "n": len(calls),
        "events": {"n": len(ev),
                   "detection": rate(ev.count("REAL"), len(ev)),
                   "miss": rate(ev.count("NOT_REAL"), len(ev)),
                   "cant_tell": rate(ev.count("CANT_TELL"), len(ev))},
        "controls": {"n": len(nl),
                     "false_alarm": rate(nl.count("REAL"), len(nl)),
                     "correct": rate(nl.count("NOT_REAL"), len(nl)),
                     "cant_tell": rate(nl.count("CANT_TELL"), len(nl))},
    }


ANSWER_TO_CALL = {"changed": "REAL", "not_changed": "NOT_REAL", "unsure": "CANT_TELL"}


def combine_tool_human(tool: str | None, human: str | None) -> str | None:
    """"Tool + human": the tool decides, the human adjudicates its CAN'T TELLs.

    The tool's REAL / NOT REAL stand -- they carry a placebo test and an
    interval, which an eye does not. Where the tool declines, the human's call
    is used; if the human is unsure too, the pair stays CAN'T TELL. This is the
    workflow the app is for (an analyst triaging what the tool could not
    settle), and it is the only simple rule that cannot change the tool's
    answer on the cases it did decide."""
    if tool is None:
        return None
    if tool != "CANT_TELL":
        return tool
    return human if human is not None else "CANT_TELL"


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    path = review_db()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, created TEXT NOT NULL,
            reviewer TEXT, order_seed INTEGER NOT NULL, sample_seed INTEGER);
        CREATE TABLE IF NOT EXISTS answers (
            session_id TEXT NOT NULL, case_id TEXT NOT NULL, answer TEXT NOT NULL,
            confidence TEXT, note TEXT, seconds REAL, created TEXT NOT NULL,
            PRIMARY KEY (session_id, case_id));
        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, created TEXT NOT NULL,
            author TEXT, status TEXT, call TEXT, note TEXT, links TEXT);
        CREATE INDEX IF NOT EXISTS annotations_run ON annotations(run_id);
    """)
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# blind cases
# ---------------------------------------------------------------------------

def case_id_for(sample_seed, item_id: str) -> str:
    """Stable, opaque id. Deterministic, so a case keeps its id across rebuilds."""
    return hashlib.sha256(f"otherwise-blind:{sample_seed}:{item_id}".encode()).hexdigest()[:12]


def _load_cases() -> dict:
    """Cases with a finished run, keyed by case id.

    Ground truth (`expected`) and the tool's verdict are loaded here for the
    scoring endpoint only; `blind_payload` never sees this dict."""
    bd = blind_dir()
    sample_path = os.path.join(bd, "sample.json")
    results_path = os.path.join(bd, "results.jsonl")
    key = (bd, ) + tuple(os.path.getmtime(p) if os.path.exists(p) else None
                         for p in (sample_path, results_path))
    with _lock:
        if _cache["key"] == key:
            return _cache
        cases, by_id, truth, tool = [], {}, {}, {}
        if os.path.exists(sample_path):
            with open(sample_path) as f:
                sample = json.load(f)
            seed = sample.get("seed")
            rows = {}
            if os.path.exists(results_path):
                with open(results_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            r = json.loads(line)
                            rows[r["id"]] = r
            for item in sample.get("items", []):
                row = rows.get(item["id"])
                if not row or not row.get("run_id"):
                    continue
                cid = case_id_for(seed, item["id"])
                truth[cid] = item["expected"]
                tool[cid] = row.get("status")
                run_id = row["run_id"]
                has_img = all(os.path.exists(os.path.join(bd, "runs", f"{run_id}_{t}.png"))
                              for t in ("before", "after"))
                rec = {"case_id": cid, "item_id": item["id"], "run_id": run_id,
                       "has_imagery": has_img}
                cases.append(rec)
                by_id[cid] = rec
        cases.sort(key=lambda c: c["case_id"])
        _cache.update({"key": key, "cases": cases, "by_id": by_id, "truth": truth, "tool": tool})
        return _cache


def reviewable(cases: list[dict]) -> list[dict]:
    """Only cases a human can actually judge: before and after imagery present."""
    return [c for c in cases if c["has_imagery"]]


def _days(dates: list[str], event: str) -> list[int]:
    ev = date.fromisoformat(event)
    return [(date.fromisoformat(d) - ev).days for d in dates]


def blind_payload(case: dict) -> dict:
    """Everything the reviewer is allowed to see, built from a whitelist.

    Included: the two thumbnails, the time-lapse frames, the observed and
    control trajectories and the gap between them, on a *relative* day axis.
    Deliberately excluded: ground truth, the tool's verdict and every number
    behind it (interval, placebo p, effect size), the placebo band, the site
    label, the change type, the signal name, the absolute dates, the polygon
    and its coordinates, the run id, the item id and the data source."""
    bd = blind_dir()
    run_path = os.path.join(bd, "runs", f"{case['run_id']}.json")
    if not os.path.exists(run_path):
        raise HTTPException(404, "case not prepared")
    with open(run_path) as f:
        run = json.load(f)
    lead = run["verdict"]["lead_signal"]
    chart = run.get("charts", {}).get(lead) or {}
    sig = run.get("signals", {}).get(lead, {})
    sensor = sig.get("sensor")
    dates = chart.get("dates") or []
    days = _days(dates, run["event_date"]) if dates else []
    base = f"/api/review/case/{case['case_id']}"

    frames = []
    fp = os.path.join(bd, "runs", f"{case['run_id']}_frames.json")
    if os.path.exists(fp):
        with open(fp) as f:
            for fr in json.load(f):
                i = int(fr["index"])
                if os.path.exists(os.path.join(bd, "runs", f"{case['run_id']}_t{i}.png")):
                    frames.append({"index": i, "url": f"{base}/t{i}.png",
                                   "day": (date.fromisoformat(fr["date"])
                                           - date.fromisoformat(run["event_date"])).days})
    frames.sort(key=lambda fr: fr["day"])

    return {
        "case_id": case["case_id"],
        "area_ha": round(float(run["area"]["ha"])),
        "images": {"before": f"{base}/before.png", "after": f"{base}/after.png"},
        "frames": frames,
        "axis": ("Radar backscatter (dB)" if sensor == "S1" else "Surface index (unitless)"),
        "chart": {"day": days,
                  "observed": chart.get("treated"),
                  "control": chart.get("counterfactual"),
                  "gap": chart.get("effect")},
        "n_observations": len([v for v in (chart.get("treated") or []) if v is not None]),
    }


# ---------------------------------------------------------------------------
# API: blind review
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    reviewer: str = Field(default="", max_length=80)


class AnswerRequest(BaseModel):
    session_id: str = Field(max_length=64)
    case_id: str = Field(max_length=32)
    answer: str
    confidence: str = ""
    note: str = Field(default="", max_length=2000)
    seconds: float | None = None


@router.get("/review")
def review_page():
    return FileResponse(os.path.join(WEB_DIR, "review.html"))


@router.post("/api/review/session")
def start_session(req: StartRequest):
    c = _load_cases()
    sid = uuid.uuid4().hex[:16]
    seed = int.from_bytes(os.urandom(4), "big")
    with _connect() as con:
        con.execute("INSERT INTO sessions (session_id, created, reviewer, order_seed, sample_seed) "
                    "VALUES (?,?,?,?,?)", (sid, _now(), req.reviewer.strip() or None, seed, None))
    return {"session_id": sid, "order_seed": seed, "n_cases": len(reviewable(c["cases"]))}


def order_for(session_id: str, seed: int, cases: list[dict]) -> list[str]:
    """The per-session presentation order: a shuffle seeded by the session."""
    ids = [c["case_id"] for c in cases]
    random.Random(f"{session_id}:{seed}").shuffle(ids)
    return ids


def _session(con, session_id: str):
    row = con.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such review session")
    return row


@router.get("/api/review/next")
def next_case(session: str):
    c = _load_cases()
    pool = reviewable(c["cases"])
    with _connect() as con:
        s = _session(con, session)
        done = {r["case_id"] for r in con.execute(
            "SELECT case_id FROM answers WHERE session_id = ?", (session,))}
    order = order_for(session, s["order_seed"], pool)
    by_id = {x["case_id"]: x for x in pool}
    for cid in order:
        if cid not in done:
            return {"done": False, "answered": len(done), "total": len(pool),
                    "case": blind_payload(by_id[cid])}
    return {"done": True, "answered": len(done), "total": len(pool), "case": None}


@router.post("/api/review/answer")
def submit_answer(req: AnswerRequest):
    if req.answer not in ANSWERS:
        raise HTTPException(400, f"answer must be one of {sorted(ANSWERS)}")
    conf = req.confidence.strip().lower()
    if conf and conf not in CONFIDENCES:
        raise HTTPException(400, f"confidence must be one of {sorted(CONFIDENCES)}")
    c = _load_cases()
    if req.case_id not in c["by_id"]:
        raise HTTPException(404, "no such case")
    with _connect() as con:
        _session(con, req.session_id)
        con.execute("INSERT OR IGNORE INTO answers "
                    "(session_id, case_id, answer, confidence, note, seconds, created) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (req.session_id, req.case_id, req.answer, conf or None,
                     req.note.strip() or None, req.seconds, _now()))
        n = con.execute("SELECT COUNT(*) FROM answers WHERE session_id = ?",
                        (req.session_id,)).fetchone()[0]
    total = len(reviewable(c["cases"]))
    return {"ok": True, "answered": n, "remaining": max(0, total - n)}


@router.get("/api/review/case/{case_id}/{tag}.png")
def case_image(case_id: str, tag: str):
    if tag not in ("before", "after") and not re.fullmatch(r"t\d{1,2}", tag):
        raise HTTPException(404)
    c = _load_cases()
    case = c["by_id"].get(case_id)
    if not case:
        raise HTTPException(404)
    p = os.path.join(blind_dir(), "runs", f"{case['run_id']}_{tag}.png")
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


# ---------------------------------------------------------------------------
# API: the three numbers
# ---------------------------------------------------------------------------

def score(cases: dict, answers: list) -> dict:
    """Tool alone, human alone and tool + human, each over its own denominator.

    Tool alone covers every finished run. Human alone and tool + human cover
    the cases a human has actually answered; one row per (session, case), so
    two reviewers answering the same case count twice and `by_session` shows
    them separately."""
    truth, tool = cases["truth"], cases["tool"]
    tool_calls = [(truth[cid], tool[cid]) for cid in truth
                  if tool.get(cid) in ("REAL", "NOT_REAL", "CANT_TELL")]
    human_calls, both_calls, per_session = [], [], {}
    for a in answers:
        cid = a["case_id"]
        if cid not in truth:
            continue
        hc = ANSWER_TO_CALL[a["answer"]]
        human_calls.append((truth[cid], hc))
        combined = combine_tool_human(tool.get(cid), hc)
        if combined is not None:
            both_calls.append((truth[cid], combined))
        per_session.setdefault(a["session_id"], []).append((truth[cid], hc))
    return {
        "tool": rates_from_calls(tool_calls),
        "human": rates_from_calls(human_calls),
        "tool_human": rates_from_calls(both_calls),
        "reviews": len(human_calls),
        "reviewers": len(per_session),
        "by_session": {s: rates_from_calls(v) for s, v in per_session.items()},
        "combination_rule": ("The tool decides; where it returns CAN'T TELL the human's call is used. "
                             "If the human is unsure as well, the pair stays CAN'T TELL."),
        "interval": "95% Wilson score interval",
    }


@router.get("/api/review/results")
def review_results():
    """Aggregates only -- never per-case answers, so this cannot unblind a case."""
    c = _load_cases()
    with _connect() as con:
        answers = list(con.execute("SELECT session_id, case_id, answer FROM answers"))
    out = score(c, answers)
    meta = {}
    sp = os.path.join(blind_dir(), "summary.json")
    if os.path.exists(sp):
        with open(sp) as f:
            s = json.load(f)
        meta = {"seed": s.get("seed"), "sample_n": s.get("sample_n"), "completed": s.get("completed"),
                "git_commit": s.get("git_commit"), "sample_generated": s.get("sample_generated"),
                "generated": s.get("generated"), "sample_git_commit": s.get("sample_git_commit")}
    out["sample"] = meta
    out["cases_prepared_for_review"] = len(reviewable(c["cases"]))
    return out


# ---------------------------------------------------------------------------
# API: analyst layer on verdict pages
# ---------------------------------------------------------------------------

class AnnotationRequest(BaseModel):
    run_id: str = Field(max_length=64)
    call: str = ""
    status: str = ""
    note: str = Field(default="", max_length=4000)
    links: list[str] = Field(default_factory=list)
    author: str = Field(default="", max_length=80)


ANNOTATION_CALLS = {"", "changed", "not_changed", "unsure"}
ANNOTATION_STATUS = {"", "unreviewed", "in_review", "confirmed", "disputed"}


def _annotation_row(r) -> dict:
    return {"id": r["id"], "run_id": r["run_id"], "created": r["created"], "author": r["author"],
            "status": r["status"], "call": r["call"], "note": r["note"],
            "links": json.loads(r["links"] or "[]")}


@router.get("/api/review/annotations/{run_id}")
def get_annotations(run_id: str):
    with _connect() as con:
        rows = list(con.execute("SELECT * FROM annotations WHERE run_id = ? ORDER BY id DESC", (run_id,)))
    return {"run_id": run_id, "annotations": [_annotation_row(r) for r in rows],
            "note": "Human annotation. It does not change the statistical verdict."}


def _check_review_token(supplied: str | None) -> None:
    """Writes are closed unless APP_REVIEW_TOKEN is set and the caller sends it."""
    token = os.environ.get("APP_REVIEW_TOKEN", "")
    if not token or not supplied or not hmac.compare_digest(supplied.encode(), token.encode()):
        raise HTTPException(403, "Annotations are restricted to analysts.")


@router.post("/api/review/annotations")
def add_annotation(req: AnnotationRequest, x_review_token: str | None = Header(default=None)):
    _check_review_token(x_review_token)
    if req.call not in ANNOTATION_CALLS:
        raise HTTPException(400, f"call must be one of {sorted(ANNOTATION_CALLS)}")
    if req.status not in ANNOTATION_STATUS:
        raise HTTPException(400, f"status must be one of {sorted(ANNOTATION_STATUS)}")
    links = [l.strip() for l in req.links if l.strip().startswith(("http://", "https://"))][:10]
    if not (req.note.strip() or req.call or links):
        raise HTTPException(400, "an annotation needs a note, a call or a link")
    with _connect() as con:
        cur = con.execute("INSERT INTO annotations (run_id, created, author, status, call, note, links) "
                          "VALUES (?,?,?,?,?,?,?)",
                          (req.run_id, _now(), req.author.strip() or None, req.status or "in_review",
                           req.call or None, req.note.strip() or None, json.dumps(links)))
        row = con.execute("SELECT * FROM annotations WHERE id = ?", (cur.lastrowid,)).fetchone()
        out = _annotation_row(row)
    return {"ok": True, "annotation": out}
