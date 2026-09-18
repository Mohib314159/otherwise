"""
Permanence monitoring — does a verified credit STAY verified?

A carbon credit isn't a one-time stamp. A farmer can be genuinely verified in
2022 and plough the whole thing up in 2024 — the sequestered carbon is released
and the credit is worthless, but nobody is watching. Permanence / reversal risk
is the Achilles heel of every nature-based credit, and it's almost never
monitored continuously.

CarbonTwin keeps running the synthetic control forward in time and tracks the
additionality YEAR BY YEAR. If a sustained positive effect collapses back toward
zero, we raise a REVERSAL alert with the year it broke — the same defensible
method, pointed at the question the market actually can't answer today.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .audit import EFFECT_MIN
from .carbon import estimate_carbon
from .contract import offseason_mask


def detect_onset(month_dates: np.ndarray,
                 effect_full: np.ndarray,
                 floor: float = EFFECT_MIN,
                 baseline_max_year: int = 2020,
                 lat: float | None = None) -> tuple[int | None, list[int], list[float]]:
    """Detect the YEAR a practice was adopted, from the data alone.

    This answers the literal Challenge-B question ("detect the exact year his
    practices changed") instead of assuming it. The synthetic control is fitted on
    an early baseline (<= baseline_max_year); the adoption year is the first
    post-baseline year whose off-season additionality crosses the floor and stays
    there. A field that never crosses (a liar / control) returns None.
    """
    md = pd.to_datetime(month_dates)
    yrs = md.year.to_numpy()
    os_mask = offseason_mask(month_dates, lat)

    years, yearly = [], []
    for y in range(baseline_max_year + 1, int(yrs.max()) + 1):
        sel = (yrs == y) & os_mask
        if sel.any():
            years.append(y)
            yearly.append(float(np.mean(effect_full[sel])))

    onset = None
    for i, (y, e) in enumerate(zip(years, yearly)):
        # confident onset = two consecutive off-seasons above the floor
        if e >= floor and i < len(years) - 1 and yearly[i + 1] >= floor:
            onset = y
            break
    return onset, years, yearly


@dataclass
class ReversalResult:
    detected: bool
    reversal_year: int | None
    years: list[int] = field(default_factory=list)
    yearly_effect: list[float] = field(default_factory=list)     # off-season effect / yr
    cumulative_tco2e: list[float] = field(default_factory=list)  # "carbon bank" to date
    headline: str = ""


def detect_reversal(month_dates: np.ndarray,
                    effect_full: np.ndarray,
                    area_ha: float,
                    treat_year: int = 2021,
                    lat: float | None = None) -> ReversalResult:
    """Track yearly off-season additionality and flag a collapse.

    A reversal = the effect was clearly positive (>= EFFECT_MIN) in earlier
    post-treatment years, then fell below half that threshold and stayed there.
    """
    md = pd.to_datetime(month_dates)
    yrs = md.year.to_numpy()
    os_mask = offseason_mask(month_dates, lat)

    years, yearly, cum = [], [], []
    running = 0.0
    for y in range(treat_year, int(yrs.max()) + 1):
        sel = (yrs == y) & os_mask
        if not sel.any():
            continue
        eff_y = float(np.mean(effect_full[sel]))
        years.append(y)
        yearly.append(eff_y)
        # only a verified-positive year adds to the carbon bank
        c = estimate_carbon(eff_y, area_ha, verified=(eff_y >= EFFECT_MIN))
        running += c.central_tco2e_yr
        cum.append(running)

    # detection: a credit that was clearly verified, then collapsed relative to
    # its own peak and fell below the verifiable floor (denoised over last 2 yrs)
    detected, ry, headline = False, None, "Stable - no reversal detected"
    if years:
        arr = np.asarray(yearly, dtype=float)
        peak = float(arr.max())
        peak_year = years[int(arr.argmax())]
        k = min(2, len(years))
        recent = float(np.mean(arr[-k:]))
        if peak >= EFFECT_MIN and recent < EFFECT_MIN and recent < 0.45 * peak:
            below = [y for y, e in zip(years, yearly) if y > peak_year and e < EFFECT_MIN]
            ry = below[0] if below else years[-1]
            detected = True
            headline = (f"REVERSAL: verified through ~{peak_year}, additionality "
                        f"collapsed by {ry} - credit at risk")
        elif peak < EFFECT_MIN:
            headline = "Never reached verifiable additionality"

    return ReversalResult(detected=detected, reversal_year=ry, years=years,
                          yearly_effect=yearly, cumulative_tco2e=cum,
                          headline=headline)
