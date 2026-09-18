"""
Phenology extraction — reconstruct each field's management calendar from its NDVI
time series. From the shape of the green-up/senescence curve we read, per year:

  sos  start of season   (green-up crosses the half-amplitude threshold upward)
  pos  peak of season    (day of maximum NDVI)
  eos  end of season     (senescence crosses back below threshold)
  length    season length in days (eos - sos)
  amplitude peak minus trough NDVI

This is a creative use of the 7-year temporal runway: planting/harvest timing, season
length and crop vigour per field per year — and it profiles management without a single
extra sensor. The multi-year SHIFT is the causal hook: a field that consistently breaks
ground earlier than its synthetic twin is front-running the season (a risk-tolerance
signal); a field whose season length jumps signals a management change. Those annual
series feed the same fit()+placebo_test() engine (needs the multi-year cube, not the
24-month demo). Honest: thresholds are simple and would be tuned per crop/biome.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def extract_phenology(ndvi, dates, frac: float = 0.5) -> dict:
    """Return {year: {sos, pos, eos, length, amplitude}} from one field's series."""
    s = pd.Series(np.asarray(ndvi, float), index=pd.to_datetime(dates)
                  ).interpolate(limit_direction="both")
    out = {}
    for yr, grp in s.groupby(s.index.year):
        v = grp.to_numpy()
        doy = grp.index.dayofyear.to_numpy()
        if v.size < 4 or not np.isfinite(v).any():
            continue
        vmin, vmax = float(np.nanmin(v)), float(np.nanmax(v))
        amp = vmax - vmin
        pos = int(doy[int(np.nanargmax(v))])
        thr = vmin + frac * amp
        up = np.where(v >= thr)[0]
        sos = int(doy[up[0]]) if up.size else None
        eos = int(doy[up[-1]]) if up.size else None
        out[int(yr)] = {"sos": sos, "pos": pos, "eos": eos,
                        "length": (eos - sos) if (sos and eos) else None,
                        "amplitude": round(amp, 4)}
    return out


def phenology_table(dataset) -> "pd.DataFrame":
    """Per-field phenology summary across all years (for inspection / a figure)."""
    rows = []
    for f in dataset.fields:
        for yr, ph in extract_phenology(f.ndvi, dataset.dates).items():
            rows.append({"field_id": f.field_id, "year": yr, **ph})
    return pd.DataFrame(rows)
