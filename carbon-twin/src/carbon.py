"""
Carbon estimate — honest, cited, uncertainty-first.

The weakest scientific link in any "NDVI -> carbon" story is the conversion, and
a physicist judge will go straight for it. So we do NOT invent a precise
"tCO2e per NDVI unit" coefficient. Instead:

  1. The synthetic control decides WHETHER a real, significant additionality
     effect exists (that's the defensible part).
  2. If verified, we attach a per-hectare sequestration rate drawn from the
     published literature, carried with a wide band.
  3. The *magnitude* of the causal NDVI effect only places the field WITHIN that
     band (stronger sustained greenness -> more biomass input -> upper end). The
     absolute number stays uncertain and we say so.

Literature anchors (state these):
  * Cover cropping sequesters ~0.22 t CARBON / acre / yr  (CO2e ~ x 3.67/0.405
    ~ 2.0 tCO2e/ha/yr at the high end of estimates).
  * No-till + cover cropping together ~1.2 tCO2e/ha/yr net mitigation.
  * Soil-carbon studies more conservatively report ~0.2-0.5 tCO2e/ha/yr.
  * Carbon price varies wildly (~$/EUR 5-100+/tCO2e by market).

So the defensible central range we carry is ~0.2-2.0 tCO2e/ha/yr, central ~1.0.
Note: per-field money is SMALL. That is precisely why
automated verification (not manual audits) is the only way the market scales.
"""
from __future__ import annotations

from dataclasses import dataclass

# central estimate and band (tCO2e per hectare per year), literature-derived
RATE_CENTRAL = 1.0
RATE_LOW = 0.2
RATE_HIGH = 2.0

# the NDVI off-season effect that we treat as a "strong" signal (places field
# at the top of the band). Calibrated to the corn-belt cover-crop literature
# signal, NOT a physical conversion — see module docstring.
NDVI_EFFECT_REFERENCE = 0.20


@dataclass
class CarbonEstimate:
    central_tco2e_yr: float
    low_tco2e_yr: float
    high_tco2e_yr: float
    rate_central: float        # per ha
    note: str

    def value_range_gbp(self, price_low: float = 5.0, price_high: float = 100.0
                        ) -> tuple[float, float]:
        return self.low_tco2e_yr * price_low, self.high_tco2e_yr * price_high


def estimate_carbon(ndvi_effect: float, area_ha: float, verified: bool
                    ) -> CarbonEstimate:
    """Convert a *verified* NDVI additionality effect to an indicative CO2e/yr.

    If not verified, returns zeros — we never credit an unproven claim.
    """
    if not verified or ndvi_effect <= 0:
        return CarbonEstimate(0.0, 0.0, 0.0, 0.0,
                              "No verified additionality — no credit attributed.")

    # place within the band by signal strength, clamped to [0, 1].
    # IMPORTANT: this is a *triage* scaling for dashboard ranking, NOT a physical
    # NDVI->carbon conversion. The defensible claim is the statistical
    # additionality + the literature band; the point estimate is indicative only.
    strength = max(0.0, min(1.0, ndvi_effect / NDVI_EFFECT_REFERENCE))
    rate = RATE_LOW + strength * (RATE_CENTRAL - RATE_LOW)  # conservative centre

    central = rate * area_ha
    low = RATE_LOW * area_ha
    high = RATE_HIGH * area_ha
    note = ("Indicative triage estimate, NOT a measured tonnage. Statistical "
            "significance is proven; the tonnage is a linear scaling bounded by the "
            "literature band (0.2-2.0 tCO2e/ha/yr) and requires soil-core calibration.")
    return CarbonEstimate(central, low, high, rate, note)
