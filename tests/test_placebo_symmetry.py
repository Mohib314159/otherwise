"""CRITIQUE #4: every placebo unit must get the treated unit's donor procedure.

Pre-registered in DECISIONS.md. The defect was that the treated unit's donor pool
was an argmax over all candidates, chosen by minimising pre-period fit error on
the same pre-period the RMSPE ratio's denominator uses, while placebo units were
fitted on *that* pool with the treated unit's tuned ridge penalty. That made the
treated denominator optimistically small and every placebo's honest, inflating
the treated ratio and shrinking p.

The prediction recorded before implementing: symmetric placebos fit better, so
their ratios rise and p goes UP. These tests pin the direction, not a magnitude.
"""
import numpy as np
import pytest

from src.app.donors import select_donors
from src.app.estimator import fit_ascm, space_placebo
from src.app.run import _placebo_selector


def _panel(seed=0, n_cells=40, T=60, n_pre=44, effect=-0.30):
    """A treated cell with a real post-event drop, plus candidate cells that
    share a common seasonal signal and differ in noise level."""
    rng = np.random.default_rng(seed)
    t = np.arange(T)
    common = 0.55 + 0.12 * np.sin(2 * np.pi * t / 24.0)
    pre = np.zeros(T, dtype=bool); pre[:n_pre] = True
    cols = []
    for i in range(n_cells):
        noise = 0.004 + 0.02 * (i / n_cells)          # some cells track the common signal closely
        cols.append(common + rng.normal(0, noise, T) + rng.normal(0, 0.01))
    y = common + rng.normal(0, 0.008, T)
    y[~pre] += effect
    matrix = np.column_stack([y] + cols)
    return matrix, pre


def _run(matrix, pre, k=10, symmetric=True, max_units=40):
    donor_cov = np.ones(matrix.shape[1] - 1)
    sel = select_donors(matrix, pre, donor_cov, None, k=k)
    y = matrix[:, 0]
    pool = matrix[:, 1:].T
    D = pool[sel.index]
    f = fit_ascm(y, D, pre)
    point = float(np.mean(f.effect[~pre]))
    cell_of_col = np.arange(pool.shape[0])
    kw = {}
    if symmetric:
        kw = {"pool": pool, "select_for": _placebo_selector(pool, pre, cell_of_col, None, k)}
    return space_placebo(y, D, pre, f.lam, point, max_units=max_units, **kw)


def test_symmetric_flag_is_only_true_when_selection_is_re_run():
    matrix, pre = _panel()
    assert _run(matrix, pre, symmetric=True).symmetric is True
    assert _run(matrix, pre, symmetric=False).symmetric is False


def test_every_placebo_unit_re_selects_its_own_donors():
    """The selector must return a different pool for different units, and never
    include the unit itself."""
    matrix, pre = _panel()
    pool = matrix[:, 1:].T
    sel_for = _placebo_selector(pool, pre, np.arange(pool.shape[0]), None, k=10)
    pools = {}
    for j in (0, 5, 17, 31):
        idx = sel_for(j)
        assert j not in idx, "a placebo unit was offered itself as a donor"
        assert len(idx) == 10
        pools[j] = tuple(sorted(idx.tolist()))
    assert len(set(pools.values())) > 1, "every unit got the same pool; selection is not per-unit"


def _ratios_both_ways(seed, effect=-0.06, k=10, n_cells=40):
    """Placebo ratios for the SAME unit set under the old and new procedures.

    Holding the unit set fixed is essential: the fix also draws placebo units
    from the whole candidate pool instead of the treated unit's selected k, which
    changes the number of units and therefore the p-value's resolution (the
    smallest attainable p is 1/(units+1)). Comparing p directly would confound a
    resolution change with the bias being fixed.
    """
    from src.app.estimator import _ratio

    matrix, pre = _panel(seed=seed, effect=effect, n_cells=n_cells)
    donor_cov = np.ones(matrix.shape[1] - 1)
    sel = select_donors(matrix, pre, donor_cov, None, k=k)
    y = matrix[:, 0]
    pool = matrix[:, 1:].T
    f = fit_ascm(y, pool[sel.index], pre)
    sel_for = _placebo_selector(pool, pre, np.arange(pool.shape[0]), None, k)
    old, new_, old_pre, new_pre = [], [], [], []
    for j in sel.index:
        keep = np.array([i for i in sel.index if i != j])
        if len(keep) < 3:
            continue
        g_old = fit_ascm(pool[j], pool[keep], pre, lam=f.lam)       # treated's pool and lambda
        g_new = fit_ascm(pool[j], pool[sel_for(j)], pre, lam=None)  # its own pool and lambda
        old.append(_ratio(g_old.effect, pre)); new_.append(_ratio(g_new.effect, pre))
        old_pre.append(g_old.pre_rmse); new_pre.append(g_new.pre_rmse)
    return (np.asarray(old), np.asarray(new_), np.asarray(old_pre), np.asarray(new_pre))


def test_a_unit_fitted_on_its_own_donors_fits_better():
    """The mechanism behind the bias, with the unit set held fixed.

    The treated unit got an argmax over all candidates; placebo units got the
    treated unit's pool. So the treated pre-event RMSE was optimistically small
    and every placebo's was honest.
    """
    _, _, old_pre, new_pre = _ratios_both_ways(seed=0)
    better = int((new_pre < old_pre).sum())
    assert better >= 0.7 * len(old_pre), (
        f"own-pool fits were better for only {better}/{len(old_pre)} units")
    assert np.median(new_pre) < np.median(old_pre)


def test_symmetry_makes_placebo_units_harder_to_beat():
    """Conservative direction, as pre-registered in DECISIONS.md.

    Asserted on the placebo ratio rather than on p, because p saturates at its
    floor 1/(units+1) whenever the treated unit beats every placebo -- which it
    does in this panel at every effect size tested. A higher placebo ratio is
    what makes the treated unit harder to distinguish, i.e. the test gets
    stricter.
    """
    ups = 0
    for seed in range(6):
        old, new_, _, _ = _ratios_both_ways(seed=seed)
        ups += int(np.median(new_) > np.median(old))
    assert ups >= 5, f"placebo ratios rose on only {ups}/6 panels"


def test_symmetric_placebo_does_not_raise_the_false_alarm_rate():
    """The check in the other direction from the pre-registration: a panel with
    no real effect must not become MORE significant under the fix.

    Measured as a rate across seeds. A single panel's p is a rank statistic and
    moves in steps of 1/(units+1), so one seed says very little.
    """
    hits = 0
    ps = []
    for seed in range(12):
        matrix, pre = _panel(seed=seed, effect=0.0)
        p = _run(matrix, pre, symmetric=True).p_value
        ps.append(p)
        hits += int(p <= 0.05)
    assert hits == 0, f"{hits}/12 null panels reached p <= 0.05 (ps={np.round(ps, 3).tolist()})"
    assert np.mean(ps) > 0.25, f"mean null p only {np.mean(ps):.3f}"


def test_placebo_units_come_from_the_whole_candidate_pool():
    """Not just the treated unit's selected K: the reference distribution must not
    be drawn from units pre-selected for resembling the treated area."""
    matrix, pre = _panel(n_cells=40)
    sp = _run(matrix, pre, k=10, symmetric=True, max_units=40)
    assert len(sp.ratios) > 10, (
        f"only {len(sp.ratios)} placebo units; expected the full pool, not the selected k=10")


def test_too_few_candidates_degrades_gracefully():
    matrix, pre = _panel(n_cells=4)
    sp = _run(matrix, pre, k=3, symmetric=True)
    assert 0.0 < sp.p_value <= 1.0
