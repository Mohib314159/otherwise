"""CRITIQUE #9: the power table must count what the product's verdict says.

scripts/power.py used to call a unit 'detected' on interval + minimum effect +
placebo p alone. These tests pin that it now builds the product's SignalResult
(run.signal_result, the helper run._analyse uses) and counts verdict.combine's
status, so a unit the old gate passed but the pre-fit gate blocks is CAN'T TELL.
Small synthetic panels, no network, no cache.
"""
import numpy as np
import pytest

from scripts import power
from src.app.verdict import decide


def _panel(seed=0, n_cells=30, T=110, noisy_sd=0.05):
    """30 control cells sharing a seasonal signal with little noise; cell 1 is
    far noisier, so its pre-event fit is poor next to the other cells'."""
    rng = np.random.default_rng(seed)
    dates = np.datetime64("2020-01-01") + np.arange(T) * 10
    t = np.arange(T)
    common = 0.55 + 0.12 * np.sin(2 * np.pi * t / 36.5)
    cells = [common + rng.normal(0, 0.006, T) + rng.normal(0, 0.01) for _ in range(n_cells)]
    V = np.column_stack([np.full(T, np.nan)] + cells)
    V[:, 1] = common + rng.normal(0, noisy_sd, T)
    return dates, V


def _unit(dates, V, u, eff):
    event = np.datetime64(dates[int(len(dates) * 0.7)])
    cols = [u] + [c for c in range(1, V.shape[1]) if c != u]
    M = V[:, cols].copy()
    M[dates >= event, 0] += eff
    return event, M


def test_poor_prefit_unit_passes_old_gate_but_verdict_says_cant_tell():
    dates, V = _panel()
    event, M = _unit(dates, V, 1, -0.10)
    status, res, old = power.judge_unit(dates, M, event, "NDVI", -0.10)
    assert old is True                       # the old three-condition gate called it detected
    assert not res.pre_fit_ok                # ...but the pre-fit gate blocks it
    assert status == "CANT_TELL"
    assert status == decide(res, "other", "x").status
    assert any("does not track" in r for r in decide(res, "other", "x").reasons)


def test_evaluate_counts_the_verdict_status_not_the_old_gate():
    dates, V = _panel()
    # unit 1 is the poor-fit cell; unit 2 is an ordinary, well-fitted cell
    rows = power.evaluate(V, dates, "NDVI", effects=(-0.10,), units=np.array([1, 2]), log=lambda *a: None)
    r = rows[0]
    assert r["n"] == 2
    assert r["old_gate_detected"] == 2
    assert r["detected"] == 1 and r["cant_tell"] == 1 and r["not_real"] == 0
    assert r["rate"] == 0.5
    # the published shape keeps its fields and gains not_real
    for k in ("detected", "cant_tell", "n", "rate", "not_real", "symmetric_placebo"):
        assert k in r


def test_null_row_counts_not_real():
    dates, V = _panel()
    rows = power.evaluate(V, dates, "NDVI", effects=(0.0,), units=np.array([2, 3]), log=lambda *a: None)
    r = rows[0]
    assert r["detected"] + r["not_real"] + r["cant_tell"] == r["n"] == 2
    assert r["detected"] == 0


def test_thin_unit_is_cant_tell():
    dates, V = _panel(n_cells=15)            # < 21 columns after binning
    event, M = _unit(dates, V, 2, -0.2)
    status, res, old = power.judge_unit(dates, M, event, "NDVI", -0.2)
    assert (status, res, old) == ("CANT_TELL", None, False)


@pytest.mark.parametrize("sig", ["VH", "VV", "vh"])
def test_radar_defaults_are_db(sig):
    assert power.default_effects(sig) == (0.0, -0.5, -1.0, -2.0)
    cache, s, effects, modes = power.parse_args(["data/cache/x/", sig])
    assert effects == (0.0, -0.5, -1.0, -2.0)
    assert modes == [True, False]


def test_optical_defaults_unchanged_and_explicit_effects_win():
    assert power.default_effects("NDVI") == (0.0, -0.05, -0.10, -0.20)
    assert power.parse_args([])[2] == (0.0, -0.05, -0.10, -0.20)
    _, _, effects, modes = power.parse_args(["c/", "VH", "--effects=0,-3", "--asymmetric"])
    assert effects == (0.0, -3.0) and modes == [False]
