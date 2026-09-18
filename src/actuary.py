"""
The Orbital Actuary — pricing reversal risk for a carbon credit.

The honest bridge from orbital MRV to actuarial finance. We do NOT invent a
precise per-farmer probability from radar we don't have. Instead:

  hazard(field) = base_annual_hazard  x  stability_multiplier(field)

  * base_annual_hazard comes from the OBSERVED reversal frequency across the
    portfolio (a frequency estimate — exactly what an actuary starts from).
  * stability_multiplier is a transparent score from THIS field's own
    additionality trajectory: a declining or volatile credit is riskier.

Survival is the standard exponential model S(t) = exp(-hazard * t) (Weibull is
the natural generalisation if a shape parameter is later calibrated). From that
we read a horizon reversal probability and an *illustrative* risk premium. Every
number here is bounded and labelled indicative — the novelty is the bridge, not
a claim of actuarial precision from one short series.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ReversalRisk:
    applicable: bool              # only meaningful for credits with verified carbon
    stability_multiplier: float
    annual_hazard: float
    survival_curve: list[float]   # S(t) for t = 0..horizon
    horizon_years: int
    reversal_prob_horizon: float  # 1 - S(horizon)
    annual_premium_per_tco2e: float
    insured_tco2e: float          # the tonnage being insured (per yr)
    annual_premium_value: float   # premium_per_ton x insured tonnage
    note: str


def _stability_multiplier(yearly_effect: list[float]) -> float:
    """Higher when a credit's additionality is declining or volatile.

    Transparent triage score in roughly [0.5, 2.5]; not a calibrated parameter.
    """
    y = np.asarray([e for e in yearly_effect], dtype=float)
    if y.size < 2:
        return 1.0
    peak = max(float(np.max(y)), 1e-6)
    last = float(y[-1])
    decline_frac = float(np.clip((peak - last) / peak, 0.0, 1.0))
    vol = float(np.clip(np.std(y) / peak, 0.0, 1.0))
    m = 0.6 + 1.6 * decline_frac + 0.6 * vol
    return float(np.clip(m, 0.5, 2.5))


def price_report(report, base_annual_hazard: float, price: float = 50.0,
                 horizon_years: int = 10) -> ReversalRisk:
    """Price the reversal risk of one audited field."""
    insured = float(getattr(report.carbon, "central_tco2e_yr", 0.0) or 0.0)
    verified = report.verdict.status in ("VERIFIED", "PARTIAL")

    rev = getattr(report, "reversal", None)
    yearly = rev.yearly_effect if rev is not None else []
    mult = _stability_multiplier(yearly)

    # a reverted credit is effectively certain to have failed; floor the base
    # hazard so a portfolio with zero observed reversals still prices *some* risk.
    base = max(base_annual_hazard, 0.01)
    hazard = float(np.clip(base * mult, 0.0, 0.6))
    if rev is not None and rev.detected:
        hazard = max(hazard, 0.25)   # already reversing -> high hazard

    t = np.arange(0, horizon_years + 1)
    if rev is not None and rev.detected:
        # Confirmed reversal: the credit is impaired NOW, not a future maybe.
        # Model it as (near-)terminated rather than smooth exponential survival
        # (which would absurdly imply an already-collapsed asset still survives).
        survival = np.where(t == 0, 1.0, 0.05)
        reversal_note = (" Reversal already detected: credit treated as impaired "
                         "(survival ~0), not a forward projection.")
    else:
        survival = np.exp(-hazard * t)
        reversal_note = ""
    prob_h = float(1.0 - survival[-1])

    # illustrative annual premium per tonne = price x expected annual loss rate
    prem_per_ton = float(price * hazard)
    prem_value = prem_per_ton * insured

    if not verified or insured <= 0:
        return ReversalRisk(False, mult, hazard, survival.tolist(), horizon_years,
                            prob_h, 0.0, 0.0, 0.0,
                            "No verified carbon to insure.")

    note = ("Illustrative. Hazard = portfolio base rate x trajectory-stability "
            "score; premium = price x annual hazard. Calibrate on real reversal "
            "history before quoting." + reversal_note)
    return ReversalRisk(True, mult, hazard, survival.tolist(), horizon_years,
                        prob_h, prem_per_ton, insured, prem_value, note)
