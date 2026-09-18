"""
End-to-end pipeline: Dataset -> per-field audit.

run_audit() is the one call the dashboard and the validation harness both use.
Everything is built on the data contract, so swapping synthetic data for
Treefera's real data with live data changes nothing here - only the adapter.

Robustness wired in here (so real data on Thursday doesn't blow up):
  * thresholds adapt to the dataset's own noise floor (donor placebo pre-RMSE)
  * a coverage gate refuses to score fields whose off-season window is mostly
    cloud-interpolated (a clouded-out winter must never read as "no cover crop")
  * permanence monitoring runs forward in time to flag reversals
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .audit import EFFECT_MIN, PRE_RMSE_MAX, Verdict, decide
from .carbon import CarbonEstimate, estimate_carbon
from .contract import Dataset, monthly_composite, haversine_m, offseason_mask
from .inference import InferenceResult, placebo_test, benjamini_hochberg
from .monitor import ReversalResult, detect_onset, detect_reversal
from .scm import SCMResult, fit

COVERAGE_MIN = 0.40          # min fraction of REAL off-season obs to risk a verdict


@dataclass
class AuditReport:
    field_id: str
    month_dates: np.ndarray
    target: np.ndarray            # composited monthly NDVI of the field
    scm: SCMResult
    inference: InferenceResult
    carbon: CarbonEstimate
    verdict: Verdict
    reversal: ReversalResult
    detected_adoption_year: int | None
    area_ha: float
    claimed_rate_tco2e_ha: float | None
    offseason_coverage: float
    pre_rmse_max: float
    truth_label: str | None       # carried through for validation only


def _pre_mask(month_dates: np.ndarray, treat_year: int) -> np.ndarray:
    yrs = pd.to_datetime(month_dates).year
    return yrs < treat_year


def run_audit(dataset: Dataset, target_id: str,
              treat_year: int | None = None,
              donor_ids: list[str] | None = None,
              buffer_m: float | None = None) -> AuditReport:
    """Audit one field against its claim. Returns everything the UI needs."""
    month_dates, matrix, observed = monthly_composite(dataset)
    ids = dataset.ids
    idx = {fid: i for i, fid in enumerate(ids)}

    target = dataset.by_id(target_id)
    t_idx = idx[target_id]
    treat_year = treat_year or target.claimed_year or 2021

    if donor_ids is None:
        donor_ids = [d for d in dataset.control_ids() if d != target_id]
    # SUTVA / spatial-spillover guard: optionally exclude donors physically too
    # close to the treated field (shared runoff / microclimate). Standard applied
    # fix - a spatial buffer in donor selection, not a penalty inside the solver.
    # Donors with unknown coordinates are KEPT (can't measure - don't silently drop).
    if buffer_m:
        t = dataset.by_id(target_id)
        kept = []
        for d in donor_ids:
            f = dataset.by_id(d)
            dist = haversine_m(t.lat, t.lon, f.lat, f.lon)
            if np.isnan(dist) or dist >= buffer_m:
                kept.append(d)
        donor_ids = kept
    donor_rows = np.array([idx[d] for d in donor_ids])

    pre = _pre_mask(month_dates, treat_year)
    post = ~pre
    os_post = offseason_mask(month_dates, target.lat) & post

    y = matrix[t_idx]
    D = matrix[donor_rows]

    scm = fit(y, D, pre, donor_ids)
    inf = placebo_test(y, D, donor_ids, pre)

    # adaptive bad-fit threshold: scale to the dataset's own noise floor, with a
    # sensible floor so clean data still behaves.
    pre_rmse_max = max(PRE_RMSE_MAX, 1.6 * inf.median_pre_rmse)

    # coverage of the off-season signal window with REAL (non-interpolated) obs
    obs_t = observed[t_idx]
    n_os = int(os_post.sum())
    coverage = float(np.mean(obs_t[os_post])) if n_os else 0.0
    coverage_ok = coverage >= COVERAGE_MIN

    eff_os = float(np.mean(scm.effect[os_post])) if os_post.any() else float(np.mean(scm.effect[post]))
    significant = ((inf.p_value < 0.05) and (eff_os > EFFECT_MIN)
                   and coverage_ok and (scm.pre_rmse <= pre_rmse_max))
    carbon = estimate_carbon(eff_os, target.area_ha, verified=significant)

    verdict = decide(
        field_id=target_id,
        effect_full=scm.effect,
        post_mask=post,
        offseason_post_mask=os_post,
        p_value=inf.p_value,
        confidence=inf.confidence,
        pre_rmse=scm.pre_rmse,
        claims_adoption=target.claims_adoption,
        claimed_rate_tco2e_ha=target.claimed_rate_tco2e_ha,
        est_rate_tco2e_ha=carbon.rate_central,
        pre_rmse_max=pre_rmse_max,
        coverage_ok=coverage_ok,
    )

    reversal = detect_reversal(month_dates, scm.effect, target.area_ha, treat_year, lat=target.lat)
    detected_year, _, _ = detect_onset(month_dates, scm.effect, lat=target.lat)

    return AuditReport(field_id=target_id, month_dates=month_dates, target=y,
                       scm=scm, inference=inf, carbon=carbon, verdict=verdict,
                       reversal=reversal, detected_adoption_year=detected_year,
                       area_ha=target.area_ha,
                       claimed_rate_tco2e_ha=target.claimed_rate_tco2e_ha,
                       offseason_coverage=coverage, pre_rmse_max=pre_rmse_max,
                       truth_label=target.truth_label)


def audit_all_claims(dataset: Dataset) -> list[AuditReport]:
    """Audit every field that makes a claim (the demo set)."""
    return [run_audit(dataset, f.field_id)
            for f in dataset.fields if f.claims_adoption]


def fdr_significant(reports, alpha: float = 0.05) -> dict:
    """Across a batch of audits, return {field_id: bool} for which 'significant'
    detections survive Benjamini-Hochberg FDR control at level alpha.

    Use this at scale instead of trusting each field's raw p<0.05: it caps the
    expected proportion of false positives among the fields we flag.
    """
    reports = list(reports)
    pvals = [r.inference.p_value for r in reports]
    keep = benjamini_hochberg(pvals, alpha)
    return {r.field_id: bool(k) for r, k in zip(reports, keep)}
