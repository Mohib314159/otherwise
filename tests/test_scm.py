"""SCM solver correctness."""
import numpy as np
from src.scm import solve_weights, fit


def test_weights_are_convex():
    rng = np.random.default_rng(0)
    X = rng.random((20, 5))
    y = rng.random(20)
    w = solve_weights(y, X)
    assert np.all(w >= -1e-9)
    assert abs(w.sum() - 1.0) < 1e-6


def test_recovers_identical_donor():
    # target pre exactly equals donor 0 -> weight should concentrate on donor 0
    rng = np.random.default_rng(1)
    d0 = rng.random(30)
    X = np.column_stack([d0, rng.random(30), rng.random(30)])
    w = solve_weights(d0.copy(), X)
    assert w[0] > 0.95


def test_recovers_known_linear_combo():
    rng = np.random.default_rng(2)
    d0, d1 = rng.random(40), rng.random(40)
    target = 0.6 * d0 + 0.4 * d1
    X = np.column_stack([d0, d1])
    w = solve_weights(target, X)
    assert abs(w[0] - 0.6) < 0.03 and abs(w[1] - 0.4) < 0.03


def test_fit_effect_sign_is_target_minus_synthetic():
    # target sits ABOVE donors post-treatment -> effect must be positive
    T = 24
    pre = np.arange(T) < 12
    donors = np.vstack([np.full(T, 0.3), np.full(T, 0.3)])
    target = np.full(T, 0.3)
    target[~pre] = 0.5  # jump up after treatment
    res = fit(target, donors, pre, ["a", "b"])
    assert res.effect[~pre].mean() > 0.15
    assert res.pre_rmse < 1e-6
