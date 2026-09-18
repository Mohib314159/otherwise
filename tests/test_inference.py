"""Inference: placebo p-value behaviour and Benjamini-Hochberg FDR control."""
import numpy as np
from src.inference import benjamini_hochberg
from src.synth_data import generate
from src.pipeline import audit_all_claims, fdr_significant


def test_bh_is_never_more_permissive_than_raw():
    rng = np.random.default_rng(0)
    p = rng.random(50)
    assert benjamini_hochberg(p, 0.05).sum() <= (p < 0.05).sum()


def test_bh_admits_clearly_significant_when_resolution_is_adequate():
    p = [0.0004, 0.001, 0.002, 0.003, 0.04, 0.3, 0.7]
    keep = benjamini_hochberg(p, 0.05)
    assert keep[:4].all()          # the four tiny p-values survive
    assert not keep[4:].any()      # the rest do not


def test_bh_empty_and_none_pass():
    assert benjamini_hochberg([], 0.05).size == 0
    assert benjamini_hochberg([0.6, 0.7, 0.8], 0.05).sum() == 0


def test_fdr_helper_runs_on_real_batch():
    ds = generate(seed=7)
    reports = audit_all_claims(ds)
    flags = fdr_significant(reports, 0.05)
    assert set(flags.keys()) == {r.field_id for r in reports}
    assert all(isinstance(v, bool) for v in flags.values())
