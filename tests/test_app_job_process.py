"""Live runs execute in a spawned child process, never inside the web process.

Each test drives the real supervisor (`server._worker`) and a real spawned
child; only the run function is fake (tests/fake_job_runners.py). No network.
"""
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.app import jobrunner, server


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(server, "JOB_POLL_S", 0.05)
    monkeypatch.setattr(server, "JOB_RUNNER", server.JOB_RUNNER)   # restored after each test
    return server


def _queue(srv, job_id, cls=dict):
    srv._jobs[job_id] = cls(status="queued", stage="queued", done=0, total=1,
                            rid="r-" + job_id, created=time.time())


def _run(srv, runner):
    srv.JOB_RUNNER = f"tests.fake_job_runners:{runner}"
    job_id = os.urandom(6).hex()
    _queue(srv, job_id)
    srv._worker(job_id, srv.RunRequest(geojson={"type": "Polygon"}, event_date="2020-01-01"))
    return srv._jobs.pop(job_id)


def _slot_is_free(srv):
    ok = srv._sem.acquire(blocking=False)
    if ok:
        srv._sem.release()
    return ok


def test_success_reports_run_id_and_child_writes_to_runs_dir(srv, tmp_path):
    job = _run(srv, "succeed")
    assert job["status"] == "done" and job["stage"] == "done"
    assert job["run_id"].startswith("fake-ok-")
    assert int(job["run_id"].rsplit("-", 1)[1]) != os.getpid(), "ran in another process"
    assert (tmp_path / "fake-ok.json").exists()
    assert _slot_is_free(srv)


def test_an_exception_in_the_child_is_reported(srv):
    job = _run(srv, "raise_error")
    assert job["status"] == "error" and job["stage"] == "error"
    assert job["error"] == "fake pipeline failure"
    assert _slot_is_free(srv)


def test_a_hung_child_is_killed_at_the_hard_deadline(srv, monkeypatch):
    monkeypatch.setattr(srv, "JOB_TIMEOUT_S", 0.5)
    monkeypatch.setattr(srv, "JOB_KILL_GRACE_S", 0.5)
    t0 = time.monotonic()
    job = _run(srv, "hang")                       # sleeps 120 s with no checkpoint
    assert time.monotonic() - t0 < 60, "killed, not waited out"
    assert job["status"] == "error"
    assert "limit" in job["error"] and "stopped" in job["error"]
    assert _slot_is_free(srv)


def test_a_sigkilled_child_reads_as_out_of_memory_and_the_server_lives(srv):
    job = _run(srv, "sigkill_self")
    assert job["status"] == "error"
    assert "ran out of memory" in job["error"]
    assert _slot_is_free(srv)
    h = TestClient(srv.app).get("/api/health")
    assert h.status_code == 200 and h.json()["ok"] is True


def test_a_child_that_exits_nonzero_reports_its_exit_code(srv):
    job = _run(srv, "exit_3")
    assert job["status"] == "error"
    assert "exit code 3" in job["error"]
    assert "memory" not in job["error"]


def test_progress_reaches_the_job_record(srv):
    seen = []

    class Spy(dict):
        def update(self, *a, **kw):
            seen.append(dict(*a, **kw))
            super().update(*a, **kw)

    srv.JOB_RUNNER = "tests.fake_job_runners:succeed"
    job_id = "p" * 12
    _queue(srv, job_id, Spy)
    srv._worker(job_id, srv.RunRequest(geojson={"type": "Polygon"}, event_date="2020-01-01"))
    srv._jobs.pop(job_id)
    assert {"stage": "sentinel-2", "done": 1, "total": 2} in seen


def test_max_live_jobs_still_bounds_concurrency(srv, monkeypatch):
    """With every slot taken, a job waits queued and spawns nothing."""
    spawned = []

    def no_spawn(*a):
        spawned.append(a)
        raise RuntimeError("spawn refused by test")

    monkeypatch.setattr(srv.multiprocessing, "get_context", no_spawn)
    held = 0
    while srv._sem.acquire(blocking=False):
        held += 1
    assert held == srv.MAX_LIVE_JOBS
    job_id = "q" * 12
    _queue(srv, job_id)
    t = threading.Thread(target=srv._worker, daemon=True, args=(job_id, srv.RunRequest(
        geojson={"type": "Polygon"}, event_date="2020-01-01")))
    try:
        t.start()
        t.join(0.5)
        assert t.is_alive() and srv._jobs[job_id]["status"] == "queued" and spawned == []
    finally:
        for _ in range(held):
            srv._sem.release()
    t.join(10)
    assert len(spawned) == 1
    assert srv._jobs.pop(job_id)["status"] == "error"


def test_default_runner_dispatches_air_and_land(tmp_path, monkeypatch):
    """The real run function (in-process here): air goes to run_air_verdict and never
    the land pipeline; land goes to run_verdict with the live profile, then thumbnails."""
    from src.app import air, imagery, run as runmod
    calls = []

    def fake_air(case_id, months, **kw):
        calls.append(("air", case_id, months, kw["runs_dir"]))
        return {"id": "air-1"}

    def fake_land(g, d, ct, pm, **kw):
        calls.append(("land", ct, pm, kw["profile"], kw["runs_dir"]))
        return {"id": "land-1"}

    monkeypatch.setattr(air, "run_air_verdict", fake_air)
    monkeypatch.setattr(runmod, "run_verdict", fake_land)
    monkeypatch.setattr(imagery, "make_thumbnails",
                        lambda g, d, out, rid: {"before": {"date": "2020-01-01"}})
    rd = str(tmp_path)
    progress = lambda *a: None
    assert jobrunner.run_live_job({"domain": "air", "case_id": "c", "post_months": 3}, progress,
                                  runs_dir=rd, profile="live") == "air-1"
    assert calls == [("air", "c", 3, rd)]
    assert jobrunner.run_live_job({"domain": "land", "geojson": {}, "event_date": "2020-01-01",
                                   "change_type": "clearing", "post_months": 6}, progress,
                                  runs_dir=rd, profile="live") == "land-1"
    assert calls[1] == ("land", "clearing", 6, "live", rd)
    assert (tmp_path / "land-1_before.json").exists()
