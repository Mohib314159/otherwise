"""Tests for scripts/blind_sample.py: component picking on a synthetic raster,
null-box picking, band helpers and RNG determinism. No network."""
from __future__ import annotations

import numpy as np
import pytest

from scripts.blind_sample import (
    MIN_LOSS_FRAC,
    allowed_years,
    box_sums,
    mtbs_climate,
    pick_component,
    pick_null_box,
    pixel_ha,
    qualifying_offsets,
    size_bucket,
    substream,
    tile_for,
)

PIX_HA = 0.0775          # one Hansen pixel at the equator, hectares
CODE_2019 = 19


def _window(h=200, w=200):
    return np.zeros((h, w), dtype=np.uint8), np.full((h, w), 80, dtype=np.uint8)


def test_pick_component_returns_shrunken_bbox_of_a_solid_block():
    ly, tc = _window()
    ly[50:80, 60:100] = CODE_2019              # 30 x 40 = 1200 px = 93 ha, solid
    pick = pick_component(ly, tc, 2019, np.random.default_rng(0), PIX_HA)
    assert pick is not None
    assert (pick["row0"], pick["row1"], pick["col0"], pick["col1"]) == (51, 79, 61, 99)
    assert pick["component_px"] == 1200
    assert pick["loss_fraction"] == 1.0
    assert pick["n_candidates"] == 1
    assert pick["box_ha"] == pytest.approx(28 * 38 * PIX_HA, abs=0.01)


def test_pick_component_ignores_other_years_low_cover_and_small_or_edge_components():
    ly, tc = _window()
    ly[50:80, 60:100] = 18                     # 2018: wrong year
    ly[100:130, 60:100] = CODE_2019
    tc[100:130, 60:100] = 10                   # too little tree cover in 2000
    ly[150:160, 10:20] = CODE_2019             # 100 px = 7.8 ha: below 20 ha
    ly[0:40, 120:160] = CODE_2019              # touches the window edge
    assert pick_component(ly, tc, 2019, np.random.default_rng(0), PIX_HA) is None


def test_pick_component_rejects_sparse_components():
    ly, tc = _window()
    # a diagonal band: connected (8-conn) but fills a small share of its bbox
    for i in range(60):
        ly[40 + i, 40 + i:40 + i + 5] = CODE_2019
    pick = pick_component(ly, tc, 2019, np.random.default_rng(0), PIX_HA)
    assert pick is None                        # 300 px = 23 ha but bbox fraction far below 60%


def test_pick_component_caps_the_box_and_keeps_it_inside_the_component_bbox():
    ly, tc = _window(300, 300)
    ly[20:280, 20:100] = CODE_2019             # 260 x 80 = 20800 px = 1612 ha: too big a component
    assert pick_component(ly, tc, 2019, np.random.default_rng(0), PIX_HA) is None
    ly, tc = _window(300, 300)
    ly[20:80, 20:106] = CODE_2019              # 60 x 86 = 5160 px = 399.9 ha component, box 58 x 84 = 377 ha
    pick = pick_component(ly, tc, 2019, np.random.default_rng(0), PIX_HA, max_box_ha=100.0)
    assert pick is not None
    assert pick["box_ha"] <= 100.0
    assert 21 <= pick["row0"] < pick["row1"] <= 79 and 21 <= pick["col0"] < pick["col1"] <= 105
    assert pick["loss_fraction"] >= MIN_LOSS_FRAC


def test_pick_component_choice_is_seeded():
    ly, tc = _window()
    ly[10:40, 10:40] = CODE_2019               # 900 px = 70 ha
    ly[100:130, 100:130] = CODE_2019
    ly[150:180, 20:50] = CODE_2019
    picks = [pick_component(ly, tc, 2019, np.random.default_rng(7), PIX_HA) for _ in range(3)]
    assert picks[0] == picks[1] == picks[2]
    assert picks[0]["n_candidates"] == 3
    other = {pick_component(ly, tc, 2019, np.random.default_rng(s), PIX_HA)["row0"] for s in range(20)}
    assert len(other) > 1                      # different seeds do reach different components


def test_pick_null_box_respects_cover_and_buffer():
    ly, tc = _window()
    tc[:, :] = 90
    tc[100:110, 100:110] = 20                  # a hole in the cover
    ly[150, 150] = 5                           # one loss pixel (2005)
    rng = np.random.default_rng(3)
    for _ in range(30):
        b = pick_null_box(ly, tc, 20, 20, rng, buf_rows=11, buf_cols=11)
        assert b is not None
        r0, r1, c0, c1 = b["row0"], b["row1"], b["col0"], b["col1"]
        assert (tc[r0:r1, c0:c1] >= 50).all()
        assert not ly[r0 - 11:r1 + 11, c0 - 11:c1 + 11].any()
        assert b["min_treecover"] == 90
    assert pick_null_box(ly, tc, 200, 200, rng, 11, 11) is None            # box + buffer cannot fit
    ly[:, :] = 3
    assert pick_null_box(ly, tc, 20, 20, rng, 11, 11) is None              # loss everywhere


def test_box_sums_and_qualifying_offsets():
    m = np.zeros((4, 10), dtype=bool)
    m[:, 3:6] = True                           # a 4 x 3 solid block
    s = box_sums(m, 4, 4)
    assert s.shape == (1, 7)
    assert s[0].tolist() == [1, 2, 3, 3, 2, 1, 0]
    assert qualifying_offsets(m, 4, 4, 3).tolist() == [2, 3]
    assert qualifying_offsets(m, 4, 4, 13).tolist() == []


def test_rng_substreams_are_deterministic_and_independent():
    a, b = substream(20260918, 1), substream(20260918, 1)
    assert a.integers(0, 40000, 10).tolist() == b.integers(0, 40000, 10).tolist()
    c = substream(20260918, 2)
    assert substream(20260918, 1).integers(0, 40000, 10).tolist() != c.integers(0, 40000, 10).tolist()
    assert substream(1, 1).integers(0, 40000, 10).tolist() != substream(2, 1).integers(0, 40000, 10).tolist()


def test_geometry_helpers():
    assert pixel_ha(0.0) == pytest.approx(0.07746, abs=1e-4)
    assert pixel_ha(60.0) == pytest.approx(0.07746 / 2, abs=1e-4)
    assert tile_for(-55.0, -5.0) == "00N_060W"
    assert tile_for(15.0, 45.0) == "50N_010E"
    assert tile_for(-125.0, 45.0) == "50N_130W"
    assert tile_for(105.0, 55.0) == "60N_100E"
    assert tile_for(-55.0, -35.0) == "30S_060W"
    assert size_bucket(49.9) == "<50 ha" and size_bucket(50) == "50-150 ha" and size_bucket(150.1) == ">150 ha"
    assert mtbs_climate(-110.0, 40.0) == "dry"
    assert mtbs_climate(-122.0, 45.0) == "temperate"
    assert mtbs_climate(-150.0, 64.0) == "boreal"


def test_allowed_years_depends_on_today():
    import datetime as dt
    assert allowed_years(dt.date(2023, 12, 31)) == [2018, 2019, 2020, 2021, 2022]
    assert allowed_years(dt.date(2026, 9, 18)) == [2018, 2019, 2020, 2021, 2022, 2023]
