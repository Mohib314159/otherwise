"""Verdict logic — every state, including the honest INCONCLUSIVE."""
import numpy as np
from src.audit import decide

# helper: build masks/effect for a post-only off-season effect value
def _mk(effect_value, pre_rmse=0.02):
    T = 24
    post = np.zeros(T, bool); post[12:] = True
    os_post = np.zeros(T, bool); os_post[12:] = True
    eff = np.zeros(T); eff[os_post] = effect_value
    return eff, post, os_post, pre_rmse


def test_flat_claim_is_rejected():
    eff, post, osp, r = _mk(0.0)
    v = decide("F", eff, post, osp, p_value=0.6, confidence=40, pre_rmse=r,
               claims_adoption=True)
    assert v.status == "REJECTED"


def test_strong_significant_is_verified():
    eff, post, osp, r = _mk(0.15)
    v = decide("F", eff, post, osp, p_value=0.02, confidence=98, pre_rmse=r,
               claims_adoption=True)
    assert v.status == "VERIFIED"


def test_significant_below_claim_is_partial():
    eff, post, osp, r = _mk(0.10)
    v = decide("F", eff, post, osp, p_value=0.02, confidence=98, pre_rmse=r,
               claims_adoption=True, claimed_rate_tco2e_ha=3.0, est_rate_tco2e_ha=0.5)
    assert v.status == "PARTIAL"


def test_signal_but_not_significant_is_inconclusive():
    eff, post, osp, r = _mk(0.06)
    v = decide("F", eff, post, osp, p_value=0.12, confidence=88, pre_rmse=r,
               claims_adoption=True)
    assert v.status == "INCONCLUSIVE"


def test_bad_prefit_is_inconclusive():
    eff, post, osp, _ = _mk(0.15, pre_rmse=0.09)
    v = decide("F", eff, post, osp, p_value=0.02, confidence=98, pre_rmse=0.09,
               claims_adoption=True)
    assert v.status == "INCONCLUSIVE"


def test_flat_no_claim_is_baseline():
    eff, post, osp, r = _mk(0.0)
    v = decide("F", eff, post, osp, p_value=0.6, confidence=40, pre_rmse=r,
               claims_adoption=False)
    assert v.status == "BASELINE"
