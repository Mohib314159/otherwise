"""The showcase imagery audit, and the server fields the verdict page's visual
evidence reads. Offline: no imagery is fetched."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from scripts import showcase_imagery as si
from src.app import server


def _write(d, name, obj):
    with open(os.path.join(d, name), "w") as f:
        json.dump(obj, f)


def _png(d, name):
    open(os.path.join(d, name), "wb").write(b"\x89PNG\r\n\x1a\n")


@pytest.fixture
def showcase(tmp_path, monkeypatch):
    monkeypatch.setattr(si, "SHOWCASE", str(tmp_path))
    return str(tmp_path)


def test_audit_flags_wrongly_dated_or_cloudy_thumbnails_and_an_unmarkable_event(showcase):
    run = {"id": "r1", "event_date": "2020-02-13", "label": "x"}
    _write(showcase, "r1_before.json", {"date": "2020-03-01", "clear": 0.95})   # after the event
    _write(showcase, "r1_after.json", {"date": "2020-03-14", "clear": 0.40})    # too cloudy
    _png(showcase, "r1_before.png"); _png(showcase, "r1_after.png")
    _write(showcase, "r1_frames.json", [{"index": 0, "date": "2020-03-01", "clear": 1.0},
                                        {"index": 1, "date": "2020-06-01", "clear": 1.0}])
    _png(showcase, "r1_t0.png"); _png(showcase, "r1_t1.png")
    p = " | ".join(si.audit(run)["problems"])
    assert "before: dated 2020-03-01, on the wrong side of the event" in p
    assert "after: clear share 0.4 below 0.6" in p
    assert "event date outside the frame range" in p


def test_audit_passes_a_clean_run_and_checks_controls_share_the_areas_dates(showcase):
    run = {"id": "r2", "event_date": "2020-02-13", "label": "x"}
    _write(showcase, "r2_before.json", {"date": "2020-01-24", "clear": 0.94})
    _write(showcase, "r2_after.json", {"date": "2020-03-14", "clear": 1.0})
    _png(showcase, "r2_before.png"); _png(showcase, "r2_after.png")
    _write(showcase, "r2_frames.json", [{"index": 0, "date": "2019-01-01", "clear": 1.0},
                                        {"index": 1, "date": "2020-06-01", "clear": 0.9}])
    _png(showcase, "r2_t0.png"); _png(showcase, "r2_t1.png")
    ctl = lambda b, a: {"rank": 1, "role": "weighted", "weight": 1.0,
                        "before": {"date": b, "same_scene_as_area": True}, "after": {"date": a, "same_scene_as_area": True}}
    _write(showcase, "r2_controls.json", {"controls": [ctl("2020-01-24", "2020-03-14")]})
    assert si.audit(run)["problems"] == []
    _write(showcase, "r2_controls.json", {"controls": [ctl("2020-01-22", "2020-03-14")]})
    assert any("control 1 before" in p for p in si.audit(run)["problems"])


def test_run_payload_carries_controls_and_only_the_aligned_overlay(tmp_path, monkeypatch):
    run = json.load(open(os.path.join(server.SHOWCASE_DIR, "5a5f8d14423c28f0.json")))
    monkeypatch.setattr(server, "RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(tmp_path))
    _write(str(tmp_path), f"{run['id']}.json", run)
    _write(str(tmp_path), f"{run['id']}_change.json", {"status": "ok", "overlay": f"{run['id']}_changeoverlay.png"})
    _png(str(tmp_path), f"{run['id']}_change.png")
    c = TestClient(server.app)
    assert c.get(f"/api/runs/{run['id']}").json()["pixels"]["overlay_url"] is None   # file missing: no overlay
    _png(str(tmp_path), f"{run['id']}_changeoverlay.png")
    _write(str(tmp_path), f"{run['id']}_controls.json", {"controls": [{"rank": 1}], "skipped": []})
    body = c.get(f"/api/runs/{run['id']}").json()
    assert body["pixels"]["overlay_url"] == f"/api/runs/{run['id']}/changeoverlay.png"
    assert body["control_imagery"]["controls"] == [{"rank": 1}]
    _png(str(tmp_path), f"{run['id']}_ctl1_before.png")
    assert c.get(f"/api/runs/{run['id']}/ctl1_before.png").status_code == 200
    assert c.get(f"/api/runs/{run['id']}/changeoverlay.png").status_code == 200
    assert c.get(f"/api/runs/{run['id']}/ctl1_sideways.png").status_code == 404
