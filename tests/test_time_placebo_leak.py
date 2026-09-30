"""In-time placebo leakage (DECISIONS.md, CRITIQUE #4 follow-up).

`time_placebos` fakes event dates inside the real pre-period. It used the
treated unit's donors, which were selected by pre-event similarity over the
WHOLE real pre-period -- including the window after each fake date, i.e. the
very window the fake-date test scores. Each fake date must now re-run donor
selection (same rules, same k) on data before that fake date only, and re-choose
its ridge penalty the same way.

All offline, seeded, small.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.app import run as runmod
from src.app.donors import select_donors
from src.app.estimator import fit_ascm, time_placebos
from src.app.prep import binned
from src.app.run import _analyse, _time_selector
from src.app.series import AreaData, SensorSeries
from src.app.verdict import ALPHA, MIN_EFFECT


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _panel(seed=0, n_donors=60, T=110, n_pre=75, noise=0.03):
    """Same construction as tests/test_redteam.py: one seasonal curve shared by
    every unit (own amplitude and offset), 10-day observations, no effect."""
    rng = np.random.default_rng(seed)
    t = np.arange(T)
    season = 0.2 * np.sin(2 * math.pi * t / 36.5)
    amp = rng.uniform(0.8, 1.2, n_donors + 1)
    off = rng.normal(0, 0.05, n_donors + 1)
    V = 0.5 + season[:, None] * amp[None, :] + off[None, :] + rng.normal(0, noise, (T, n_donors + 1))
    dates = np.datetime64("2020-01-01") + (t * 10).astype("timedelta64[D]")
    return dates, V, dates[n_pre]


def _add_pretrend(dates, V, ev):
    """-0.2 NDVI/yr drift in the treated unit from one year before the event."""
    t = np.arange(len(dates)); n_pre = int(np.sum(dates < ev))
    V[:, 0] += np.clip((t - n_pre) * 10 + 365, 0, None) * (-0.2) / 365.0
    return V


def _both(dates, V, ev, k=20, min_effect=MIN_EFFECT["NDVI"]):
    """Fake-date flags under the old (leaky) and new (re-selected) procedures,
    on identical data and identical fake dates."""
    b = binned(dates, V, ev, bin_days=10)
    sel = select_donors(b.matrix, b.pre, b.donor_cov, None, k=k)
    y = b.matrix[:, 0]
    pool = b.matrix[:, 1:].T
    D = pool[sel.index]
    f = fit_ascm(y, D, b.pre)
    old = time_placebos(y, D, b.pre, f.lam, n=3, min_effect=min_effect, alpha=ALPHA)
    new = time_placebos(y, D, b.pre, None, n=3, min_effect=min_effect, alpha=ALPHA,
                        pool=pool, select_at=_time_selector(b.matrix, b.donor_cov, None, k))
    return old, new


def _trap_panel(T=100, n_pre=80, n_honest=30, n_trap=5, first_cut=20, seed=0):
    """Treated series plus two kinds of candidate:

    * honest donors: the common signal with their own noise, similar throughout;
    * trap donors: a copy of the treated series from `first_cut` onward, but
      offset by 0.04 before it. They match the treated unit ONLY after the
      first fake date.

    Over the whole real pre-period a trap's RMSE (~0.02) beats an honest
    donor's (~0.028), so whole-window selection prefers traps. On the window
    before the first fake date a trap's RMSE is 0.04, so it must lose.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(T)
    common = 0.55 + 0.12 * np.sin(2 * np.pi * t / 36.5)
    y = common + rng.normal(0, 0.02, T)
    honest = [common + rng.normal(0, 0.02, T) for _ in range(n_honest)]
    traps = []
    for _ in range(n_trap):
        c = y + rng.normal(0, 0.001, T)
        c[:first_cut] += 0.04
        traps.append(c)
    matrix = np.column_stack([y] + honest + traps)
    pre = np.zeros(T, dtype=bool); pre[:n_pre] = True
    trap_rows = np.arange(n_honest, n_honest + n_trap)
    return matrix, pre, trap_rows


# ---------------------------------------------------------------------------
# (1) selection for a fake date only sees data before the fake date
# ---------------------------------------------------------------------------
def test_trap_panel_is_a_real_trap_for_whole_window_selection():
    """Guard for the test below: the old, whole-pre-period selection DOES
    prefer the donors that only match after the fake date."""
    matrix, pre, trap_rows = _trap_panel()
    sel = select_donors(matrix, pre, np.ones(matrix.shape[1] - 1), None, k=5)
    assert set(sel.index.tolist()) == set(trap_rows.tolist())


def test_fake_date_selection_ignores_donors_that_match_only_after_it():
    matrix, pre, trap_rows = _trap_panel(first_cut=20)
    y = matrix[:, 0]
    pool = matrix[:, 1:].T
    D = pool[select_donors(matrix, pre, np.ones(pool.shape[0]), None, k=5).index]
    base = _time_selector(matrix, np.ones(pool.shape[0]), None, 5)
    seen = []

    def spy(mask):
        rows = base(mask)
        seen.append((mask.copy(), np.asarray(rows)))
        return rows

    tp = time_placebos(y, D, pre, None, n=3, pool=pool, select_at=spy)
    assert len(tp) == 3 and len(seen) == 3
    idx = np.where(pre)[0]
    for (mask, rows), t in zip(seen, tp):
        # the selector saw exactly the periods before this fake date, nothing else
        assert mask.sum() == int(np.sum(idx < t.fake_index))
        assert not mask[t.fake_index:].any()
        assert np.array_equal(np.where(mask)[0], idx[idx < t.fake_index])
    # first fake date is bin 20: the traps must not be chosen there
    first_mask, first_rows = seen[0]
    assert tp[0].fake_index == 20
    assert not set(first_rows.tolist()) & set(trap_rows.tolist()), (
        "a donor matching the treated unit only after the fake date was selected")


def test_fake_date_selection_is_invariant_to_data_after_the_fake_date():
    """Scramble every value at or after a fake date: the donors chosen for that
    fake date must not change."""
    dates, V, ev = _panel(seed=3)
    b = binned(dates, V, ev, bin_days=10)
    idx = np.where(b.pre)[0]
    cut = int(len(idx) * 1 / 4)
    mask = np.zeros(len(b.pre), dtype=bool); mask[idx[:cut]] = True
    rows = _time_selector(b.matrix, b.donor_cov, None, 20)(mask)
    scrambled = b.matrix.copy()
    rng = np.random.default_rng(99)
    scrambled[idx[cut]:, :] = rng.normal(0, 1, scrambled[idx[cut]:, :].shape)
    rows2 = _time_selector(scrambled, b.donor_cov, None, 20)(mask)
    assert np.array_equal(rows, rows2)


def test_fake_dates_are_placed_exactly_as_before():
    dates, V, ev = _panel(seed=1)
    old, new = _both(dates, V, ev)
    assert [t.fake_index for t in old] == [t.fake_index for t in new]
    assert len(new) == 3


# ---------------------------------------------------------------------------
# (2) null false-alarm rate (sanity) and pre-trend power
# ---------------------------------------------------------------------------
def test_null_flag_rate_at_the_production_threshold_stays_near_zero():
    """With the verdict's MIN_EFFECT gate, null panels should essentially never
    flag, under either procedure. Measured offline over 200 seeds (600 fake-date
    tests): old 0, new 1 -- see DECISIONS.md. Here 12 seeds, with a tolerance
    of one flag so a single borderline seed does not break the build."""
    old_n = new_n = 0
    for seed in range(12):
        old, new = _both(*_panel(seed=seed))
        old_n += sum(t.flagged for t in old); new_n += sum(t.flagged for t in new)
    assert new_n <= old_n + 1, f"null flags rose from {old_n} to {new_n} of 36"
    assert new_n <= 1


def test_raw_null_rate_without_the_effect_gate_is_only_slightly_higher():
    """Without the MIN_EFFECT gate the conformal interval alone decides. The
    leaky procedure fitted the fake post-window on donors partly chosen for it,
    so it flagged LESS often than an honest procedure should; a small rise here
    is the leak being removed, not a new false alarm source. Offline over 200
    seeds: old 14.0%, new 17.2% (DECISIONS.md). Bounded here so a large jump
    (a broken selection) is caught."""
    old_n = new_n = 0
    for seed in range(12):
        old, new = _both(*_panel(seed=seed), min_effect=0.0)
        old_n += sum(t.flagged for t in old); new_n += sum(t.flagged for t in new)
    assert new_n <= old_n + 4, f"raw null flags rose from {old_n} to {new_n} of 36"
    assert new_n / 36 <= 0.30


def test_pretrend_is_still_flagged():
    """A drift beginning a year before the claimed date must still be caught
    (same construction as tests/test_redteam.py's E5 panel)."""
    fired = 0
    for seed in range(6):
        dates, V, ev = _panel(seed=seed)
        V = _add_pretrend(dates, V, ev)
        _, new = _both(dates, V, ev)
        fired += int(any(t.flagged for t in new))
        if seed == 0:
            assert sum(t.flagged for t in new) >= 2
    assert fired == 6, f"pre-trend flagged on only {fired}/6 panels"


# ---------------------------------------------------------------------------
# (3) the procedure is recorded
# ---------------------------------------------------------------------------
def test_reselected_flag_on_time_placebo_results():
    old, new = _both(*_panel(seed=0))
    assert all(t.reselected for t in new)
    assert not any(t.reselected for t in old)


def test_analyse_records_time_placebo_reselected_in_chart():
    dates, V, ev = _panel(seed=0)
    out = _analyse(dates, V, ev, np.arange(V.shape[1] - 1), None, "NDVI", "S2", -1,
                   lambda *a: None, donor_k=20)
    assert out is not None
    res, chart, _ = out
    assert chart["time_placebo_reselected"] is True
    assert len(chart["time_placebos"]) == 3
    assert len(res.time_placebo_flags) == 3


def test_run_verdict_json_records_time_placebo_reselected(monkeypatch):
    """End to end through run_verdict with the fetch stubbed out (no network)."""
    dates, V, ev = _panel(seed=0, T=150, n_pre=110)
    n_cells = V.shape[1] - 1
    str_dates = np.array([str(d) for d in dates])
    s2 = SensorSeries("S2", str_dates, {"NDVI": V}, [f"scene{i}" for i in range(len(dates))])
    cell = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1e-3], [1e-3, 1e-3], [0, 0]]]}
    data = AreaData(area_geojson={}, area_ha=10.0, epsg=32630, cells_geojson=[cell] * n_cells,
                    cell_distance_m=[1000.0] * n_cells, start="", end="", s2=s2, s1=None,
                    receipts=[], summary={}, timing={})

    def no_net(*a, **kw):
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(runmod, "fetch_area", lambda *a, **kw: data)
    monkeypatch.setattr(runmod, "fetch_covariates", no_net)
    area = {"type": "Polygon", "coordinates": [[[-1.29, 52.9], [-1.2854, 52.9], [-1.2854, 52.9028],
                                                [-1.29, 52.9028], [-1.29, 52.9]]]}
    out = runmod.run_verdict(area, str(ev), change_type="clearing", post_months=12,
                             save=False, mode="ring")
    assert "NDVI" in out["signals"]
    assert out["signals"]["NDVI"]["time_placebo_reselected"] is True
    assert out["charts"]["NDVI"]["time_placebo_reselected"] is True
