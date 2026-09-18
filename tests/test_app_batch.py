"""Batch endpoints: submit a FeatureCollection, poll status, download reports.
Fake runs on disk, no network — same fixture pattern as test_app_server.py.
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from src.app import server
from src.app import run as runmod

GOOD_GEOM = {"type": "Polygon", "coordinates": [[[0, 51], [0.01, 51], [0.01, 51.01], [0, 51.01], [0, 51]]]}
TINY_GEOM = {"type": "Polygon", "coordinates": [[[0, 51], [0.0001, 51], [0.0001, 51.0001], [0, 51.0001], [0, 51]]]}


def _fake_run(rid="abc123"):
    return {"id": rid, "created": "2026-01-01T00:00:00+00:00", "label": "t", "change_type": "clearing",
            "event_date": "2023-01-01", "post_months": 12, "window": ["2020-01-01", "2024-01-01"],
            "area": {"geojson": GOOD_GEOM, "ha": 10, "lon": 0, "lat": 51, "landcover": None, "elevation_m": None},
            "verdict": {"status": "NOT_REAL", "headline": "No real change", "statement": "s", "reasons": [], "lead_signal": "NDVI"},
            "signals": {}, "charts": {}, "donors": {"cells": [], "distance_m": [], "landcover": None},
            "receipts": [], "data_summary": {}, "timing": {}, "method": {}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    runs = tmp_path / "runs"; runs.mkdir()
    show = tmp_path / "showcase"; show.mkdir()
    monkeypatch.setattr(server, "RUNS_DIR", str(runs))
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(show))
    monkeypatch.setattr(server, "_batches", {})
    with open(runs / "abc123.json", "w") as f:
        json.dump(_fake_run(), f)
    return TestClient(server.app)


def test_run_report_md_200_for_fake_run(client):
    r = client.get("/api/runs/abc123/report.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert 'attachment; filename="otherwise-abc123.md"' in r.headers["content-disposition"]
    assert "NOT_REAL" in r.text


def test_run_report_md_404_for_unknown(client):
    assert client.get("/api/runs/nope/report.md").status_code == 404


def test_run_json_download_200_and_404(client):
    r = client.get("/api/runs/abc123/run.json")
    assert r.status_code == 200
    assert r.json()["id"] == "abc123"
    assert client.get("/api/runs/nope/run.json").status_code == 404


def test_batch_with_tiny_polygon_returns_item_with_error(client):
    body = {"features": [{"type": "Feature", "geometry": TINY_GEOM,
                          "properties": {"event_date": "2023-01-01"}}],
           "default_change_type": "clearing", "default_post_months": 12}
    r = client.post("/api/batch", json=body)
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["error"] and "ha" in item["error"]
    assert item["run_id"] is None


def test_batch_with_existing_run_id_is_done(client):
    rid = runmod.run_id(GOOD_GEOM, "2023-01-01", "clearing", 12)
    with open(os.path.join(server.RUNS_DIR, f"{rid}.json"), "w") as f:
        json.dump(_fake_run(rid), f)
    body = {"features": [{"type": "Feature", "geometry": GOOD_GEOM,
                          "properties": {"event_date": "2023-01-01"}}],
           "default_change_type": "clearing", "default_post_months": 12}
    r = client.post("/api/batch", json=body)
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["done"] is True
    assert item["run_id"] == rid

    s = client.get(f"/api/batch/{r.json()['batch_id']}")
    assert s.status_code == 200
    assert s.json()["items"][0]["status"] == "done"


def test_batch_missing_event_date_is_an_error(client):
    body = {"features": [{"type": "Feature", "geometry": GOOD_GEOM, "properties": {}}],
           "default_change_type": "clearing", "default_post_months": 12}
    r = client.post("/api/batch", json=body)
    item = r.json()["items"][0]
    assert item["error"] and "event_date" in item["error"]


def test_batch_too_many_features_413(client):
    body = {"features": [{"type": "Feature", "geometry": GOOD_GEOM,
                          "properties": {"event_date": "2023-01-01"}}] * 26,
           "default_change_type": "clearing", "default_post_months": 12}
    r = client.post("/api/batch", json=body)
    assert r.status_code == 413


def test_batch_unknown_id_404(client):
    assert client.get("/api/batch/nope").status_code == 404
    assert client.get("/api/batch/nope/report.md").status_code == 404


def test_batch_report_md_returns_text(client):
    rid = runmod.run_id(GOOD_GEOM, "2023-01-01", "clearing", 12)
    with open(os.path.join(server.RUNS_DIR, f"{rid}.json"), "w") as f:
        json.dump(_fake_run(rid), f)
    body = {"features": [{"type": "Feature", "geometry": GOOD_GEOM,
                          "properties": {"event_date": "2023-01-01"}}],
           "default_change_type": "clearing", "default_post_months": 12}
    r = client.post("/api/batch", json=body)
    batch_id = r.json()["batch_id"]
    rep = client.get(f"/api/batch/{batch_id}/report.md")
    assert rep.status_code == 200
    assert rep.headers["content-type"].startswith("text/markdown")
    assert "batch report" in rep.text.lower()
    assert rid in rep.text


def test_batch_page_serves_html(client):
    r = client.get("/batch")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
