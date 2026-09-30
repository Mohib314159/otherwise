"""Air API contract tests; all local, no live data calls."""
import json
import os
from collections import OrderedDict

import pytest
from fastapi.testclient import TestClient

from src.app import server
from src.app.air import AIR_CASES, air_run_id


@pytest.fixture(autouse=True)
def _air_enabled(monkeypatch):
    """These tests exercise the air API itself, so switch it on. The default
    (off) is covered by the tests at the bottom of this file."""
    monkeypatch.setattr(server, "AIR_ENABLED", True)


def test_mixed_case_air_domain_reaches_air_worker(monkeypatch):
    """The normalised domain reaches the job's child process intact.

    Runs submit() -> _worker -> a real spawned child whose run function echoes
    the request it received. That the default run function then sends "air" to
    the air pipeline and never to the land one is checked in-process by
    tests/test_app_job_process.py::test_default_runner_dispatches_air_and_land.
    """
    monkeypatch.setattr(server, "_find_run", lambda rid: None)
    monkeypatch.setattr(server, "LIVE_RUNS_ENABLED", True)
    monkeypatch.setattr(server, "_jobs", OrderedDict())
    monkeypatch.setattr(server, "JOB_RUNNER", "tests.fake_job_runners:echo_request")

    class InlineThread:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(server.threading, "Thread", InlineThread)
    reply = server.submit(server.RunRequest(domain="AiR", case_id="ulez-central-2019", post_months=3))
    job = server._jobs[reply["job_id"]]
    assert job["status"] == "done"
    assert job["run_id"] == f"air|ulez-central-2019|3|{server.LIVE_PROFILE}"


def _air_run(rid):
    return {
        "id": rid, "domain": "air", "case_id": "ulez-central-2019", "created": "2026-09-20T00:00:00+00:00",
        "label": "Central ULEZ", "change_type": "air_no2", "event_date": "2019-04-08", "post_months": 3,
        "window": ["2016-04-08", "2019-07-08"],
        "area": {"geojson": None, "ha": None, "lon": -0.1, "lat": 51.5, "landcover": None, "elevation_m": None},
        "case": AIR_CASES["ulez-central-2019"].public_dict(),
        "verdict": {"status": "REAL", "headline": "NO2 fell", "statement": "s", "reasons": [], "lead_signal": "NO2_TRAFFIC"},
        "signals": {"NO2_TRAFFIC": {"point": -4.0, "lo": -6.0, "hi": -2.0, "placebo_p": .05}},
        "charts": {}, "donors": {}, "receipts": [], "data_summary": {}, "method": {}, "timing": {},
    }


def test_air_cases_and_existing_permalink(tmp_path, monkeypatch):
    runs = tmp_path / "runs"; runs.mkdir()
    show = tmp_path / "show"; show.mkdir()
    monkeypatch.setattr(server, "RUNS_DIR", str(runs))
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(show))
    client = TestClient(server.app)

    cases = client.get("/api/air/cases")
    assert cases.status_code == 200
    ids = {x["id"] for x in cases.json()}
    assert "ulez-central-2019" in ids and "ulez-londonwide-2023" in ids

    rid = air_run_id("ulez-central-2019", 3)
    (runs / f"{rid}.json").write_text(json.dumps(_air_run(rid)))
    r = client.post("/api/run", json={"domain":"air", "case_id":"ulez-central-2019", "post_months":3})
    assert r.status_code == 200 and r.json() == {"run_id": rid, "done": True}
    assert client.get(f"/api/runs/{rid}").json()["domain"] == "air"


def test_air_validation_is_honestly_pending_until_file_exists(tmp_path, monkeypatch):
    show = tmp_path / "show"; show.mkdir()
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(show))
    client = TestClient(server.app)
    d = client.get("/api/air/validation").json()
    assert d["runs"] == []
    assert any(c["id"] == "ulez-central-2019" for c in d["cases"])

    payload = {"generated_by":"test", "runs":[{"case_id":"ulez-central-2019"}]}
    (show / "air_validation.json").write_text(json.dumps(payload))
    d2 = client.get("/api/air/validation").json()
    assert d2["runs"][0]["case_id"] == "ulez-central-2019"


def test_air_submit_rejects_unknown_case(tmp_path, monkeypatch):
    runs = tmp_path / "runs"; runs.mkdir()
    show = tmp_path / "show"; show.mkdir()
    monkeypatch.setattr(server, "RUNS_DIR", str(runs))
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(show))
    client = TestClient(server.app)
    r = client.post("/api/run", json={"domain":"air", "case_id":"not-a-case", "post_months":3})
    assert r.status_code == 400


def test_air_permalink_share_preview_uses_physical_signal(tmp_path, monkeypatch):
    runs = tmp_path / "runs"; runs.mkdir()
    show = tmp_path / "show"; show.mkdir()
    monkeypatch.setattr(server, "RUNS_DIR", str(runs))
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(show))
    # verdict_page reads the repo's real web template, so only the run store is patched.
    rid = air_run_id("ulez-central-2019", 3)
    (runs / f"{rid}.json").write_text(json.dumps(_air_run(rid)))
    client = TestClient(server.app)
    html = client.get(f"/v/{rid}").text
    assert "Central ULEZ" in html
    assert "NO₂" in html
    assert "µg/m³" in html


def test_air_boundary_endpoint_uses_registered_layer_without_touching_runner(tmp_path, monkeypatch):
    show = tmp_path / "show"; show.mkdir()
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(show))
    feature = {"type":"Feature", "properties":{"source":"test"},
               "geometry":{"type":"Polygon", "coordinates":[[[-.2,51.4],[0,51.4],[0,51.6],[-.2,51.6],[-.2,51.4]]]}}
    seen = {}
    def fake(case, http):
        seen["case"] = case.id
        return feature
    monkeypatch.setattr(server, "fetch_case_boundary", fake)
    client = TestClient(server.app)
    r = client.get("/api/air/cases/ulez-central-2019/boundary")
    assert r.status_code == 200 and r.json()["geometry"]["type"] == "Polygon"
    assert seen["case"] == "ulez-central-2019"
    r23 = client.get("/api/air/cases/ulez-londonwide-2023/boundary")
    assert r23.status_code == 200
    assert client.get("/api/air/cases/nope/boundary").status_code == 404


def test_air_is_off_by_default_and_every_air_route_says_so(monkeypatch):
    monkeypatch.delenv("APP_AIR_ENABLED", raising=False)
    assert os.environ.get("APP_AIR_ENABLED", "0") != "1"
    src = open(server.__file__, encoding="utf-8").read()
    assert 'os.environ.get("APP_AIR_ENABLED", "0") == "1"' in src   # default is off

    monkeypatch.setattr(server, "AIR_ENABLED", False)
    c = TestClient(server.app)
    case_id = next(iter(AIR_CASES))
    for url in ("/api/air/cases", f"/api/air/cases/{case_id}/boundary", "/api/air/validation"):
        assert c.get(url).status_code == 404, url
    r = c.post("/api/run", json={"domain": "air", "case_id": case_id})
    assert r.status_code == 404
    h = c.get("/api/health").json()
    assert h["air_pollution"] is False and h["air_cases"] == 0


def test_landing_page_hides_the_air_tab_until_the_server_enables_it():
    html = open(os.path.join(os.path.dirname(server.WEB_DIR), "web", "index.html"), encoding="utf-8").read()
    assert 'id="domain-picker"' in html and 'style="display:none;"' in html.split('id="domain-picker"')[1][:120]
    js = open(os.path.join(server.WEB_DIR, "landing.js"), encoding="utf-8").read()
    assert 'getElementById("domain-picker").style.display = ""' in js


def test_render_blueprint_keeps_air_off():
    root = os.path.dirname(server.WEB_DIR)
    y = open(os.path.join(root, "render.yaml"), encoding="utf-8").read()
    assert "APP_AIR_ENABLED" in y and 'value: "0"' in y.split("APP_AIR_ENABLED")[1][:40]
