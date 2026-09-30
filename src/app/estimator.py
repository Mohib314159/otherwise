"""Augmented synthetic control with conformal inference.

Why not the hackathon estimator alone: with ~20 donors and 24 monthly steps the
Abadie permutation p-value floors at 0.048 and the answer is a binary rank. Here:

* **Augmented SCM** (Ben-Michael, Feller & Rothstein 2021). Convex SCM weights
  from `src/scm.py`, plus a ridge correction for whatever the convex fit could
  not match in the pre-period. Reduces bias when the donor pool is large and
  noisy, which is exactly the app's situation.
* **Conformal inference** (Chernozhukov, Wuthrich & Zhu 2021). To test "the
  average post-event effect equals theta0", subtract theta0 from the treated
  post-event outcomes, refit on all periods, and compare the post-period
  residual size with the same statistic on every cyclic block shift of the
  residual sequence. Inverting the test over theta0 gives a confidence interval
  for the average effect. No parametric noise model, valid with one treated unit.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import nnls

from ..scm import solve_weights as solve_weights_slsqp


def solve_weights(y_pre: np.ndarray, X_pre: np.ndarray) -> np.ndarray:
    """Convex weights (w >= 0, sum w = 1) minimising ||y_pre - X_pre w||^2.

    Same problem as `scm.solve_weights`, solved as non-negative least squares
    with a heavily weighted row enforcing the sum-to-one constraint, then
    normalised. On real data it returns the same loss as SLSQP in ~1 ms instead
    of ~2 s, which is what makes hundreds of placebo refits affordable.
    """
    m = X_pre.shape[1]
    if not np.all(np.isfinite(y_pre)) or not np.all(np.isfinite(X_pre)) or m == 0:
        return np.full(max(m, 1), 1.0 / max(m, 1))
    c = 10.0 * float(np.abs(y_pre).max()) + 1.0
    A = np.vstack([X_pre, c * np.ones((1, m))])
    b = np.concatenate([y_pre, [c]])
    try:
        w, _ = nnls(A, b, maxiter=50 * m)
    except Exception:
        return solve_weights_slsqp(y_pre, X_pre)
    s = w.sum()
    if not np.isfinite(s) or s <= 0:
        return solve_weights_slsqp(y_pre, X_pre)
    return w / s


@dataclass
class Fit:
    weights: np.ndarray            # (m,) convex weights
    eta: np.ndarray                # (Tpre, T) ridge coefficients, or zeros
    synthetic: np.ndarray          # (T,) counterfactual, augmented
    synthetic_scm: np.ndarray      # (T,) plain convex SCM counterfactual
    effect: np.ndarray             # (T,) observed - counterfactual
    pre_rmse: float
    lam: float


def _ridge_eta(X_pre: np.ndarray, Y: np.ndarray, lam: float) -> np.ndarray:
    """X_pre: (m, Tpre) donors' pre outcomes; Y: (m, T). eta: (Tpre, T)."""
    Xc = X_pre - X_pre.mean(axis=0, keepdims=True)
    Yc = Y - Y.mean(axis=0, keepdims=True)
    A = Xc.T @ Xc + lam * np.eye(Xc.shape[1])
    return np.linalg.solve(A, Xc.T @ Yc)


def fit_ascm(y: np.ndarray, D: np.ndarray, pre: np.ndarray, lam: float | None = None) -> Fit:
    """y: (T,) treated; D: (m, T) donors; pre: (T,) bool. All finite.

    lam=None picks the ridge penalty by holding out the last 25% of the
    pre-period: fit on the first 75%, choose the lam with the smallest holdout
    error. lam=0 gives plain convex SCM.
    """
    T = y.shape[0]
    m = D.shape[0]
    X_pre = D[:, pre]                              # (m, Tpre)
    w = solve_weights(y[pre], X_pre.T)
    synth_scm = D.T @ w
    if lam is None:
        lam = _choose_lambda(y, D, pre)
    if lam <= 0 or m < 3:
        eta = np.zeros((int(pre.sum()), T))
        synth = synth_scm
    else:
        scale = np.trace(X_pre.T @ X_pre) / max(X_pre.shape[1], 1)
        eta = _ridge_eta(X_pre, D, lam * scale)
        resid_pre = y[pre] - X_pre.T @ w            # what the convex fit missed
        synth = synth_scm + resid_pre @ eta
    effect = y - synth
    pre_rmse = float(np.sqrt(np.mean(effect[pre] ** 2)))
    return Fit(w, eta, synth, synth_scm, effect, pre_rmse, float(lam))


def _choose_lambda(y, D, pre, grid=(0.0, 0.03, 0.1, 0.3, 1.0, 3.0)) -> float:
    idx = np.where(pre)[0]
    if len(idx) < 12:
        return 0.3
    cut = idx[int(len(idx) * 0.75)]
    train = pre.copy(); train[cut:] = False
    hold = pre & ~train
    best, best_err = 0.3, np.inf
    for lam in grid:
        f = fit_ascm(y, D, train, lam=lam)
        err = float(np.sqrt(np.mean(f.effect[hold] ** 2)))
        if err < best_err - 1e-12:
            best, best_err = lam, err
    return best


# ---------------------------------------------------------------------------
# Conformal inference
# ---------------------------------------------------------------------------
def _stat(u_post: np.ndarray) -> float:
    """Absolute mean of the post-event residuals.

    The interval is for the AVERAGE post-event effect. With an RMS statistic the
    sharp null (same shift every period) is rejected for every constant when the
    real effect varies in time (a clearing that regrows, a construction site that
    keeps changing), and the interval collapses. The absolute mean tests exactly
    the quantity we report and stays valid when the effect varies.
    """
    return float(abs(np.mean(u_post)))


def conformal_p(y: np.ndarray, D: np.ndarray, pre: np.ndarray, theta0: float,
                lam: float, block: int | None = None) -> float:
    """p-value for H0: mean post effect == theta0 (moving-block permutations)."""
    post = ~pre
    y0 = y.copy()
    y0[post] -= theta0
    all_pre = np.ones_like(pre)                     # under H0 every period is "pre"
    f = fit_ascm(y0, D, all_pre, lam=lam)
    u = f.effect
    T = len(u)
    q = int(post.sum())
    s_obs = _stat(u[post])
    # cyclic block shifts of the residual sequence, evaluated on q-length windows
    stats = []
    for shift in range(T):
        idx = (np.arange(q) + shift) % T
        stats.append(_stat(u[idx]))
    stats = np.asarray(stats)
    return float(np.mean(stats >= s_obs - 1e-12))


@dataclass
class Conformal:
    point: float
    lo: float
    hi: float
    alpha: float
    p_zero: float                  # p-value for "no effect"
    grid: np.ndarray
    pvals: np.ndarray
    boundary_hit: bool = False     # accepted set reaches numerical search boundary
    accepted_empty: bool = False   # no theta accepted on the searched grid


def conformal_interval(y, D, pre, lam: float, point: float, scale: float,
                       alpha: float = 0.10, n_grid: int = 41, span: float = 4.0,
                       max_half: float | None = None, ensure_zero: bool = False,
                       max_widen: int = 4) -> Conformal:
    """Invert the conformal test over a grid of candidate average effects.

    Defaults preserve the original land/radar behaviour.  Domains with larger
    physical units (for example NO₂ in µg/m³) can provide ``max_half`` and
    ``ensure_zero=True`` so the numerical search does not silently truncate a
    scientifically plausible interval. ``boundary_hit`` is returned explicitly
    so a caller can abstain rather than mistake a search ceiling for evidence.
    """
    half = max(span * scale, 1e-3)
    if ensure_zero:
        # The grid must span the no-effect value with some margin.
        half = max(half, abs(float(point)) + max(float(scale), 0.5))
    if max_half is None:
        max_half = 1.0 if scale < 0.3 else 10.0
    max_half = max(float(max_half), half)

    acc = np.array([], dtype=float)
    grid = np.linspace(point - half, point + half, n_grid)
    pv = np.array([conformal_p(y, D, pre, th, lam) for th in grid])
    boundary_hit = False
    for _ in range(max(1, int(max_widen))):
        acc = grid[pv > alpha]
        if acc.size:
            eps = max(abs(grid[1] - grid[0]), 1e-12) * 0.51
            left = acc.min() <= grid[0] + eps
            right = acc.max() >= grid[-1] - eps
            boundary_hit = bool(left or right)
            if not boundary_hit:
                break
        else:
            boundary_hit = False
        if half >= max_half - 1e-12:
            break
        half = min(half * 3.0, max_half)
        grid = np.linspace(point - half, point + half, n_grid)
        pv = np.array([conformal_p(y, D, pre, th, lam) for th in grid])

    accepted_empty = bool(acc.size == 0)
    if accepted_empty:
        lo = hi = point
    else:
        lo, hi = float(acc.min()), float(acc.max())
        step = grid[1] - grid[0]
        lo, hi = lo - step / 2, hi + step / 2
    p0 = conformal_p(y, D, pre, 0.0, lam)
    return Conformal(point, lo, hi, alpha, p0, grid, pv, boundary_hit, accepted_empty)


# ---------------------------------------------------------------------------
# Placebos
# ---------------------------------------------------------------------------
@dataclass
class SpacePlacebo:
    p_value: float                     # rank of the treated RMSPE ratio among donors
    p_effect: float                    # share of donors with a post effect at least as large (same sign)
    treated_ratio: float
    ratios: np.ndarray
    effects: np.ndarray                # mean post effect of each donor treated as if it were the area
    pre_rmses: np.ndarray
    effect_series: np.ndarray          # (units, T) effect path of each placebo unit
    symmetric: bool = False            # True when every placebo unit re-ran donor selection


def _ratio(effect, pre):
    return float(np.sqrt(np.mean(effect[~pre] ** 2)) / (np.sqrt(np.mean(effect[pre] ** 2)) + 1e-9))


def space_placebo(y, D, pre, lam: float, treated_effect: float, max_units: int = 60,
                  pool: np.ndarray | None = None, select_for=None,
                  retune_lambda: bool = True) -> SpacePlacebo:
    """Each candidate cell becomes the 'treated' unit, under the IDENTICAL procedure.

    y: (T,) treated; D: (m, T) the treated unit's selected donors; pre: (T,) bool.

    `pool` is the full candidate set (n, T) the treated unit's donors were chosen
    from, and `select_for(j)` returns the donors that unit j gets when the same
    selection procedure is applied to it -- its own pre-event ranking, its own
    land cover and elevation, the same k. Both must be supplied together.

    Why this matters (CRITIQUE.md issue 4, pre-registered in DECISIONS.md): the
    treated unit's pool is an argmax over n candidates, chosen by minimising
    pre-period fit error on the very pre-period the RMSPE ratio's denominator is
    computed from. Fitting placebo units on *that* pool, with the treated unit's
    tuned ridge penalty, left the treated denominator optimistically small and
    every placebo's honest, which inflated the treated ratio and shrank p. The
    placebo test was anti-conservative on every run.

    Without `pool`/`select_for` the old, asymmetric behaviour is used. That path
    exists only for the offline diagnostic scripts that have no candidate set to
    hand; it reports `symmetric=False` so a result computed that way is never
    mistaken for a symmetric one.
    """
    f = fit_ascm(y, D, pre, lam=lam)
    t_ratio = _ratio(f.effect, pre)
    symmetric = pool is not None and select_for is not None
    units_src = pool if symmetric else D
    n = units_src.shape[0]
    units = np.arange(n) if n <= max_units else np.linspace(0, n - 1, max_units).round().astype(int)
    ratios, effects, pres, paths = [], [], [], []
    for j in units:
        if symmetric:
            idx = select_for(int(j))
            if idx is None or len(idx) < 3:
                continue                      # too few valid controls for this unit
            Dj = pool[idx]
            lam_j = None if retune_lambda else lam
        else:
            keep = np.ones(n, dtype=bool); keep[j] = False
            Dj = D[keep]
            lam_j = lam
        g = fit_ascm(units_src[j], Dj, pre, lam=lam_j)
        ratios.append(_ratio(g.effect, pre))
        effects.append(float(np.mean(g.effect[~pre])))
        pres.append(g.pre_rmse)
        paths.append(g.effect)
    if not ratios:                            # no placebo unit could be fitted
        empty = np.zeros(0)
        return SpacePlacebo(1.0, 1.0, t_ratio, empty, empty, empty,
                            np.zeros((0, len(y))), symmetric)
    ratios, effects, pres = map(np.asarray, (ratios, effects, pres))
    p = (np.sum(ratios >= t_ratio) + 1) / (len(ratios) + 1)
    sign = np.sign(treated_effect) if treated_effect != 0 else 1.0
    p_eff = (np.sum(sign * effects >= sign * treated_effect) + 1) / (len(effects) + 1)
    return SpacePlacebo(float(p), float(p_eff), t_ratio, ratios, effects, pres,
                        np.vstack(paths), symmetric)


@dataclass
class TimePlacebo:
    fake_index: int
    effect: float
    lo: float
    hi: float
    flagged: bool
    reselected: bool = False       # donors and lambda re-chosen from data before the fake date only


def time_placebos(y, D, pre, lam: float | None, n: int = 3, min_effect: float = 0.0,
                  alpha: float = 0.10, pool: np.ndarray | None = None,
                  select_at=None) -> list[TimePlacebo]:
    """Pretend the event happened at fake dates inside the pre-period, using
    only pre-period data. A method that 'finds' effects here is not trustworthy.

    `pool` (n, T) is the full candidate set the treated unit's donors `D` were
    chosen from, and `select_at(mask)` returns row indices into `pool`: the
    donors the treated unit gets when the SAME selection procedure (same
    filters, same k, same relaxation) ranks candidates on the periods in `mask`
    (a (T,) bool) only. Both must be supplied together.

    Why (DECISIONS.md, CRITIQUE #4 follow-up): `D` was selected by pre-event
    similarity over the WHOLE real pre-period, which includes the window after
    each fake date -- the window the fake-date test is scoring. So the fake
    "post" period was already fitted well by construction, flattering the
    fake-date fit and hiding false alarms. With `pool`/`select_at`, each fake
    date re-selects donors on the fake pre-window alone and re-chooses its own
    ridge penalty (lam=None) by the usual holdout inside that window, mirroring
    `space_placebo`'s symmetric path. Fake dates are placed exactly as before.

    Without them the old (leaky) behaviour is used, with the given `lam`, and
    every result reports `reselected=False`.
    """
    idx = np.where(pre)[0]
    Tpre = len(idx)
    out = []
    if Tpre < 24:
        return out
    reselect = pool is not None and select_at is not None
    yy = y[idx]
    for k in range(1, n + 1):
        cut = int(Tpre * k / (n + 1))
        fake_pre = np.zeros(Tpre, dtype=bool); fake_pre[:cut] = True
        if reselect:
            mask = np.zeros(len(y), dtype=bool); mask[idx[:cut]] = True
            rows = select_at(mask)
            if rows is None or len(rows) < 3:
                continue                      # too few valid controls before this fake date
            DD = pool[np.asarray(rows)][:, idx]
            lam_k = None
        else:
            DD = D[:, idx]
            lam_k = lam
        f = fit_ascm(yy, DD, fake_pre, lam=lam_k)
        point = float(np.mean(f.effect[~fake_pre]))
        ci = conformal_interval(yy, DD, fake_pre, f.lam, point, f.pre_rmse, alpha=alpha, n_grid=21)
        flagged = bool((ci.lo > 0 or ci.hi < 0) and abs(point) >= min_effect)
        out.append(TimePlacebo(int(idx[cut]), point, ci.lo, ci.hi, flagged, reselect))
    return out
