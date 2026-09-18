"""
Inference by placebo permutation (Abadie et al.).

We can't get a textbook standard error from one treated unit. Instead we ask:
if we pretend each *donor* field was the treated one, how often do we see a
post-treatment divergence as extreme as the real field's?

Test statistic = RMSPE ratio = (post-period RMSE of the gap) / (pre-period RMSE).
A genuine effect fits tightly before treatment and diverges sharply after, so it
scores a high ratio. A field that just fits badly everywhere scores low. Ranking
the real field's ratio among the placebos gives a permutation p-value.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .scm import fit


def _rmspe_ratio(effect: np.ndarray, pre_mask: np.ndarray) -> float:
    pre = effect[pre_mask]
    post = effect[~pre_mask]
    pre_rmse = np.sqrt(np.mean(pre ** 2)) + 1e-9
    post_rmse = np.sqrt(np.mean(post ** 2))
    return float(post_rmse / pre_rmse)


@dataclass
class InferenceResult:
    p_value: float
    target_ratio: float
    placebo_ratios: np.ndarray
    confidence: float          # 1 - p, as a percentage-friendly number
    donor_pre_rmses: np.ndarray  # pre-fit RMSE of each placebo (the noise floor)
    median_pre_rmse: float       # dataset-specific baseline fit quality


def placebo_test(target_ndvi: np.ndarray,
                 donor_matrix: np.ndarray,
                 donor_ids: list[str],
                 pre_mask: np.ndarray) -> InferenceResult:
    """One-sided permutation test on the RMSPE ratio.

    Each donor is re-fit as a fake-treated unit using the *other* donors, giving
    a null distribution of ratios. p = P(placebo ratio >= target ratio). The
    placebos' own pre-fit RMSEs also tell us the dataset's noise floor, which we
    use to set the "baseline too weak to trust" threshold adaptively.
    """
    # real effect
    real = fit(target_ndvi, donor_matrix, pre_mask, donor_ids)
    target_ratio = _rmspe_ratio(real.effect, pre_mask)

    placebo_ratios, pre_rmses = [], []
    m = donor_matrix.shape[0]
    for j in range(m):
        keep = [k for k in range(m) if k != j]
        fake_target = donor_matrix[j]
        fake_donors = donor_matrix[keep]
        r = fit(fake_target, fake_donors, pre_mask, [donor_ids[k] for k in keep])
        placebo_ratios.append(_rmspe_ratio(r.effect, pre_mask))
        pre_rmses.append(r.pre_rmse)

    placebo_ratios = np.array(placebo_ratios)
    pre_rmses = np.array(pre_rmses)
    # +1 in num & denom: the conventional, slightly conservative permutation p
    p = (np.sum(placebo_ratios >= target_ratio) + 1) / (len(placebo_ratios) + 1)
    return InferenceResult(p_value=float(p), target_ratio=target_ratio,
                           placebo_ratios=placebo_ratios,
                           confidence=float(100.0 * (1.0 - p)),
                           donor_pre_rmses=pre_rmses,
                           median_pre_rmse=float(np.median(pre_rmses)))


def benjamini_hochberg(pvalues, alpha: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg FDR control over a family of tests.

    Returns a boolean mask of which p-values are 'discoveries' while holding the
    expected false-discovery rate at <= alpha. This is the honest answer to
    'won't you flag false positives when you scale to thousands of fields?': we
    don't trust raw per-field p<0.05 at scale, we control the FDR across the batch.
    """
    p = np.asarray(pvalues, dtype=float)
    n = p.size
    if n == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(p)
    ranked = p[order]
    thresh = alpha * (np.arange(1, n + 1) / n)
    passed = ranked <= thresh
    if not passed.any():
        return np.zeros(n, dtype=bool)
    kmax = np.max(np.where(passed)[0])      # largest rank meeting the BH line
    cutoff = ranked[kmax]
    return p <= cutoff
