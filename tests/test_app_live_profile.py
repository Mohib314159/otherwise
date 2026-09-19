"""The memory-bounded live profile: scene pre-filters and the read-window budget.

These are the guards that keep a user-drawn run inside a 512 MB container.
They are pure functions, so none of this touches the network.
"""
from datetime import datetime, timezone

import numpy as np
import pytest
from shapely.geometry import box

from src.app.fetch import (LIVE_MAX_WINDOW_PX, PROFILES, MemoryBudgetError, best_tile_per_minute,
                           cap_per_bin, choose_donor_res, window_px)
from src.app.geometry import donor_grid, validate_polygon
from src.app.providers import Scene


def _scene(day, tile, geom, cloud=10.0, hour=10, minute=0):
    return Scene(id=f"{tile}_{day}", sensor="S2",
                 datetime=datetime(2020, 1, 1, hour, minute, tzinfo=timezone.utc).replace(
                     year=int(day[:4]), month=int(day[5:7]), day=int(day[8:10])),
                 hrefs={}, props={"tile": tile, "cloud_cover": cloud}, geometry=geom)


def _area(ha=27.0):
    side = (ha * 10_000) ** 0.5
    d = side / 111_000.0
    return {"type": "Polygon", "coordinates": [[[13.8, 52.4], [13.8 + d, 52.4],
                                               [13.8 + d, 52.4 + d], [13.8, 52.4 + d], [13.8, 52.4]]]}


# --- one tile per acquisition -------------------------------------------------

def test_best_tile_per_minute_keeps_the_tile_that_covers_the_target():
    target = box(0, 0, 1, 1)
    full = box(-1, -1, 2, 2)          # contains the target
    sliver = box(0.9, 0.9, 3, 3)      # clips one corner
    keep, dropped = best_tile_per_minute([_scene("2020-03-01", "A", sliver),
                                          _scene("2020-03-01", "B", full)], target)
    assert len(keep) == 1 and len(dropped) == 1
    assert keep[0].props["tile"] == "B"


def test_best_tile_per_minute_keeps_distinct_acquisitions():
    target = box(0, 0, 1, 1)
    g = box(-1, -1, 2, 2)
    scenes = [_scene("2020-03-01", "A", g), _scene("2020-03-06", "A", g), _scene("2020-03-11", "A", g)]
    keep, dropped = best_tile_per_minute(scenes, target)
    assert len(keep) == 3 and dropped == []


def test_best_tile_per_minute_survives_missing_geometry():
    keep, _ = best_tile_per_minute([_scene("2020-03-01", "A", None)], box(0, 0, 1, 1))
    assert len(keep) == 1


# --- at most N scenes per analysis bin ---------------------------------------

def test_cap_per_bin_keeps_the_least_cloudy():
    g = box(-1, -1, 2, 2)
    scenes = [_scene("2020-03-02", "A", g, cloud=80, minute=1),
              _scene("2020-03-03", "A", g, cloud=5, minute=2),
              _scene("2020-03-04", "A", g, cloud=40, minute=3),
              _scene("2020-03-05", "A", g, cloud=60, minute=4)]
    keep, dropped = cap_per_bin(scenes, "2020-03-01", bin_days=10, per_bin=2)
    assert len(keep) == 2 and len(dropped) == 2
    assert sorted(s.props["cloud_cover"] for s in keep) == [5, 40]


def test_cap_per_bin_spans_bins_and_is_anchored_on_the_event():
    g = box(-1, -1, 2, 2)
    scenes = [_scene("2020-03-02", "A", g, cloud=10, minute=1),
              _scene("2020-03-03", "A", g, cloud=20, minute=2),
              _scene("2020-03-15", "A", g, cloud=30, minute=3),
              _scene("2020-03-16", "A", g, cloud=40, minute=4)]
    keep, _ = cap_per_bin(scenes, "2020-03-01", bin_days=10, per_bin=1)
    assert len(keep) == 2                       # one per bin, two bins
    assert {s.date for s in keep} == {"2020-03-02", "2020-03-15"}


def test_cap_per_bin_is_a_no_op_without_a_cap():
    g = box(-1, -1, 2, 2)
    scenes = [_scene("2020-03-02", "A", g), _scene("2020-03-03", "A", g)]
    keep, dropped = cap_per_bin(scenes, "2020-03-01", 10, 0)
    assert len(keep) == 2 and dropped == []


def test_cap_per_bin_treats_missing_cloud_cover_as_worst():
    g = box(-1, -1, 2, 2)
    a = _scene("2020-03-02", "A", g, cloud=None, minute=1)
    b = _scene("2020-03-03", "A", g, cloud=50, minute=2)
    keep, _ = cap_per_bin([a, b], "2020-03-01", 10, 1)
    assert keep[0].props["cloud_cover"] == 50


# --- read-window budget -------------------------------------------------------

def test_window_px_scales_with_the_square_of_resolution():
    p = [box(0, 0, 1000, 1000)]
    assert window_px(p, 10) == pytest.approx(window_px(p, 20) * 4, rel=0.02)


def test_the_full_ring_at_10m_is_what_blew_the_budget():
    """The measured regression: treated + ring donors in one 10 m window is
    ~6 Mpx, four times the live budget; the treated area alone is ~3 kpx."""
    area = validate_polygon(_area())
    grid = donor_grid(area)
    both = [area.utm] + grid.cells
    assert window_px(both, 10) > 5e6
    assert window_px([area.utm], 10) < 1e4
    assert window_px(both, 40) < 1.5e6


def test_choose_donor_res_picks_the_coarsest_that_fits():
    area = validate_polygon(_area())
    grid = donor_grid(area)
    res = choose_donor_res([area.utm] + grid.cells)
    assert res == 40.0


def test_choose_donor_res_fails_fast_with_a_readable_message():
    huge = [box(0, 0, 400_000, 400_000)]        # 400 km square: nothing fits
    with pytest.raises(MemoryBudgetError) as e:
        choose_donor_res(huge)
    msg = str(e.value)
    assert "million pixels" in msg and "smaller area" in msg


# --- profile table ------------------------------------------------------------

def test_live_profile_is_strictly_cheaper_than_full():
    live, full = PROFILES["live"], PROFILES["full"]
    assert live["max_cloud"] < full["max_cloud"]
    assert live["max_cells"] < full["max_cells"]
    assert live["workers"] <= full["workers"]
    assert live["per_bin"] and not full["per_bin"]
    assert live["one_tile_per_minute"] and not full["one_tile_per_minute"]
    assert live["split_donors"] and not full["split_donors"]


def test_full_profile_is_unchanged_behaviour():
    """Showcase and validation numbers must not move: the full profile applies
    no pre-filter and reads at native resolution."""
    full = PROFILES["full"]
    assert full["donor_res"] is None
    assert full["per_bin"] is None
    assert full["max_cloud"] == 95.0


# --- donor groups must not drag the treated polygon into their window ---------

def test_wide_donor_window_excludes_the_treated_polygon():
    """Regression: a wide run hit the 512 MiB ceiling because of this.

    Donor groups used to be read as `[area.utm] + cells`, so Zones.build's
    bounding box stretched from the treated area to cells 20-150 km away. The
    treated polygon was only in the list so column 0 could be stripped again
    afterwards, and it cost 4-11x the read window.
    """
    from src.app.fetch import window_px
    from src.app.geometry import wide_candidates

    area = validate_polygon(_area(ha=100.0))
    cands = wide_candidates(area, 20_000.0, 150_000.0, n=400)
    # Groups are spatially bucketed so each is one compact read window
    # (fetch._wide_groups buckets on a 30 km grid); a scattered selection would
    # already span the annulus and hide the effect being tested.
    buckets: dict[tuple, list] = {}
    for c, d in zip(cands.cells, cands.distances_m):
        if d < 60_000:
            continue
        k = (int(c.centroid.x // 30_000), int(c.centroid.y // 30_000))
        buckets.setdefault(k, []).append(c)
    group = max(buckets.values(), key=len)
    assert len(group) >= 3, "expected a compact cluster of distant cells"

    with_treated = window_px([area.utm] + group, 40.0)
    cells_only = window_px(group, 40.0)
    assert cells_only < with_treated / 3, (
        f"including the treated polygon should dominate the window: "
        f"{with_treated / 1e6:.2f} Mpx vs {cells_only / 1e6:.2f} Mpx")
    assert cells_only < LIVE_MAX_WINDOW_PX


def test_ring_donor_window_is_unaffected_by_the_same_change():
    """The ring surrounds the area, so dropping it changes nothing there.

    Worth pinning: it is why the fix above did not invalidate cached ring
    fetches, whose donor columns keep the same shape and the same values.
    """
    from src.app.fetch import window_px

    area = validate_polygon(_area())
    grid = donor_grid(area, max_cells=120)
    with_treated = window_px([area.utm] + grid.cells, 40.0)
    cells_only = window_px(grid.cells, 40.0)
    assert abs(with_treated - cells_only) / with_treated < 0.01


def test_donor_groups_are_read_without_the_treated_polygon():
    """Pin the call sites themselves, so the old pattern cannot come back."""
    import inspect

    from src.app import fetch as f
    for fn in (f._fetch_wide, f._fetch_live_ring):
        src = inspect.getsource(fn)
        assert "_fetch_group([area.utm] + cells" not in src, (
            f"{fn.__name__} passes the treated polygon into the donor group window")
