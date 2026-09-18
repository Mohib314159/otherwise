"""Tests for src/app/fetch.py: dedupe by processing baseline and footprint coverage."""
from __future__ import annotations

from datetime import datetime, timezone

from shapely.geometry import box

from src.app.fetch import _covering, _latest_processing
from src.app.providers import Scene


def _scene(id_, minute, tile, baseline, geometry=None):
    dt = datetime.strptime(minute, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    return Scene(id=id_, sensor="S2", datetime=dt, hrefs={},
                 props={"tile": tile, "baseline": baseline}, geometry=geometry)


def test_latest_processing_keeps_newest_baseline_same_tile():
    old = _scene("a", "2023-06-01T10:30", "30UXD", "03.00")
    new = _scene("b", "2023-06-01T10:30", "30UXD", "05.10")

    out = _latest_processing([old, new])

    assert len(out) == 1
    assert out[0].id == "b"


def test_latest_processing_keeps_both_different_tiles():
    a = _scene("a", "2023-06-01T10:30", "30UXD", "03.00")
    b = _scene("b", "2023-06-01T10:30", "30UXC", "03.00")

    out = _latest_processing([a, b])

    assert {s.id for s in out} == {"a", "b"}


def test_covering_keeps_intersecting_and_none_geometry():
    area = box(0, 0, 10, 10)
    inside = _scene("a", "2023-06-01T10:30", "30UXD", "05.10", geometry=box(5, 5, 15, 15))
    outside = _scene("b", "2023-06-01T10:30", "30UXD", "05.10", geometry=box(100, 100, 110, 110))
    no_geom = _scene("c", "2023-06-01T10:30", "30UXD", "05.10", geometry=None)

    out = _covering([inside, outside, no_geom], area)

    assert {s.id for s in out} == {"a", "c"}
