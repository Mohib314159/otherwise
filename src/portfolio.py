"""
Portfolio risk layer — the risk-desk view across all audited fields.

Deliberately simple and defensive: it only sums/counts scalars that the audit
already produced, and guards every value so one bad field can never blank the
whole summary. This is what turns "we detect cover crops" into "we quantify the
verified tonnage, the fraud exposure, and the reversal risk of a credit book".
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def _safe(x: float) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


@dataclass
class PortfolioSummary:
    n_fields: int
    counts: dict                  # verdict status -> count
    verified_tco2e: float         # credited (VERIFIED + PARTIAL) tonnage / yr
    verified_at_95_tco2e: float   # tonnage from >=95% confidence fields only
    fraud_fields: int             # REJECTED claims
    fraud_exposure_tco2e: float   # claimed-but-unverified tonnage / yr
    fraud_exposure_value: float   # $ at the given carbon price
    reversal_fields: int          # fields with a detected reversal
    reversal_at_risk_tco2e: float # previously-credited tonnage now at risk / yr
    base_reversal_rate: float     # fraction of ever-verified fields that reverted
    base_annual_hazard: float     # that rate per observation-year
    observation_years: float
    price: float


def summarize(reports, price: float = 50.0) -> PortfolioSummary:
    counts: dict = {}
    verified = verified95 = 0.0
    fraud_n = 0
    fraud_t = 0.0
    rev_n = 0
    rev_risk = 0.0
    ever_verified = 0
    max_year, min_treat = 2021, 2021

    for r in reports:
        s = r.verdict.status
        counts[s] = counts.get(s, 0) + 1
        c = _safe(r.carbon.central_tco2e_yr)

        if s in ("VERIFIED", "PARTIAL"):
            verified += c
            if _safe(r.verdict.confidence) >= 95.0:
                verified95 += c

        # fraud exposure: a claim was made, nothing detected
        if s == "REJECTED":
            fraud_n += 1
            rate = _safe(r.claimed_rate_tco2e_ha)
            fraud_t += rate * _safe(r.area_ha)

        # reversal exposure
        rev = getattr(r, "reversal", None)
        if rev is not None and rev.detected:
            rev_n += 1
            # peak credited tonnage that is now at risk
            peak = max(rev.cumulative_tco2e) if rev.cumulative_tco2e else 0.0
            rev_risk += _safe(peak)
        if (s in ("VERIFIED", "PARTIAL")) or (rev is not None and rev.detected):
            ever_verified += 1

        # observation window
        if len(r.month_dates):
            max_year = max(max_year, int(pd.to_datetime(r.month_dates).year.max()))

    obs_years = max(1.0, float(max_year - min_treat + 1))
    base_rate = (rev_n / ever_verified) if ever_verified else 0.0
    base_hazard = base_rate / obs_years

    return PortfolioSummary(
        n_fields=len(reports), counts=counts,
        verified_tco2e=verified, verified_at_95_tco2e=verified95,
        fraud_fields=fraud_n, fraud_exposure_tco2e=fraud_t,
        fraud_exposure_value=fraud_t * price,
        reversal_fields=rev_n, reversal_at_risk_tco2e=rev_risk,
        base_reversal_rate=base_rate, base_annual_hazard=base_hazard,
        observation_years=obs_years, price=price,
    )
