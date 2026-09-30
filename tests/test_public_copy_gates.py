"""Public-site honesty fixes: showcase provenance in the run payload, the
superseded-run pointer, the confirmed flag on the track record, the copy on the
verdict / track-record / landing / batch pages, and the analyst-only form.
No network."""
from __future__ import annotations

import copy
import json
import os
import re

import pytest
from fastapi.testclient import TestClient

from src.app import server
from tests.test_web_copy import browser, web_url, load, dom_text, showcase_run, text_of  # noqa: F401  (fixtures)

WEB = os.path.join(os.path.dirname(__file__), "..", "web")
SHOWCASE = os.path.join(os.path.dirname(__file__), "..", "showcase")


def _read(name: str) -> str:
    return open(os.path.join(WEB, name), encoding="utf-8").read()


def _run(rid, label="Somewhere: an event"):
    return {"id": rid, "created": "2026-01-01T00:00:00+00:00", "label": label, "change_type": "burn",
            "event_date": "2023-07-18", "post_months": 12, "window": ["2020-01-01", "2024-01-01"],
            "area": {"geojson": {"type": "Polygon", "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]]},
                     "ha": 10, "lon": 0, "lat": 0, "landcover": None, "elevation_m": None},
            "verdict": {"status": "CANT_TELL", "headline": "Can't tell", "statement": "s", "reasons": [],
                        "lead_signal": "NDVI"},
            "signals": {}, "charts": {}, "donors": {"cells": [], "distance_m": [], "landcover": None},
            "receipts": [], "data_summary": {}, "timing": {}, "method": {}}


@pytest.fixture
def api(tmp_path, monkeypatch):
    runs = tmp_path / "runs"; runs.mkdir()
    show = tmp_path / "showcase"; show.mkdir()
    monkeypatch.setattr(server, "RUNS_DIR", str(runs))
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(show))
    label = "Grünheide, Germany: forest cleared"
    for rid, lab in (("new0000000000001", label), ("old0000000000001", label), ("nul0000000000001", "Park: nothing")):
        json.dump(_run(rid, lab), open(show / f"{rid}.json", "w"))
    json.dump([{"key": "g", "id": "new0000000000001", "label": label, "expected": "REAL", "confirmed": False},
               {"key": "n", "id": "nul0000000000001", "label": "Park: nothing", "expected": "NOT_REAL",
                "confirmed": False}], open(show / "index.json", "w"))
    rows = [{"id": "new0000000000001", "label": label, "expected": "REAL", "status": "REAL", "counted": True}]
    json.dump({"runs": rows, "summary": {"n": 1}}, open(show / "track_record.json", "w"))
    return TestClient(server.app)


# ---- server ------------------------------------------------------------------

def test_showcase_run_carries_index_provenance(api):
    d = api.get("/api/runs/new0000000000001").json()
    assert d["showcase"] == {"key": "g", "expected": "REAL", "confirmed": False}
    assert "superseded_by" not in d
    assert api.get("/api/runs/nul0000000000001").json()["showcase"]["expected"] == "NOT_REAL"


def test_run_missing_from_index_points_at_the_current_run_of_the_same_case(api):
    d = api.get("/api/runs/old0000000000001").json()
    assert d["superseded_by"] == "new0000000000001" and "showcase" not in d


def test_track_record_rows_carry_confirmed_from_the_index(api):
    assert api.get("/api/track-record").json()["runs"][0]["confirmed"] is False


def test_the_committed_orphan_grunheide_run_is_superseded():
    ids = {e["id"] for e in json.load(open(os.path.join(SHOWCASE, "index.json")))}
    orphan = "9028a5c4c87fc301"
    if orphan in ids or not os.path.exists(os.path.join(SHOWCASE, f"{orphan}.json")):
        pytest.skip("orphan run not present in this checkout")
    meta = server._showcase_meta(orphan, json.load(open(os.path.join(SHOWCASE, f"{orphan}.json"))))
    assert meta["superseded_by"] in ids


# ---- static copy -------------------------------------------------------------

def test_no_public_nav_link_to_review_or_batch():
    for name in ("index.html", "track.html", "batch.html", "verdict.html", "review.html", "common.js",
                 "track.js", "verdict.js", "landing.js"):
        src = _read(name)
        assert 'href="/review"' not in src, name
        assert 'href="/batch"' not in src, name


def test_batch_page_states_the_public_server_limit():
    assert "Batch runs need the offline pipeline; on the public server they queue behind one slow slot." in _read("batch.html")


def test_landing_labels():
    html = _read("index.html")
    assert "Real check" not in html and "Documented case" in html
    assert "Regrowth or restoration (experimental — no validated cases)" in html
    assert "Something else (experimental — no validated cases)" in html
    assert "Flooding (experimental)" in html


# ---- verdict page (browser) --------------------------------------------------

def _live_run(rid="live000000000001"):
    """A full committed run under a fresh id, so it renders like a real one."""
    r = copy.deepcopy(showcase_run("CANT_TELL"))
    r["id"] = rid
    r.pop("showcase", None)
    return r


def _showcase_run(expected):
    r = _live_run("new0000000000001")
    r["showcase"] = {"key": "k", "expected": expected, "confirmed": False}
    return r


def test_showcase_claim_line_and_candidate_badge(load):
    pg = load(_showcase_run("REAL"))
    assert dom_text(pg, ".verdict-kicker").startswith("Claim tested: a burn on ")
    assert dom_text(pg, ".verdict-kicker").count("false-alarm") == 0
    assert "You reported" not in pg.content()
    assert "candidate — not yet independently confirmed" in text_of(pg, "#candidate-badge")


def test_null_site_claim_line_says_false_alarm_check(load):
    pg = load(_showcase_run("NOT_REAL"))
    assert dom_text(pg, ".verdict-kicker").endswith("(false-alarm check: nothing documented here)")


def test_confirmed_site_has_no_badge_and_live_run_keeps_reported_wording(load):
    r = _showcase_run("REAL"); r["showcase"]["confirmed"] = True
    pg = load(r)
    assert pg.query_selector("#candidate-badge") is None
    live = _live_run()
    pg2 = load(live)
    assert dom_text(pg2, ".verdict-kicker").startswith("You reported a burn here on")
    assert pg2.query_selector("#candidate-badge") is None


def test_superseded_banner(load):
    r = _live_run("old0000000000001"); r["superseded_by"] = "new0000000000001"
    pg = load(r)
    assert text_of(pg, "#superseded-note").startswith("Superseded: this is an older run of this case.")
    assert pg.query_selector("#superseded-note a").get_attribute("href") == "/v/new0000000000001"


def test_annotation_form_only_with_analyst_param_and_sends_token(browser, web_url):
    seen = {}
    pg = browser.new_page()

    def route(r, req):
        path = req.url[len(web_url) - 1:] if req.url.startswith(web_url) else ""
        p = path.split("?")[0]
        if p.startswith("/api/runs/") and p.count("/") == 3:
            r.fulfill(status=200, content_type="application/json", body=json.dumps(_live_run()))
        elif p.startswith("/api/review/annotations/"):
            r.fulfill(status=200, content_type="application/json", body='{"annotations": [{"id":1,"note":"seen by all","links":[]}]}')
        elif p == "/api/review/annotations":
            seen["token"] = req.headers.get("x-review-token")
            r.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"ok": True, "annotation": {"id": 2, "note": "n", "links": []}}))
        elif path.startswith("/api/"):
            r.fulfill(status=404, content_type="application/json", body="{}")
        elif req.url.startswith(web_url):
            r.continue_()
        else:
            r.fulfill(status=200, content_type="text/plain", body=b"")

    pg.route("**/*", route)
    pg.goto(f"{web_url}v/live000000000001", wait_until="load")
    pg.wait_for_selector("#analyst-layer", timeout=15_000)
    assert "seen by all" in pg.inner_text("#analyst-layer")
    assert pg.query_selector("#ann-form") is None
    pg.goto(f"{web_url}v/live000000000001?analyst=tok123", wait_until="load")
    pg.wait_for_selector("#ann-form", timeout=15_000)
    pg.fill("textarea[name=note]", "n")
    pg.click("#ann-form button[type=submit]")
    pg.wait_for_function("() => document.querySelectorAll('.ann').length === 2")
    assert seen["token"] == "tok123"
    pg.close()


# ---- track record (browser) --------------------------------------------------

def test_track_record_summary_is_computed_from_rows_and_badges_candidates(browser, web_url):
    def row(i, expected, status, confirmed=False):
        return {"id": f"r{i}", "label": f"Site {i}", "type": "clearing", "expected": expected, "status": status,
                "counted": True, "confirmed": confirmed, "signal": "NDVI"}
    rows = [row(1, "REAL", "REAL"), row(2, "REAL", "REAL"), row(3, "REAL", "CANT_TELL"), row(4, "REAL", "NOT_REAL"),
            row(5, "NOT_REAL", "REAL"), row(6, "NOT_REAL", "CANT_TELL", True), row(7, "NOT_REAL", "NOT_REAL")]
    pg = browser.new_page()

    def route(r, req):
        path = req.url[len(web_url) - 1:] if req.url.startswith(web_url) else ""
        if path.startswith("/api/track-record"):
            r.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"runs": rows, "summary": {"n": 7, "hits": 99}}))
        elif path.startswith("/api/"):
            r.fulfill(status=404, content_type="application/json", body="{}")
        elif req.url.startswith(web_url):
            r.continue_()
        else:
            r.fulfill(status=200, content_type="text/plain", body=b"")

    pg.route("**/*", route)
    pg.goto(f"{web_url}track.html", wait_until="load")
    pg.wait_for_selector(".summary-line", timeout=15_000)
    assert pg.inner_text(".summary-line").strip() == (
        "2 of 4 documented events detected, 1 can't tell, 1 missed (called NOT REAL); "
        "3 null sites: 1 false alarms, 1 can't tell")
    assert pg.locator("td .candidate-badge").count() == 6      # the confirmed row has none
    pg.close()
