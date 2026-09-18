"""
Second worked example — Theme E: Saudi pivot-irrigation abandonment.

The point of this file is to prove a claim: CarbonTwin is not a cover-crop
detector, it is a causal engine for *regime change from orbit*. The exact same
synthetic-control solver (scm.py) and placebo inference (inference.py) that
verify carbon additionality in Iowa also detect a pivot circle being abandoned
as its aquifer depletes — a green disc that collapses to desert.

What is genuinely reused (the engine): the convex synthetic-control solve and the
Abadie placebo permutation p-value. What is domain-specific (a thin wrapper):
the signal is year-round irrigation greenness, not an off-season window, and the
"event" of interest is a collapse (negative divergence), not additionality. Being
explicit about that line is the honest version of "one engine, many problems".
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .contract import Dataset, FieldSeries, monthly_composite
from .inference import placebo_test
from .scm import fit

_LAT0, _LON0 = 24.20, 44.80          # ~Wadi as-Sirhan style pivot country
COLLAPSE_EFFECT = -0.15              # NDVI gap below the still-irrigated twin


def generate_aquifer(seed: int = 11) -> Dataset:
    """Synthetic pivot-circle NDVI: some stay irrigated, some get abandoned."""
    rng = np.random.default_rng(seed)
    dates = np.arange(np.datetime64("2016-01-01"), np.datetime64("2025-12-31"),
                      np.timedelta64(16, "D")).astype("datetime64[D]")
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    doy = (dates - dates.astype("datetime64[Y]")).astype("timedelta64[D]").astype(int) + 1

    # shared mild climate variation across the well field
    clim = np.array([rng.normal(1.0, 0.05) for _ in range(2016, 2026)])
    clim_factor = np.array([clim[y - 2016] for y in years])

    # irrigated circle: green much of the year with a cropping cycle
    def irrigated(baseline, amp):
        season = amp * (0.5 + 0.5 * np.cos((doy - 60) / 58.0))  # two-ish cycles
        return (baseline + season) * clim_factor

    # roster: 8 active (donors), 4 abandoned in different years
    roster = [("active", None)] * 20 + [("abandoned", y) for y in (2020, 2021, 2022, 2023)]
    rng.shuffle(roster)

    fields = []
    for i, (label, abandon_year) in enumerate(roster):
        baseline = 0.40 + rng.normal(0, 0.02)
        amp = 0.30 + rng.normal(0, 0.03)
        ndvi = irrigated(baseline, amp)

        if label == "abandoned":
            # decay to bare desert over ~1 year once the pump stops
            ramp = np.clip((years + (doy / 366.0) - abandon_year) / 1.0, 0.0, 1.0)
            desert = 0.08
            ndvi = ndvi * (1 - ramp) + desert * ramp

        ndvi = ndvi + rng.normal(0, 0.02, size=ndvi.shape)
        # desert skies are clear: few cloud gaps (an honest, helpful detail)
        gaps = rng.random(ndvi.shape) < 0.06
        ndvi[gaps] = np.nan
        ndvi = np.clip(ndvi, 0.02, 0.95)

        fields.append(FieldSeries(
            field_id=f"C{i:02d}", ndvi=ndvi,
            lat=_LAT0 + rng.normal(0, 0.05), lon=_LON0 + rng.normal(0, 0.05),
            area_ha=float(rng.uniform(40, 130)),
            claims_adoption=(label == "abandoned"),       # the circles we audit
            claimed_year=None,
            truth_label=label, truth_year=abandon_year,
        ))
    return Dataset(dates=dates, fields=fields)


@dataclass
class CollapseReport:
    field_id: str
    month_dates: np.ndarray
    target: np.ndarray
    synthetic: np.ndarray
    effect: np.ndarray
    p_value: float
    collapse_detected: bool
    collapse_year: int | None
    ndvi_lost: float                 # peak greenness lost vs the twin
    truth_label: str | None


def audit_circle(dataset: Dataset, target_id: str,
                 baseline_max_year: int = 2018) -> CollapseReport:
    """Detect pivot-circle abandonment using the SAME SCM + placebo engine."""
    month_dates, matrix, _ = monthly_composite(dataset)
    ids = dataset.ids
    idx = {f: i for i, f in enumerate(ids)}

    donor_ids = [f.field_id for f in dataset.fields if f.truth_label == "active"
                 and f.field_id != target_id]
    donor_rows = np.array([idx[d] for d in donor_ids])

    yrs = np.asarray(pd.to_datetime(month_dates).year)
    pre = yrs <= baseline_max_year

    y = matrix[idx[target_id]]
    D = matrix[donor_rows]

    scm = fit(y, D, pre, donor_ids)               # reused engine
    inf = placebo_test(y, D, donor_ids, pre)       # reused inference

    # yearly mean effect; collapse = sustained negative divergence from the twin
    years, yearly = [], []
    for yy in range(baseline_max_year + 1, int(yrs.max()) + 1):
        sel = (yrs == yy)
        if sel.any():
            years.append(yy)
            yearly.append(float(np.mean(scm.effect[sel])))
    collapse_year = None
    for i, (yy, e) in enumerate(zip(years, yearly)):
        nxt_ok = (i == len(years) - 1) or (yearly[i + 1] <= COLLAPSE_EFFECT)
        if e <= COLLAPSE_EFFECT and nxt_ok:
            collapse_year = yy
            break
    detected = collapse_year is not None and inf.p_value < 0.05
    ndvi_lost = float(max(0.0, -np.min(scm.effect))) if detected else 0.0

    return CollapseReport(field_id=target_id, month_dates=month_dates, target=y,
                          synthetic=scm.synthetic, effect=scm.effect,
                          p_value=inf.p_value, collapse_detected=detected,
                          collapse_year=collapse_year, ndvi_lost=ndvi_lost,
                          truth_label=dataset.by_id(target_id).truth_label)


# ===========================================================================
#  Third worked example - Theme F: pre-symptomatic crop disease detection.
#  Same SCM + placebo engine, run on a red-edge stress index (NDRE) instead of
#  NDVI. The honest "impossible" angle: chlorophyll loss shows in red-edge
#  WEEKS before greenness (NDVI) drops, so the engine flags infection before
#  it is visible to a standard vegetation index. We demonstrate the lead time
#  by running the identical engine on both indices and comparing onset weeks.
# ===========================================================================
DECLINE_ONSET = -0.05            # divergence below the healthy twin = stress


def _season_curve(week, plateau):
    """Canopy develops, plateaus, gently senesces (shared by all fields)."""
    ramp = np.clip(week / 8.0, 0, 1)                  # green-up over ~8 weeks
    senesce = np.clip((week - 26) / 8.0, 0, 1) * 0.25  # mild late decline
    return 0.15 + (plateau - 0.15) * ramp - senesce


def generate_disease(seed: int = 13):
    """Return (ndre_dataset, ndvi_dataset): same fields, two indices.

    Healthy fields plateau; infected fields decline from an onset week - first in
    red-edge (NDRE), then ~3 weeks later in greenness (NDVI).
    """
    rng = np.random.default_rng(seed)
    dates = np.arange(np.datetime64("2024-03-01"), np.datetime64("2024-10-20"),
                      np.timedelta64(7, "D")).astype("datetime64[D]")
    week = np.arange(len(dates))
    NDVI_LAG = 3                                       # weeks red-edge leads greenness

    roster = [("healthy", None)] * 20 + [("infected", w) for w in (14, 16, 18, 20)]
    rng.shuffle(roster)

    ndre_fields, ndvi_fields = [], []
    for i, (label, onset) in enumerate(roster):
        ndre = _season_curve(week, 0.45 + rng.normal(0, 0.015))
        ndvi = _season_curve(week, 0.80 + rng.normal(0, 0.015))
        if label == "infected":
            d_re = np.clip((week - onset) / 6.0, 0, 1)            # red-edge first
            d_vi = np.clip((week - (onset + NDVI_LAG)) / 6.0, 0, 1)  # greenness later
            ndre = ndre * (1 - d_re) + 0.16 * d_re
            ndvi = ndvi * (1 - d_vi) + 0.34 * d_vi
        ndre = np.clip(ndre + rng.normal(0, 0.012, len(week)), 0.05, 0.9)
        ndvi = np.clip(ndvi + rng.normal(0, 0.012, len(week)), 0.05, 0.95)
        # light cloud gaps
        for arr in (ndre, ndvi):
            arr[rng.random(len(week)) < 0.10] = np.nan
        common = dict(lat=_LAT0 + rng.normal(0, 0.05), lon=_LON0 + rng.normal(0, 0.05),
                      area_ha=float(rng.uniform(10, 40)),
                      claims_adoption=(label == "infected"),
                      truth_label=label, truth_year=onset)
        ndre_fields.append(FieldSeries(field_id=f"D{i:02d}", ndvi=ndre, **common))
        ndvi_fields.append(FieldSeries(field_id=f"D{i:02d}", ndvi=ndvi, **common))
    return (Dataset(dates=dates, fields=ndre_fields),
            Dataset(dates=dates, fields=ndvi_fields))


@dataclass
class DiseaseReport:
    field_id: str
    dates: np.ndarray
    target: np.ndarray
    synthetic: np.ndarray
    effect: np.ndarray
    p_value: float
    onset_week: int | None
    detected: bool


def _weekly_matrix(dataset):
    rows = []
    for f in dataset.fields:
        s = pd.Series(f.ndvi).interpolate(limit_direction="both")
        rows.append(s.to_numpy())
    return np.vstack(rows), dataset.ids


def audit_disease(dataset: Dataset, target_id: str, pre_weeks: int = 12) -> DiseaseReport:
    """Detect a stress divergence using the SAME SCM + placebo engine."""
    matrix, ids = _weekly_matrix(dataset)
    idx = {f: i for i, f in enumerate(ids)}
    donor_ids = [f.field_id for f in dataset.fields if f.truth_label == "healthy"
                 and f.field_id != target_id]
    donor_rows = np.array([idx[d] for d in donor_ids])
    T = matrix.shape[1]
    pre = np.arange(T) < pre_weeks

    y = matrix[idx[target_id]]
    D = matrix[donor_rows]
    scm = fit(y, D, pre, donor_ids)
    inf = placebo_test(y, D, donor_ids, pre)

    onset = None
    for w in range(pre_weeks, T - 1):
        if scm.effect[w] <= DECLINE_ONSET and scm.effect[w + 1] <= DECLINE_ONSET:
            onset = w
            break
    detected = onset is not None and inf.p_value < 0.05
    return DiseaseReport(target_id, dataset.dates, y, scm.synthetic, scm.effect,
                         inf.p_value, onset, detected)
