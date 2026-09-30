"""Tests for src/app/review.py: the blind payload leaks no ground truth, the
review store round-trips, a case is never shown twice in a session, and the
three scored numbers are arithmetically what they claim to be. No network."""
from __future__ import annotations

import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app import review as R

# Everything a reviewer must not see. Values are taken from the fixture below.
GIVEAWAYS = [
    "expected", "REAL", "NOT_REAL", "CANT_TELL", "verdict", "status", "headline",
    "clearing", "hansen", "Hansen", "lossyear", "placebo", "label",
    "Bolivia-secret-site", "2021-03-04", "change_type", "event_date",
    "-62.5", "1.25", "run_id", "item_id", "NDVI", "geojson", "lon", "lat",
]

RUN_ID = "abc123def456"
ITEM_ID = "ev-hansen-007"


def _run_json() -> dict:
    dates = ["2020-03-04", "2020-09-04", "2021-03-04", "2021-09-04"]
    return {
        "id": RUN_ID, "label": "Blind sample 007: Hansen forest loss 2021, tile 00N_060W",
        "change_type": "clearing", "event_date": "2021-03-04", "post_months": 18,
        "window": ["2018-03-04", "2022-09-04"],
        "area": {"ha": 61.4, "lon": -62.5, "lat": 1.25, "geojson": {"type": "Polygon", "coordinates": [[]]},
                 "landcover": "tree cover"},
        "verdict": {"status": "REAL", "headline": "Real change", "statement": "Greenness fell by 0.4",
                    "reasons": [], "lead_signal": "NDVI"},
        "signals": {"NDVI": {"signal": "NDVI", "sensor": "S2", "point": -0.4, "lo": -0.5, "hi": -0.3,
                             "placebo_p": 0.02, "n_pre": 40, "n_post": 12, "n_donors": 30}},
        "charts": {"NDVI": {"dates": dates, "treated": [0.8, 0.82, 0.79, 0.4],
                            "counterfactual": [0.8, 0.81, 0.8, 0.8], "effect": [0.0, 0.01, -0.01, -0.4],
                            "placebo_band": [[-0.1], [0.1]], "placebo_effects": [0.01, -0.02],
                            "time_placebos": [], "n_obs": [5, 5, 5, 5]}},
        "evidence": {"agreement": "both", "sentence": "radar agrees"},
        "receipts": [], "mode": "ring",
    }


@pytest.fixture()
def blind(tmp_path, monkeypatch):
    """A blind directory with one event case and one control case, both finished."""
    runs = tmp_path / "runs"
    runs.mkdir(parents=True)
    items, rows = [], []
    for i, (iid, rid, expected, status) in enumerate([
            (ITEM_ID, RUN_ID, "REAL", "REAL"),
            ("nl-hansen-007", "fed654cba321", "NOT_REAL", "CANT_TELL")]):
        run = _run_json()
        run["id"] = rid
        if expected == "NOT_REAL":
            run["verdict"]["status"] = "CANT_TELL"
        (runs / f"{rid}.json").write_text(json.dumps(run))
        for tag in ("before", "after"):
            (runs / f"{rid}_{tag}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        items.append({"id": iid, "kind": "event" if expected == "REAL" else "null", "source": "hansen",
                      "change_type": "clearing", "expected": expected, "event_date": "2021-03-04",
                      "post_months": 18, "geojson": run["area"]["geojson"],
                      "label": "Bolivia-secret-site " + iid})
        rows.append({"id": iid, "run_id": rid, "status": status, "expected": expected})
    (tmp_path / "sample.json").write_text(json.dumps({"seed": 20260918, "n_items": 2, "items": items}))
    (tmp_path / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setenv("APP_BLIND_DIR", str(tmp_path))
    monkeypatch.setenv("APP_REVIEW_DB", str(tmp_path / "review.sqlite"))
    R._cache["key"] = None                       # the module caches by mtime; force a reload
    yield tmp_path
    R._cache["key"] = None


@pytest.fixture()
def client(blind):
    app = FastAPI()
    app.include_router(R.router)
    return TestClient(app)


# ---------------------------------------------------------------- blinding ---

def _keys(obj, out=None):
    out = out if out is not None else set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def test_blind_payload_carries_no_ground_truth(blind):
    cases = R._load_cases()
    payload = R.blind_payload(cases["by_id"][R.case_id_for(20260918, ITEM_ID)])
    blob = json.dumps(payload)
    for word in GIVEAWAYS:
        assert word not in blob, f"blind payload leaks {word!r}: {blob}"
    assert not ({"expected", "verdict", "status", "label", "event_date", "change_type", "run_id",
                 "item_id", "signals", "placebo_p", "point", "lo", "hi"} & _keys(payload))


def test_blind_endpoint_carries_no_ground_truth(client):
    sid = client.post("/api/review/session", json={"reviewer": "t"}).json()["session_id"]
    body = client.get(f"/api/review/next?session={sid}").text
    for word in GIVEAWAYS:
        assert word not in body, f"/api/review/next leaks {word!r}"


def test_blind_payload_uses_relative_days_and_neutral_axis(blind):
    cases = R._load_cases()
    p = R.blind_payload(cases["by_id"][R.case_id_for(20260918, ITEM_ID)])
    assert p["chart"]["day"] == [-365, -181, 0, 184]           # day 0 is the claimed date
    assert p["axis"] == "Surface index (unitless)"       # never "NDVI"
    assert p["chart"]["observed"] and p["chart"]["control"] and p["chart"]["gap"]
    assert "placebo_band" not in json.dumps(p)


def test_case_id_is_stable_and_opaque():
    a = R.case_id_for(20260918, "ev-hansen-007")
    assert a == R.case_id_for(20260918, "ev-hansen-007")
    assert a != R.case_id_for(20260918, "ev-hansen-008")
    assert a != R.case_id_for(1, "ev-hansen-007")
    assert "hansen" not in a and len(a) == 12


def test_case_image_is_served_by_case_id_only(client, blind):
    cid = R.case_id_for(20260918, ITEM_ID)
    assert client.get(f"/api/review/case/{cid}/before.png").status_code == 200
    assert client.get(f"/api/review/case/{cid}/secret.png").status_code == 404
    assert client.get(f"/api/review/case/{RUN_ID}/before.png").status_code == 404


# ------------------------------------------------------------------- store ---

def test_session_answer_round_trip_and_no_repeats(client):
    s = client.post("/api/review/session", json={"reviewer": "MM"}).json()
    sid = s["session_id"]
    assert s["n_cases"] == 2

    seen = []
    for expected_answered in (0, 1):
        nxt = client.get(f"/api/review/next?session={sid}").json()
        assert nxt["done"] is False
        assert nxt["answered"] == expected_answered
        cid = nxt["case"]["case_id"]
        seen.append(cid)
        r = client.post("/api/review/answer", json={"session_id": sid, "case_id": cid,
                                                    "answer": "changed", "confidence": "high",
                                                    "note": "clear cut block", "seconds": 4.2}).json()
        assert r["ok"] and r["answered"] == expected_answered + 1

    assert len(set(seen)) == 2                                  # never the same case twice
    done = client.get(f"/api/review/next?session={sid}").json()
    assert done["done"] is True and done["case"] is None and done["answered"] == 2

    with R._connect() as con:
        rows = list(con.execute("SELECT * FROM answers WHERE session_id = ?", (sid,)))
    assert [r["answer"] for r in rows] == ["changed", "changed"]
    assert rows[0]["note"] == "clear cut block" and rows[0]["confidence"] == "high"


def test_two_sessions_get_independent_orders_and_stores(client):
    a = client.post("/api/review/session", json={}).json()
    b = client.post("/api/review/session", json={}).json()
    assert a["session_id"] != b["session_id"] and a["order_seed"] != b["order_seed"]
    first_a = client.get(f"/api/review/next?session={a['session_id']}").json()["case"]["case_id"]
    client.post("/api/review/answer", json={"session_id": a["session_id"], "case_id": first_a,
                                            "answer": "unsure"})
    # b has answered nothing, so b still sees every case
    assert client.get(f"/api/review/next?session={b['session_id']}").json()["answered"] == 0


def test_answer_validation(client):
    sid = client.post("/api/review/session", json={}).json()["session_id"]
    cid = client.get(f"/api/review/next?session={sid}").json()["case"]["case_id"]
    assert client.post("/api/review/answer", json={"session_id": sid, "case_id": cid,
                                                   "answer": "maybe"}).status_code == 400
    assert client.post("/api/review/answer", json={"session_id": sid, "case_id": cid,
                                                   "answer": "changed", "confidence": "certain"}).status_code == 400
    assert client.post("/api/review/answer", json={"session_id": "nope", "case_id": cid,
                                                   "answer": "changed"}).status_code == 404
    assert client.post("/api/review/answer", json={"session_id": sid, "case_id": "0" * 12,
                                                   "answer": "changed"}).status_code == 404


def test_order_is_shuffled_not_sample_order():
    cases = [{"case_id": f"c{i:03d}"} for i in range(50)]
    ids = [c["case_id"] for c in cases]
    o1 = R.order_for("s1", 1, cases)
    assert sorted(o1) == sorted(ids) and o1 != ids
    assert R.order_for("s1", 1, cases) == o1                    # reproducible per session
    assert R.order_for("s2", 1, cases) != o1


# ------------------------------------------------------------------- rates ---

def test_wilson_matches_published_values():
    assert R.wilson(0, 0) is None
    lo, hi = R.wilson(10, 20)                                   # symmetric case
    assert lo == pytest.approx(0.299, abs=0.001) and hi == pytest.approx(0.701, abs=0.001)
    lo, hi = R.wilson(0, 20)                                    # zero successes: lower bound is 0
    assert lo == 0.0 and hi == pytest.approx(0.161, abs=0.001)
    lo, hi = R.wilson(20, 20)
    assert lo == pytest.approx(0.839, abs=0.001) and hi == 1.0
    lo, hi = R.wilson(37, 40)
    assert lo == pytest.approx(0.801, abs=0.001) and hi == pytest.approx(0.974, abs=0.001)


def test_rate_reports_its_denominator():
    r = R.rate(3, 12)
    assert (r["k"], r["n"]) == (3, 12) and r["rate"] == pytest.approx(0.25)
    assert r["lo"] < 0.25 < r["hi"]
    empty = R.rate(0, 0)
    assert empty["rate"] is None and empty["lo"] is None and empty["hi"] is None


def test_rates_from_calls_splits_events_and_controls():
    calls = [("REAL", "REAL"), ("REAL", "REAL"), ("REAL", "CANT_TELL"), ("REAL", "NOT_REAL"),
             ("NOT_REAL", "NOT_REAL"), ("NOT_REAL", "REAL")]
    out = R.rates_from_calls(calls)
    assert out["events"]["n"] == 4 and out["controls"]["n"] == 2
    assert out["events"]["detection"]["k"] == 2 and out["events"]["detection"]["rate"] == 0.5
    assert out["events"]["miss"]["k"] == 1 and out["events"]["cant_tell"]["k"] == 1
    assert out["controls"]["false_alarm"]["k"] == 1 and out["controls"]["false_alarm"]["rate"] == 0.5
    # the three event rates cover every event case
    e = out["events"]
    assert e["detection"]["k"] + e["miss"]["k"] + e["cant_tell"]["k"] == e["n"]


def test_combine_tool_human_only_fills_cant_tells():
    assert R.combine_tool_human("REAL", "NOT_REAL") == "REAL"        # the tool's call stands
    assert R.combine_tool_human("NOT_REAL", "REAL") == "NOT_REAL"
    assert R.combine_tool_human("CANT_TELL", "REAL") == "REAL"       # human adjudicates
    assert R.combine_tool_human("CANT_TELL", "CANT_TELL") == "CANT_TELL"
    assert R.combine_tool_human("CANT_TELL", None) == "CANT_TELL"
    assert R.combine_tool_human(None, "REAL") is None                # no run, no call


def test_results_endpoint_reports_three_numbers_and_no_case_answers(client):
    empty = client.get("/api/review/results").json()
    assert empty["tool"]["events"]["detection"]["k"] == 1 and empty["tool"]["events"]["detection"]["n"] == 1
    assert empty["human"]["n"] == 0
    assert empty["human"]["events"]["detection"]["rate"] is None     # nothing reviewed yet: no number
    assert empty["reviews"] == 0 and empty["reviewers"] == 0

    sid = client.post("/api/review/session", json={}).json()["session_id"]
    for _ in range(2):
        nxt = client.get(f"/api/review/next?session={sid}").json()
        client.post("/api/review/answer", json={"session_id": sid, "case_id": nxt["case"]["case_id"],
                                                "answer": "changed"})
    out = client.get("/api/review/results").json()
    assert out["reviews"] == 2 and out["reviewers"] == 1
    assert out["human"]["events"]["detection"]["k"] == 1            # the event case: called changed
    assert out["human"]["controls"]["false_alarm"]["k"] == 1        # the control case: called changed
    # tool + human: the tool said REAL for the event (kept) and CAN'T TELL for the
    # control (adjudicated by the human, who said changed -> a false alarm)
    assert out["tool_human"]["events"]["detection"]["k"] == 1
    assert out["tool_human"]["controls"]["false_alarm"]["k"] == 1
    assert out["tool"]["controls"]["cant_tell"]["k"] == 1
    body = json.dumps(out)
    assert ITEM_ID not in body and RUN_ID not in body


# ------------------------------------------------------------- annotations ---

TOKEN = "s3cret-token"


@pytest.fixture
def analyst(monkeypatch):
    monkeypatch.setenv("APP_REVIEW_TOKEN", TOKEN)
    return {"X-Review-Token": TOKEN}


def test_annotation_write_gate(client, monkeypatch, analyst):
    body = {"run_id": "xyz", "call": "changed"}
    monkeypatch.delenv("APP_REVIEW_TOKEN")
    assert client.post("/api/review/annotations", json=body).status_code == 403
    assert client.post("/api/review/annotations", json=body, headers={"X-Review-Token": ""}).status_code == 403
    monkeypatch.setenv("APP_REVIEW_TOKEN", "")
    assert client.post("/api/review/annotations", json=body, headers={"X-Review-Token": ""}).status_code == 403
    monkeypatch.setenv("APP_REVIEW_TOKEN", TOKEN)
    assert client.post("/api/review/annotations", json=body).status_code == 403
    assert client.post("/api/review/annotations", json=body, headers={"X-Review-Token": "wrong"}).status_code == 403
    assert client.post("/api/review/annotations", json=body, headers=analyst).status_code == 200
    assert len(client.get("/api/review/annotations/xyz").json()["annotations"]) == 1   # GET stays open


def test_annotation_round_trip_and_validation(client, analyst):
    assert client.get("/api/review/annotations/xyz").json()["annotations"] == []
    r = client.post("/api/review/annotations", headers=analyst, json={
        "run_id": "xyz", "call": "changed", "status": "confirmed", "author": "MM",
        "note": "Planet basemap shows the same block cleared.",
        "links": ["https://example.org/report", "javascript:alert(1)"]}).json()
    assert r["ok"] and r["annotation"]["links"] == ["https://example.org/report"]
    got = client.get("/api/review/annotations/xyz").json()
    assert len(got["annotations"]) == 1
    assert got["annotations"][0]["call"] == "changed" and got["annotations"][0]["status"] == "confirmed"
    assert "does not change the statistical verdict" in got["note"]
    assert client.post("/api/review/annotations", headers=analyst, json={"run_id": "xyz", "call": "nonsense"}).status_code == 400
    assert client.post("/api/review/annotations", headers=analyst, json={"run_id": "xyz"}).status_code == 400


def test_review_page_is_served(client, monkeypatch):
    assert os.path.exists(os.path.join(R.WEB_DIR, "review.html"))
    assert client.get("/review").status_code == 200
