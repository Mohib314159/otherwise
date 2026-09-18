"""
Dual-channel fusion: optical NDVI + (simulated) Sentinel-1 SAR tillage signal.

This answers the FULL Theme-B question. The farmer made TWO changes — cover crops
in 2021 and no-till in 2023 — and optical NDVI can only see the first. Cover crops
show as off-season greenness (optical); no-till is the *absence of soil
disturbance*, which greenness cannot see but radar can: C-band backscatter responds
to the roughness and structure of the canopy-soil complex, so tillage events leave a
radar signature that vanishes when a field goes no-till.

HONESTY: there is no real Sentinel-1 over Iowa in the provided Theme-B data (their
SAR is a different theme, over the tropics). The radar channel here is SIMULATED in
the validation harness to prove the *fusion logic*. Real Sentinel-1 is free and
global on Google Earth Engine and plugs into the same channel-agnostic pipeline —
the adapter and SCM engine do not care whether a column is NDVI or backscatter.

The same synthetic-control engine runs on each channel:
  * optical NDVI  -> detects the cover-crop adoption year (a rise)   -> 2021
  * radar tillage -> detects the no-till adoption year (a fall)      -> 2023
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .contract import Dataset, FieldSeries
from .inference import placebo_test
from .scm import fit

_LAT0, _LON0 = 41.74, -92.72
NOTILL_DROP = -0.12          # fall in the tillage index below the still-tilling twin


def _phenology(doy, baseline, amp):
    return baseline + amp * np.exp(-((doy - 200.0) ** 2) / (2 * 48.0 ** 2))


def _offseason_weight(doy):
    w = np.zeros_like(doy, dtype=float)
    w[(doy >= 288) | (doy <= 120)] = 1.0
    return 0.5 * (w + np.clip(np.cos((doy - 30) / 90.0), 0, 1))


def _tillage_pulses(doy, years, active_until=None):
    """Soil-disturbance proxy: spikes at spring + autumn tillage each year a field
    is still being ploughed. `active_until` = last year tillage occurs (None = always).
    """
    spring = np.exp(-((doy - 110.0) ** 2) / (2 * 22.0 ** 2))   # ~late Apr ploughing
    autumn = np.exp(-((doy - 300.0) ** 2) / (2 * 22.0 ** 2))   # ~late Oct tillage
    base = 0.55 * (spring + autumn) + 0.08
    if active_until is not None:
        base = base * (years <= active_until).astype(float) + 0.08 * (years > active_until)
    return base


def generate_regen_dual(seed: int = 17):
    """Return (ndvi_dataset, tillage_dataset): same fields, two channels.

    full_regen  : cover crops from 2021 (NDVI rise) AND no-till from 2023 (tillage fall)
    conventional: neither (the donor pool for both channels)
    """
    rng = np.random.default_rng(seed)
    dates = np.arange(np.datetime64("2019-01-01"), np.datetime64("2025-12-31"),
                      np.timedelta64(16, "D")).astype("datetime64[D]")
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    doy = (dates - dates.astype("datetime64[Y]")).astype("timedelta64[D]").astype(int) + 1
    osw = _offseason_weight(doy)

    roster = [("full_regen", 2021, 2023)] * 4 + [("conventional", None, None)] * 20
    rng.shuffle(roster)

    ndvi_fields, till_fields = [], []
    for i, (label, cover_year, notill_year) in enumerate(roster):
        baseline = 0.17 + rng.normal(0, 0.02)
        amp = 0.66 + rng.normal(0, 0.03)
        ndvi = _phenology(doy, baseline, amp)
        if cover_year is not None:
            ndvi = ndvi + 0.24 * osw * (years >= cover_year).astype(float)
        ndvi = np.clip(ndvi + rng.normal(0, 0.025, ndvi.shape), -0.05, 0.97)

        till = _tillage_pulses(doy, years, active_until=(notill_year - 1) if notill_year else None)
        till = np.clip(till + rng.normal(0, 0.02, till.shape), 0.0, 1.0)

        # light cloud gaps on optical only (radar sees through cloud — the point)
        ndvi[rng.random(ndvi.shape) < 0.22] = np.nan

        meta = dict(lat=_LAT0 + rng.normal(0, 0.015), lon=_LON0 + rng.normal(0, 0.02),
                    area_ha=float(rng.uniform(28, 64)),
                    claims_adoption=(label == "full_regen"),
                    truth_label=label, truth_year=cover_year)
        ndvi_fields.append(FieldSeries(field_id=f"R{i:02d}", ndvi=ndvi, **meta))
        till_fields.append(FieldSeries(field_id=f"R{i:02d}", ndvi=till, **meta))
    return Dataset(dates=dates, fields=ndvi_fields), Dataset(dates=dates, fields=till_fields)


@dataclass
class FusionReport:
    field_id: str
    cover_year: int | None       # optical: when cover crops started
    notill_year: int | None      # radar: when no-till started
    cover_p: float
    notill_p: float
    dates: np.ndarray
    ndvi_target: np.ndarray
    ndvi_synth: np.ndarray
    till_target: np.ndarray
    till_synth: np.ndarray


def _interp_matrix(ds):
    return np.vstack([pd.Series(f.ndvi).interpolate(limit_direction="both").to_numpy()
                      for f in ds.fields]), ds.ids


def _detect_step(effect, yrs, baseline_max_year, direction, thresh):
    years, yearly = [], []
    for y in range(baseline_max_year + 1, int(yrs.max()) + 1):
        sel = yrs == y
        if sel.any():
            years.append(y); yearly.append(float(np.mean(effect[sel])))
    for i, (y, e) in enumerate(zip(years, yearly)):
        ok_next = (i == len(years) - 1) or (
            yearly[i + 1] >= thresh if direction == "up" else yearly[i + 1] <= thresh)
        hit = (e >= thresh) if direction == "up" else (e <= thresh)
        if hit and ok_next:
            return y
    return None


def audit_fusion(ndvi_ds: Dataset, till_ds: Dataset, target_id: str) -> FusionReport:
    """Fuse two channels with one engine: optical for cover crops, radar for no-till."""
    # ---- optical channel: detect the cover-crop year (a RISE), off-season ----
    Xo, ids = _interp_matrix(ndvi_ds)
    idx = {f: i for i, f in enumerate(ids)}
    donors_o = [f.field_id for f in ndvi_ds.fields if f.truth_label == "conventional"]
    do_rows = np.array([idx[d] for d in donors_o])
    yrs = np.asarray(pd.to_datetime(ndvi_ds.dates).year)
    doy = (ndvi_ds.dates - ndvi_ds.dates.astype("datetime64[Y]")).astype("timedelta64[D]").astype(int) + 1
    os_mask = (doy >= 288) | (doy <= 120)
    pre_o = yrs <= 2020
    scm_o = fit(Xo[idx[target_id]], Xo[do_rows], pre_o, donors_o)
    inf_o = placebo_test(Xo[idx[target_id]], Xo[do_rows], donors_o, pre_o)
    eff_o = np.where(os_mask, scm_o.effect, np.nan)
    cover_year = _detect_step(np.nan_to_num(eff_o), yrs, 2020, "up", 0.04)

    # ---- radar channel: detect the no-till year (a FALL in tillage) ----
    Xt, _ = _interp_matrix(till_ds)
    donors_t = [f.field_id for f in till_ds.fields if f.truth_label == "conventional"]
    dt_rows = np.array([idx[d] for d in donors_t])
    pre_t = yrs <= 2022          # tilled by everyone through 2022
    scm_t = fit(Xt[idx[target_id]], Xt[dt_rows], pre_t, donors_t)
    inf_t = placebo_test(Xt[idx[target_id]], Xt[dt_rows], donors_t, pre_t)
    notill_year = _detect_step(scm_t.effect, yrs, 2022, "down", NOTILL_DROP)

    return FusionReport(target_id, cover_year, notill_year, inf_o.p_value, inf_t.p_value,
                        ndvi_ds.dates, Xo[idx[target_id]], scm_o.synthetic,
                        Xt[idx[target_id]], scm_t.synthetic)
