"""
Synthetic Iowa cover-crop dataset WITH PLANTED GROUND TRUTH.

This is not a prop to make a pretty chart. It is the validation harness. We hide
a known truth in every field and require the pipeline to recover it on data that
contains the same nasty confounders as the real thing:

  * a shared regional shock each year (a drought year hits every field at once)
    -> this is exactly what defeats naive "did NDVI go up?" and what the
       synthetic control is built to absorb.
  * a mid-series sensor transition (PlanetScope PS2 -> PSB.SD), a small
    systematic NDVI shift applied to ALL fields from mid-2022 -> the trap that
    breaks change-detection that isn't robust. SCM differences it out because it
    is common-mode across target and donors.
  * cloud gaps (~25% of dates dropped, more in winter) -> handled by monthly
    median compositing.
  * per-observation noise and per-field random effects.

Field types (the ground truth):
  adopter      -- really started cover crops in 2021, strong off-season signal
  liar         -- CLAIMS 2021 adoption, did nothing  (must be REJECTED)
  exaggerator  -- really adopted but weakly, claims a big number (-> PARTIAL)
  control      -- never adopted, no claim (the donor pool)
"""
from __future__ import annotations

import numpy as np

from .contract import Dataset, FieldSeries

# --- regional centre (a real-ish patch near Grinnell, Iowa) ---
_LAT0, _LON0 = 41.74, -92.72
_SENSOR_SWITCH = np.datetime64("2022-07-01")  # PlanetScope PS2 -> PSB.SD


def _phenology(doy: np.ndarray, baseline: float, amp: float) -> np.ndarray:
    """Cash-crop annual curve: bare in winter, green peak mid-summer (~day 200)."""
    peak, sigma = 200.0, 48.0
    bump = amp * np.exp(-((doy - peak) ** 2) / (2 * sigma ** 2))
    return baseline + bump


def _offseason_weight(doy: np.ndarray) -> np.ndarray:
    """Weight ~1 in the cover-crop windows (late autumn + early spring), else 0."""
    w = np.zeros_like(doy, dtype=float)
    w[(doy >= 288) | (doy <= 120)] = 1.0          # Oct 15 -> Apr 30
    # taper so it isn't a hard square wave
    return 0.5 * (w + np.clip(np.cos((doy - 30) / 90.0), 0, 1))


def generate(seed: int = 7) -> Dataset:
    rng = np.random.default_rng(seed)

    # ---- date axis: every 16 days, 2019-01-01 .. 2025-12-31 ----
    dates = np.arange(
        np.datetime64("2019-01-01"), np.datetime64("2025-12-31"), np.timedelta64(16, "D")
    ).astype("datetime64[D]")
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    doy = (dates - dates.astype("datetime64[Y]")).astype("timedelta64[D]").astype(int) + 1

    # ---- shared regional shocks (same for every field) ----
    # multiplicative on summer amplitude + small additive on baseline, per year
    shock_amp = {y: float(rng.normal(1.0, 0.10)) for y in range(2019, 2026)}
    shock_base = {y: float(rng.normal(0.0, 0.015)) for y in range(2019, 2026)}
    shock_amp[2023] *= 0.78          # planted drought year — everyone dips
    shock_base[2020] += 0.03         # wet year — everyone slightly greener
    amp_factor = np.array([shock_amp[y] for y in years])
    base_add = np.array([shock_base[y] for y in years])

    osw = _offseason_weight(doy)

    # ---- roster: (truth_label, cover_strength, claimed_rate_tco2e_ha) ----
    # designed so the four honest verdict states each appear:
    #   adopter      strong, honest claim        -> VERIFIED
    #   over_claimer strong & real, absurd claim  -> PARTIAL (real but below claim)
    #   weak         small real effect, claims    -> INCONCLUSIVE (real, not provable)
    #   liar         flat, claims                 -> REJECTED (possible false claim)
    #   control      flat, no claim               -> BASELINE (donor pool)
    #   reverter     adopts 2021, ploughs it up 2024 -> VERIFIED then REVERSAL alert
    roster = (
        [("adopter", 0.24, 1.0)] * 6
        + [("over_claimer", 0.22, 3.0)] * 3
        + [("weak", 0.09, 1.0)] * 2
        + [("reverter", 0.24, 1.0)] * 2
        + [("liar", 0.0, 1.0)] * 4
        + [("control", 0.0, None)] * 20
    )
    rng.shuffle(roster)

    fields: list[FieldSeries] = []
    for i, (label, cover_strength, claim_rate) in enumerate(roster):
        # per-field random effects (soil/management identity)
        baseline = 0.17 + rng.normal(0, 0.02)
        amp = 0.66 + rng.normal(0, 0.03)

        ndvi = _phenology(doy, baseline, amp) * amp_factor + base_add

        # cover-crop off-season greenness from 2021 onward
        if label in ("adopter", "over_claimer", "weak"):
            active = (years >= 2021).astype(float)
            ndvi = ndvi + cover_strength * osw * active
        elif label == "reverter":
            # genuine adoption 2021-2023, then ploughed up: signal collapses in 2024
            active = ((years >= 2021) & (years <= 2023)).astype(float)
            ndvi = ndvi + cover_strength * osw * active

        # sensor transition: small systematic shift applied to EVERYONE post-switch
        post_switch = dates >= _SENSOR_SWITCH
        ndvi[post_switch] = 1.03 * ndvi[post_switch] - 0.015

        # observation noise
        ndvi = ndvi + rng.normal(0, 0.025, size=ndvi.shape)

        # cloud gaps: ~25% overall, heavier in winter
        winter = (doy <= 75) | (doy >= 305)
        p_cloud = np.where(winter, 0.42, 0.18)
        gaps = rng.random(ndvi.shape) < p_cloud
        ndvi[gaps] = np.nan

        ndvi = np.clip(ndvi, -0.05, 0.97)

        # claim metadata depends on type
        claims = label in ("adopter", "over_claimer", "weak", "liar", "reverter")
        adopted = label in ("adopter", "over_claimer", "weak", "reverter")

        fields.append(
            FieldSeries(
                field_id=f"F{i:02d}",
                ndvi=ndvi,
                lat=_LAT0 + rng.normal(0, 0.015),
                lon=_LON0 + rng.normal(0, 0.020),
                area_ha=float(rng.uniform(28, 64)),
                claims_adoption=claims,
                claimed_year=2021 if claims else None,
                claimed_rate_tco2e_ha=claim_rate,
                truth_label=label,
                truth_year=2021 if adopted else None,
            )
        )

    return Dataset(dates=dates, fields=fields)
