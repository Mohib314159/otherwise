"""Known-answer checks over the committed showcase runs (no network).

The showcase JSONs are real results computed by scripts/run_sites.py. These
tests pin the properties that must hold for the method to be trusted:
  * a site with no documented event is never called REAL (no false alarms)
  * a REAL verdict always has a placebo p <= 0.10 and an interval that
    excludes zero in the claimed direction
  * the sharply bounded, well-documented clearing (Grünheide) is called REAL
"""
import glob
import json
import os

import pytest

SHOW = os.path.join(os.path.dirname(__file__), "..", "showcase")


def _runs():
    idx_path = os.path.join(SHOW, "index.json")
    if not os.path.exists(idx_path):
        pytest.skip("no showcase index")
    out = []
    for e in json.load(open(idx_path)):
        p = os.path.join(SHOW, f"{e['id']}.json")
        if os.path.exists(p):
            out.append((e, json.load(open(p))))
    if not out:
        pytest.skip("no showcase runs")
    return out


def test_no_false_alarms_on_null_sites():
    for e, r in _runs():
        if e.get("expected") == "NOT_REAL":
            assert r["verdict"]["status"] != "REAL", e["label"]


def test_real_verdicts_pass_placebo_and_exclude_zero():
    for e, r in _runs():
        v = r["verdict"]
        if v["status"] != "REAL":
            continue
        s = r["signals"][v["lead_signal"]]
        assert s["placebo_p"] <= 0.10, e["label"]
        sign = s["expected_sign"]
        if sign < 0:
            assert s["hi"] < 0, e["label"]
        elif sign > 0:
            assert s["lo"] > 0, e["label"]
        else:
            assert s["lo"] > 0 or s["hi"] < 0, e["label"]
        assert abs(s["point"]) >= s["min_effect"], e["label"]


def test_grunheide_clearing_is_real():
    runs = {e["key"]: r for e, r in _runs()}
    if "grunheide" not in runs:
        pytest.skip("grunheide not in showcase")
    r = runs["grunheide"]
    assert r["verdict"]["status"] == "REAL"
    assert r["signals"]["NDVI"]["point"] < -0.15


def test_events_larger_than_ring_are_not_called_real_from_ring_controls():
    """An event bigger than the 12 km control ring contaminates its own controls,
    so a RING run of it must not come back REAL.

    Wide mode exists precisely to give these events valid controls (Rhodes:
    42 cells 20-150 km away), so a wide run reaching REAL is the intended
    outcome, not a failure. The distinction is the point of the test: assert on
    the mode that produced the run, not on the site.
    """
    runs = {e["key"]: r for e, r in _runs()}
    for key in ("rhodes", "sindh"):
        if key not in runs:
            continue
        r = runs[key]
        if r.get("mode") == "wide":
            assert r["controls"]["inner_m"] >= 12_000, (
                f"{key} is marked wide but its controls start inside the ring")
            continue
        assert r["verdict"]["status"] != "REAL", (
            f"{key} was called REAL from ring controls the event itself covers")
