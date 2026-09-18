"""Offline tests for src/app/pixels.py: the numerical core and the map renderer."""
from __future__ import annotations

import numpy as np
import pytest

from src.app.pixels import (
    cell_fractions,
    cell_labels,
    change_threshold,
    changed_mask,
    composite,
    index_from_bands,
    placebo_p,
    render_change_map,
)


def test_threshold_matches_percentile_for_each_sign():
    rng = np.random.default_rng(0)
    d = rng.normal(0, 0.1, 10000)
    assert change_threshold(d, -1) == pytest.approx(np.percentile(d, 5))
    assert change_threshold(d, +1) == pytest.approx(np.percentile(d, 95))
    assert change_threshold(d, 0) == pytest.approx(np.percentile(np.abs(d), 95))
    # NaNs are ignored, an empty pool gives NaN
    assert change_threshold(np.r_[d, np.nan], -1) == pytest.approx(np.percentile(d, 5))
    assert np.isnan(change_threshold(np.array([np.nan]), -1))


def test_changed_mask_direction_and_nan():
    d = np.array([-0.5, -0.1, 0.0, 0.1, 0.5, np.nan])
    assert changed_mask(d, -0.2, -1).tolist() == [True, False, False, False, False, False]
    assert changed_mask(d, 0.2, +1).tolist() == [False, False, False, False, True, False]
    assert changed_mask(d, 0.2, 0).tolist() == [True, False, False, False, True, False]
    assert not changed_mask(d, np.nan, -1).any()


def _field(shift: float, seed: int = 3):
    """200x200 delta field: N(0, 0.05) noise, a 40x40 block shifted by `shift`.
    Control = outside the block dilated by 5 px, so the 40 px placebo cells
    around it keep >= 80 % control pixels while the corner cells drop out."""
    rng = np.random.default_rng(seed)
    delta = rng.normal(0, 0.05, (200, 200))
    area = np.zeros((200, 200), dtype=bool)
    area[80:120, 80:120] = True
    delta[area] += shift
    ring = np.zeros_like(area)
    ring[75:125, 75:125] = True
    control = ~ring
    return delta, area, control


def _run(delta, area, control, sign=-1):
    thr = change_threshold(delta[control], sign)
    changed = changed_mask(delta, thr, sign)
    frac = changed[area].mean()
    cf = cell_fractions(changed, control, cell_labels(delta.shape, 40))
    return frac, cf, placebo_p(cf, frac)


def test_shifted_block_is_detected():
    delta, area, control = _field(-0.4)
    frac, cf, p = _run(delta, area, control)
    assert frac > 0.9
    assert 15 <= cf.size <= 24
    assert p < 0.05


def test_null_field_flags_about_five_percent():
    delta, area, control = _field(0.0)
    frac, cf, p = _run(delta, area, control)
    assert 0.0 <= frac <= 0.15
    assert p > 0.2
    assert np.median(cf) == pytest.approx(0.05, abs=0.03)


def test_cell_labels_and_fraction_rule():
    lab = cell_labels((7, 9), 3)
    assert lab.shape == (7, 9) and lab.min() == 1
    assert lab[0, 0] == 1 and lab[0, 3] == 2 and lab[3, 0] == 4
    # a cell with fewer than 80 % control pixels is dropped
    changed = np.zeros((6, 6), dtype=bool)
    control = np.ones((6, 6), dtype=bool)
    control[:3, :3] = False
    control[3, 0] = False                       # cell 3 has 8/9 control pixels: kept
    changed[3, 1] = True
    cf = cell_fractions(changed, control, cell_labels((6, 6), 3))
    assert cf.size == 3
    assert sorted(cf.round(4).tolist()) == [0.0, 0.0, round(1 / 8, 4)]


def test_placebo_p_counts_with_plus_one():
    assert placebo_p(np.array([0.01, 0.02, 0.5, 0.7]), 0.4) == pytest.approx(3 / 5)
    assert placebo_p(np.array([0.01, 0.02]), 0.4) == pytest.approx(1 / 3)
    assert placebo_p(np.array([]), 0.4) is None


def test_composite_ignores_nan_and_counts():
    a = np.array([[1.0, np.nan], [3.0, np.nan]])
    b = np.array([[5.0, 2.0], [np.nan, np.nan]])
    c = np.array([[3.0, 4.0], [7.0, np.nan]])
    med, cnt = composite([a, b, c])
    assert med[0, 0] == 3.0 and med[0, 1] == 3.0 and med[1, 0] == 5.0
    assert np.isnan(med[1, 1])
    assert cnt.tolist() == [[3, 2], [2, 0]]


def test_index_formulas_match_s2():
    from src.app.s2 import indices_from_bands
    rng = np.random.default_rng(1)
    b = {k: rng.uniform(0.01, 0.5, (4, 4)).astype("float32") for k in ("B03", "B04", "B08", "B12")}
    ref = indices_from_bands(b["B03"], b["B04"], b["B08"], b["B12"])
    for k in ("NDVI", "NBR", "NDWI"):
        np.testing.assert_allclose(index_from_bands(k, b), ref[k])


def test_render_writes_640_png(tmp_path):
    from PIL import Image
    rng = np.random.default_rng(2)
    pre = rng.uniform(0.2, 0.8, (50, 50))
    pre[0, 0] = np.nan
    delta = rng.normal(0, 0.05, (50, 50))
    area = np.zeros((50, 50), dtype=bool)
    area[20:30, 20:30] = True
    delta[22:28, 22:28] = -0.5
    changed = delta < -0.2
    path = tmp_path / "x_change.png"
    render_change_map(pre, delta, changed, area, str(path))
    img = Image.open(path)
    assert img.size == (640, 640)
    arr = np.asarray(img.convert("RGB"))
    # centre of the block is painted in the decrease colour, blended at 85 %
    px = arr[25 * 640 // 50, 25 * 640 // 50]
    assert px[0] > px[1] + 60 and px[0] > px[2] + 60
    # the outline is white somewhere on the block's top edge
    assert (arr[20 * 640 // 50, 20 * 640 // 50 + 40] == 255).all()
