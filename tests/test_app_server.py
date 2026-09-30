import time
"""API smoke tests with a fake run on disk; no network."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from src.app import server


def _fake_run(rid="abc123"):
    return {"id": rid, "created": "2026-01-01T00:00:00+00:00", "label": "t", "change_type": "clearing",
            "event_date": "2023-01-01", "post_months": 12, "window": ["2020-01-01", "2024-01-01"],
            "area": {"geojson": {"type": "Polygon", "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]]},
                     "ha": 10, "lon": 0, "lat": 0, "landcover": None, "elevation_m": None},
            "verdict": {"status": "NOT_REAL", "headline": "No real change", "statement": "s", "reasons": [], "lead_signal": "NDVI"},
            "signals": {}, "charts": {}, "donors": {"cells": [], "distance_m": [], "landcover": None},
            "receipts": [], "data_summary": {}, "timing": {}, "method": {}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    runs = tmp_path / "runs"; runs.mkdir()
    show = tmp_path / "showcase"; show.mkdir()
    monkeypatch.setattr(server, "RUNS_DIR", str(runs))
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(show))
    with open(runs / "abc123.json", "w") as f:
        json.dump(_fake_run(), f)
    with open(show / "index.json", "w") as f:
        json.dump([{"id": "abc123", "label": "Fake", "expected": "NOT_REAL", "source": "", "blurb": "b"}], f)
    return TestClient(server.app)


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_get_run_and_404(client):
    r = client.get("/api/runs/abc123")
    assert r.status_code == 200 and r.json()["verdict"]["status"] == "NOT_REAL"
    assert r.json()["imagery"] == {}
    assert client.get("/api/runs/nope").status_code == 404


def test_showcase_lists_existing_runs(client):
    s = client.get("/api/showcase").json()
    assert len(s) == 1 and s[0]["id"] == "abc123" and s[0]["status"] == "NOT_REAL"


def test_track_record_empty(client):
    assert client.get("/api/track-record").json() == {"runs": [], "summary": None}


def test_submit_rejects_bad_polygon(client):
    body = {"geojson": {"type": "Polygon", "coordinates": [[[0, 51], [0.0001, 51], [0.0001, 51.0001], [0, 51.0001], [0, 51]]]},
            "event_date": "2023-01-01", "change_type": "clearing", "post_months": 12}
    r = client.post("/api/run", json=body)
    assert r.status_code == 400 and "0.5 ha" in r.json()["detail"]


def test_submit_rejects_bad_type(client):
    body = {"geojson": {"type": "Polygon", "coordinates": [[[0, 51], [0.01, 51], [0.01, 51.01], [0, 51.01], [0, 51]]]},
            "event_date": "2023-01-01", "change_type": "meteor", "post_months": 12}
    assert client.post("/api/run", json=body).status_code == 400


def test_submit_returns_existing_run_without_a_job(client, monkeypatch):
    body = {"geojson": _fake_run()["area"]["geojson"], "event_date": "2023-01-01",
            "change_type": "clearing", "post_months": 12}
    from src.app import run as runmod
    rid = runmod.run_id(body["geojson"], "2023-01-01", "clearing", 12)
    with open(os.path.join(server.RUNS_DIR, f"{rid}.json"), "w") as f:
        json.dump(_fake_run(rid), f)
    r = client.post("/api/run", json=body)
    assert r.status_code == 200 and r.json() == {"run_id": rid, "done": True}


def _queue_job(srv, job_id):
    srv._jobs[job_id] = {"status": "queued", "stage": "queued", "done": 0, "total": 1,
                         "rid": "deadbeef", "created": time.time()}


_REQ_GEOJSON = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}


def test_a_wedged_job_is_cancelled_at_the_next_checkpoint(monkeypatch, tmp_path):
    """Regression: one wedged run held the single live-run slot forever.

    The run executes in a child process whose progress callback raises once the
    deadline passes, so a run that keeps reporting progress stops at its next
    checkpoint (well before the parent's hard kill) and the slot is released,
    instead of blocking every later run until restart.
    """
    from src.app import server as srv

    counter = tmp_path / "checkpoints"
    monkeypatch.setenv("FAKE_JOB_COUNTER", str(counter))    # inherited by the child
    monkeypatch.setattr(srv, "RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(srv, "JOB_TIMEOUT_S", 0.0)
    monkeypatch.setattr(srv, "JOB_KILL_GRACE_S", 120.0)     # prove the checkpoint, not the kill
    monkeypatch.setattr(srv, "JOB_RUNNER", "tests.fake_job_runners:checkpoint_forever")

    job_id = "t" * 12
    _queue_job(srv, job_id)
    t0 = time.monotonic()
    srv._worker(job_id, srv.RunRequest(geojson=_REQ_GEOJSON, event_date="2020-01-01"))

    job = srv._jobs.pop(job_id)
    assert job["status"] == "error"
    assert "limit" in job["error"]
    assert counter.read_text() == "x", "cancelled at the first checkpoint, not after the whole run"
    assert time.monotonic() - t0 < 60, "stopped by the checkpoint, not the hard kill"
    # the slot is free again
    assert srv._sem.acquire(blocking=False)
    srv._sem.release()
