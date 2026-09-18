"""
The audit verdict — where a number becomes a decision.

This is the differentiator. Most teams will show "NDVI went up". We return a
verdict against the farmer's *claim*, on a calibrated five-state scale that a
risk MD will recognise instantly:

  VERIFIED      significant effect, real additionality            -> credit it
  PARTIAL       significant & real, but BELOW what was claimed     -> credit real part
  INCONCLUSIVE  a real-looking but weak signal, NOT statistically
                separable from natural variation (or poor baseline
                fit) -> don't credit, don't accuse: recommend a visit
  REJECTED      a claim was made but the field is essentially flat
                -> possible false claim, flag for audit
  BASELINE      no claim, no significant change -> business-as-usual (donor)

The crucial honesty: a weak genuine adopter must NEVER be branded a liar. Only a
field with no detectable change is REJECTED. The "I don't know yet" state is a
feature, not a hedge - it's exactly how you avoid false accusations.
Thresholds are explicit and tunable. Defensibility > cleverness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

# decision thresholds
P_SIGNIF = 0.05          # placebo p-value for "significant"
EFFECT_MIN = 0.03        # min mean off-season NDVI uplift to call it meaningful
PRE_RMSE_MAX = 0.06      # if the pre-treatment fit is worse than this, don't trust it

COLORS = {
    "VERIFIED": "#34a853",      # green
    "PARTIAL": "#f9ab00",       # amber
    "INCONCLUSIVE": "#a142f4",  # purple
    "REJECTED": "#ea4335",      # red
    "BASELINE": "#9aa0a6",      # grey
}


@dataclass
class Verdict:
    field_id: str
    status: str
    headline: str
    effect_offseason: float
    p_value: float
    confidence: float
    pre_rmse: float
    reason: str
    color: str


def decide(field_id: str,
           effect_full: np.ndarray,
           post_mask: np.ndarray,
           offseason_post_mask: np.ndarray,
           p_value: float,
           confidence: float,
           pre_rmse: float,
           claims_adoption: bool,
           claimed_rate_tco2e_ha: Optional[float] = None,
           est_rate_tco2e_ha: Optional[float] = None,
           pre_rmse_max: float = PRE_RMSE_MAX,
           coverage_ok: bool = True) -> Verdict:
    eff_os = (float(np.mean(effect_full[offseason_post_mask]))
              if offseason_post_mask.any() else float(np.mean(effect_full[post_mask])))

    significant = (p_value < P_SIGNIF) and (eff_os > EFFECT_MIN)
    has_signal = eff_os > EFFECT_MIN
    bad_fit = pre_rmse > pre_rmse_max

    def v(status, headline, reason):
        return Verdict(field_id, status, headline, eff_os, p_value, confidence,
                       pre_rmse, reason, COLORS[status])

    # 0) not enough cloud-free observations in the signal window -> never guess.
    # A clouded-out winter must not be flattened into a confident "no cover crop".
    if not coverage_ok:
        return v("INCONCLUSIVE", "Insufficient cloud-free observations",
                 "Too few real (non-interpolated) off-season observations to judge "
                 "this field. We decline to score rather than trust interpolated data.")

    # 1) significant, real effect
    if significant and not bad_fit:
        if (claimed_rate_tco2e_ha is not None and est_rate_tco2e_ha is not None
                and est_rate_tco2e_ha < 0.6 * claimed_rate_tco2e_ha):
            return v("PARTIAL", "Real effect, but smaller than claimed",
                     f"Significant uplift (p={p_value:.3f}) but verified rate "
                     f"~{est_rate_tco2e_ha:.2f} vs claimed {claimed_rate_tco2e_ha:.2f} "
                     f"tCO2e/ha/yr. Credit only the verified portion.")
        return v("VERIFIED", "Additionality confirmed",
                 f"Off-season NDVI is {eff_os:+.3f} above the synthetic twin, "
                 f"sustained post-2021, p={p_value:.3f} ({confidence:.0f}% conf).")

    # 2) a real-looking but not-significant signal, or weak baseline fit
    if has_signal or bad_fit:
        why = (f"baseline fit (RMSE {pre_rmse:.3f}) exceeds the dataset noise floor "
               f"({pre_rmse_max:.3f})" if bad_fit
               else "a weak uplift is visible but not statistically separable from "
                    "natural variation at p<0.05")
        return v("INCONCLUSIVE", "Insufficient evidence - recommend site visit",
                 f"Effect {eff_os:+.3f}, p={p_value:.3f}: {why}. We neither credit "
                 f"nor reject - this is the calibrated 'go look' state.")

    # 3) flat. if they claimed something, that's a possible false claim
    if claims_adoption:
        return v("REJECTED", "Claim not supported - possible false claim",
                 f"Field claims adoption but shows no detectable divergence "
                 f"(effect {eff_os:+.3f}, p={p_value:.3f}). Flag for site visit.")

    # 4) flat and no claim -> business as usual
    return v("BASELINE", "Business-as-usual (no claim, no change)",
             "No adoption claimed and no significant divergence - donor-eligible.")
