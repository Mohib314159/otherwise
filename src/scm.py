"""
Synthetic Control Method (Abadie, Diamond & Hainmueller).

The single treated field is reconstructed as a convex combination of donor
("business-as-usual") fields, with weights chosen to match the treated field's
PRE-treatment NDVI as closely as possible. The post-treatment gap between the
real field and this synthetic twin is the causal additionality estimate.

Why convex weights (w >= 0, sum = 1) and not free regression: it forbids
extrapolation. The counterfactual is an interpolation of real fields, so it
stays physically plausible and can't manufacture a fake baseline by
over-fitting with large +/- coefficients. That restraint is the whole point.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize


@dataclass
class SCMResult:
    weights: np.ndarray        # (m,) donor weights, >=0 sum 1
    synthetic: np.ndarray      # (T,) synthetic twin over the FULL period
    effect: np.ndarray         # (T,) target - synthetic  (+ = additionality)
    pre_rmse: float            # fit quality before treatment (lower = better)
    donor_ids: list[str]


def solve_weights(y_pre: np.ndarray, X_pre: np.ndarray) -> np.ndarray:
    """Find convex weights w minimising ||y_pre - X_pre @ w||^2.

    y_pre : (Tpre,)         target pre-treatment NDVI
    X_pre : (Tpre, m)       donor pre-treatment NDVI (columns = donors)

    Robust by design: SLSQP can fail to converge on highly collinear donors
    (neighbouring fields often are). If it reports failure or returns anything
    non-finite, we fall back to a transparent equal-weight average rather than
    silently feeding garbage into a verification tool.
    """
    m = X_pre.shape[1]
    w_equal = np.full(m, 1.0 / m)
    if not np.all(np.isfinite(y_pre)) or not np.all(np.isfinite(X_pre)):
        # caller should sanitise, but never let NaNs reach the optimiser
        return w_equal

    def loss(w: np.ndarray) -> float:
        r = y_pre - X_pre @ w
        return float(r @ r)

    def grad(w: np.ndarray) -> np.ndarray:
        return -2.0 * X_pre.T @ (y_pre - X_pre @ w)

    cons = ({"type": "eq", "fun": lambda w: np.sum(w) - 1.0,
             "jac": lambda w: np.ones_like(w)},)
    bounds = [(0.0, 1.0)] * m

    res = minimize(loss, w_equal, jac=grad, method="SLSQP", bounds=bounds,
                   constraints=cons, options={"maxiter": 500, "ftol": 1e-12})

    w = np.clip(res.x, 0.0, None) if res.x is not None else w_equal
    s = w.sum()
    w = w / s if s > 0 else w_equal
    # accept only a finite solution that beats the equal-weight baseline; else fall back
    if (not res.success) or (not np.all(np.isfinite(w))) or loss(w) > loss(w_equal) + 1e-9:
        return w_equal
    return w


def fit(target_ndvi: np.ndarray,
        donor_matrix: np.ndarray,
        pre_mask: np.ndarray,
        donor_ids: list[str]) -> SCMResult:
    """Fit a synthetic control.

    target_ndvi  : (T,)        treated field, full period (no NaNs — composite first)
    donor_matrix : (m, T)      donor fields, full period
    pre_mask     : (T,) bool   True for pre-treatment dates
    """
    y_pre = target_ndvi[pre_mask]
    X_pre = donor_matrix[:, pre_mask].T          # (Tpre, m)

    w = solve_weights(y_pre, X_pre)
    synthetic = donor_matrix.T @ w               # (T,)
    effect = target_ndvi - synthetic             # + means target greener than twin

    resid_pre = y_pre - X_pre @ w
    pre_rmse = float(np.sqrt(np.mean(resid_pre ** 2)))

    return SCMResult(weights=w, synthetic=synthetic, effect=effect,
                     pre_rmse=pre_rmse, donor_ids=donor_ids)
