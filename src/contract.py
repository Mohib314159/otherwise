"""
Data contract — the single fixed internal format the whole pipeline speaks.

The point of this file: everything downstream (synthetic control, inference,
carbon, audit, dashboard) is built and tested against THIS schema. For a new
data source the only new code required is a thin adapter (src/adapter.py) that reads
Treefera's actual files and produces a `Dataset`. Nothing else changes.

A `Dataset` is:
  - dates:   1-D array of numpy datetime64[D], sorted ascending, length T
  - fields:  list[FieldSeries], each with an NDVI vector aligned to `dates`
             (NaN where no cloud-free observation exists)

That's it. NDVI in [-1, 1]. One value per field per date. Field-level means
we've already reduced each polygon to its mean NDVI; the dashboard works at
field granularity, which keeps the story (and the maths) clean.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class FieldSeries:
    """One field: its NDVI time series plus the metadata the audit needs."""
    field_id: str
    ndvi: np.ndarray              # shape (T,), float, NaN allowed for cloud gaps
    lat: float
    lon: float
    area_ha: float
    # --- claim metadata (what the farmer says they did) ---
    claims_adoption: bool = False         # did they claim a regen practice?
    claimed_year: Optional[int] = None    # the year they claim they started
    claimed_rate_tco2e_ha: Optional[float] = None  # optional: per-ha rate they assert
    # --- ground truth (ONLY present in synthetic data, for validation) ---
    truth_label: Optional[str] = None     # 'adopter' | 'liar' | 'exaggerator' | 'control'
    truth_year: Optional[int] = None

    def __post_init__(self) -> None:
        self.ndvi = np.asarray(self.ndvi, dtype=float)


@dataclass
class Dataset:
    """A bundle of fields sharing one date axis."""
    dates: np.ndarray                      # datetime64[D], shape (T,)
    fields: list[FieldSeries] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.dates = np.asarray(self.dates, dtype="datetime64[D]")
        T = len(self.dates)
        for f in self.fields:
            if f.ndvi.shape[0] != T:
                raise ValueError(
                    f"Field {f.field_id} has {f.ndvi.shape[0]} points "
                    f"but dataset has {T} dates. Adapter must align them."
                )

    # ---- convenience lookups -------------------------------------------------
    def by_id(self, field_id: str) -> FieldSeries:
        for f in self.fields:
            if f.field_id == field_id:
                return f
        raise KeyError(field_id)

    @property
    def ids(self) -> list[str]:
        return [f.field_id for f in self.fields]

    def control_ids(self) -> list[str]:
        """Donor pool = fields that make no adoption claim.

        Honest assumption: a conventional 'business-as-
        usual' donor is a field with no claimed practice change. On real data
        you'd refine this (exclude any field showing its own off-season
        greenness), but no-claim is the clean, defensible default.
        """
        return [f.field_id for f in self.fields if not f.claims_adoption]


# ---------------------------------------------------------------------------
# Preprocessing: cloud gaps -> clean monthly grid.
# This is the "median composite" step — standard MRV practice and the exact
# answer to the judge question "how do you handle clouds?".
# ---------------------------------------------------------------------------
def monthly_composite(dataset: Dataset) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reduce cloudy ~biweekly series to monthly-median NDVI.

    Returns
    -------
    month_dates : (M,) datetime64[D]   -- first-of-month axis
    matrix      : (N_fields, M) float  -- monthly NDVI, interpolated for the solver
    observed    : (N_fields, M) bool   -- True where the month had a REAL (cloud-free)
                                          observation, i.e. NOT interpolated.

    The solver needs a complete (no-NaN) vector, so we interpolate gaps. But we
    DO NOT pretend the interpolated values are evidence: `observed` records which
    months are real, and the pipeline refuses to score a field whose off-season
    signal window is mostly interpolated (a clouded-out winter must never be
    flattened into a confident "no cover crop"). See pipeline.offseason_coverage.
    """
    df_dates = pd.to_datetime(dataset.dates)
    months = df_dates.to_period("M")
    unique_months = pd.period_range(months.min(), months.max(), freq="M")
    month_dates = np.array(
        [p.to_timestamp().to_datetime64() for p in unique_months], dtype="datetime64[D]"
    )

    rows, obs = [], []
    for f in dataset.fields:
        s = pd.Series(f.ndvi, index=months)
        monthly = s.groupby(level=0).median().reindex(unique_months)
        obs.append(monthly.notna().to_numpy())          # real months, pre-fill
        monthly = monthly.interpolate(method="linear", limit_direction="both")
        rows.append(monthly.to_numpy())

    matrix = np.vstack(rows)
    observed = np.vstack(obs)
    # any field that is still all-NaN (no data at all) -> zeros, flagged unobserved
    matrix = np.nan_to_num(matrix, nan=0.0)
    return month_dates, matrix, observed


def offseason_mask(month_dates: np.ndarray, lat: float | None = None) -> np.ndarray:
    """Boolean mask for the cover-crop signal window (post-harvest + spring).

    Cover crops show up as *off-season* greenness — roughly Oct–Dec and Mar–Apr in
    the Northern-Hemisphere corn belt. The summer cash crop dominates and is noisier
    for additionality, so the audit weights the off-season.

    If `lat` is given and negative (Southern Hemisphere), the window is shifted by
    six months so the mask still tracks the off-season there (e.g. Brazil/Argentina),
    rather than mistaking their summer harvest for a missing cover crop.
    """
    base = [10, 11, 12, 3, 4]
    if lat is not None and lat < 0:
        base = [((mo + 6 - 1) % 12) + 1 for mo in base]   # -> [4, 5, 6, 9, 10]
    m = pd.to_datetime(month_dates).month
    return np.isin(m, base)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (NaN if any coordinate is missing)."""
    import numpy as _np
    if any(_np.isnan(v) for v in (lat1, lon1, lat2, lon2)):
        return float("nan")
    R = 6_371_000.0
    p1, p2 = _np.radians(lat1), _np.radians(lat2)
    dphi, dl = _np.radians(lat2 - lat1), _np.radians(lon2 - lon1)
    a = _np.sin(dphi / 2) ** 2 + _np.cos(p1) * _np.cos(p2) * _np.sin(dl / 2) ** 2
    return float(2 * R * _np.arcsin(_np.sqrt(a)))
