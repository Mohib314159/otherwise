"""Unlisted outreach runs: served by id, absent from every listing."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.app import server

RID = "out0000000000001"


def _run(rid):
    return {"id": rid, "label": "Somewhere: an event", "event_date": "2022-06-01", "post_months": 12,
            "change_type": "clearing",
            "area": {"geojson": {"type": "Polygon", "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]]},
                     "ha": 10, "lon": 0, "lat": 0, "landcover": None, "elevation_m": None},
            "verdict": {"status": "NOT_REAL", "headline": "No real change", "statement": "s", "reasons": [],
                        "lead_signal": "NDVI"},
            "signals": {}, "charts": {}, "donors": {"cells": [], "distance_m": [], "landcover": None},
            "receipts": [], "data_summary": {}, "timing": {}, "method": {}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    show = tmp_path / "showcase"
    show.mkdir()
    monkeypatch.setattr(server, "RUNS_DIR", str(runs))
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(show))
    for rid in ("abc123", RID):
        (show / f"{rid}.json").write_text(json.dumps(_run(rid)))
    (show / "index.json").write_text(json.dumps([
        {"id": "abc123", "label": "Fake", "expected": "NOT_REAL", "source": "", "blurb": "b"},
        {"id": RID, "label": "Outreach", "expected": None, "source": "", "confirmed": False, "listed": False},
    ]))
    (show / "track_record.json").write_text(json.dumps({"runs": [{"id": "abc123"}, {"id": RID}], "summary": None}))
    return TestClient(server.app)


def test_listings_exclude_the_unlisted_run(client):
    assert [e["id"] for e in client.get("/api/showcase").json()] == ["abc123"]
    assert [r["id"] for r in client.get("/api/track-record").json()["runs"]] == ["abc123"]


def test_unlisted_run_is_still_served_by_id(client):
    r = client.get(f"/api/runs/{RID}")
    assert r.status_code == 200 and r.json()["id"] == RID
    assert client.get(f"/v/{RID}").status_code == 200


def test_outreach_index_entry_shape():
    from scripts.run_outreach import index_entry, parse_bbox
    e = index_entry("abc", "Somewhere", "clearing")
    assert e["listed"] is False and e["expected"] is None and e["confirmed"] is False
    assert parse_bbox("1,2,3,4") == (1.0, 2.0, 3.0, 4.0)
