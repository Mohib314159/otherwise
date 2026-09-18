"""
Intentionality detection: is the winter green a PLANTED cover crop or just WEEDS?

NDVI mean cannot tell them apart — both are green and neither is bare soil. But a
planted cover crop is *drilled*: spatially uniform across the field. Weeds are
opportunistic: patchy, denser at edges and in wet spots. At sub-5m resolution (the
Theme-B data) we can measure that WITHIN-FIELD texture. So we add a discriminator:

  green off-season + LOW within-field texture (uniform)  -> MANAGED cover crop
  green off-season + HIGH within-field texture (patchy)  -> LIKELY WEEDS (flag)
  no off-season green                                    -> NONE

HONESTY: this is a *probabilistic discriminator*, not a perfect classifier. Some
cover crops establish patchily and some weeds are uniform; the texture threshold
would be calibrated on labelled fields. Its value is moving weeds from an invisible
loophole to a flagged low-confidence case — exactly the kind of intentionality
signal first-mile data couldn't deliver before sub-5m imagery.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .contract import Dataset, FieldSeries, offseason_mask

_LAT0, _LON0 = 41.74, -92.72
TEXTURE_MAX = 0.08          # within-field NDVI std below which green reads as "managed"
GREEN_MIN = 0.06            # off-season NDVI uplift over the field's own pre-baseline


def _phenology(doy, baseline, amp):
    return baseline + amp * np.exp(-((doy - 200.0) ** 2) / (2 * 48.0 ** 2))


def _osw(doy):
    w = np.zeros_like(doy, dtype=float)
    w[(doy >= 288) | (doy <= 120)] = 1.0
    return 0.5 * (w + np.clip(np.cos((doy - 30) / 90.0), 0, 1))


def generate_management(seed: int = 23):
    """Return (ndvi_ds, texture_ds): mean NDVI and within-field NDVI std per field.

    cover_crop : uniform winter green (managed)   -> low texture
    weeds      : patchy winter green (incidental)  -> high texture
    conventional: bare in winter                   -> low texture, no green
    """
    rng = np.random.default_rng(seed)
    dates = np.arange(np.datetime64("2019-01-01"), np.datetime64("2025-12-31"),
                      np.timedelta64(16, "D")).astype("datetime64[D]")
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    doy = (dates - dates.astype("datetime64[Y]")).astype("timedelta64[D]").astype(int) + 1
    osw = _osw(doy)
    active = (years >= 2021).astype(float)

    roster = ([("cover_crop", 0.24, 0.035)] * 4
              + [("weeds", 0.20, 0.14)] * 4
              + [("conventional", 0.0, 0.03)] * 16)
    rng.shuffle(roster)

    ndvi_fields, tex_fields = [], []
    for i, (label, green, tex_green) in enumerate(roster):
        baseline = 0.17 + rng.normal(0, 0.02)
        amp = 0.66 + rng.normal(0, 0.03)
        ndvi = _phenology(doy, baseline, amp) + green * osw * active
        ndvi = np.clip(ndvi + rng.normal(0, 0.02, ndvi.shape), -0.05, 0.97)

        # within-field NDVI std: low everywhere normally; during managed winter green
        # it stays low (uniform), during weedy winter green it is high (patchy).
        tex = 0.03 + rng.normal(0, 0.004, doy.shape)
        winter_green = osw * active
        tex = tex + tex_green * winter_green
        tex = np.clip(tex + rng.normal(0, 0.004, doy.shape), 0.0, 0.4)

        # optical cloud gaps
        ndvi[rng.random(ndvi.shape) < 0.20] = np.nan
        tex[np.isnan(ndvi)] = np.nan

        meta = dict(lat=_LAT0 + rng.normal(0, 0.015), lon=_LON0 + rng.normal(0, 0.02),
                    area_ha=float(rng.uniform(28, 64)),
                    claims_adoption=(label in ("cover_crop", "weeds")),
                    truth_label=label, truth_year=2021 if label != "conventional" else None)
        ndvi_fields.append(FieldSeries(field_id=f"M{i:02d}", ndvi=ndvi, **meta))
        tex_fields.append(FieldSeries(field_id=f"M{i:02d}", ndvi=tex, **meta))
    return Dataset(dates=dates, fields=ndvi_fields), Dataset(dates=dates, fields=tex_fields)


@dataclass
class ManagementVerdict:
    field_id: str
    green_uplift: float          # off-season NDVI rise vs the field's own pre-baseline
    texture: float               # mean within-field NDVI std during off-season green
    verdict: str                 # MANAGED COVER CROP | LIKELY WEEDS | NO COVER
    truth_label: str | None


def discriminate(ndvi_ds: Dataset, texture_ds: Dataset, target_id: str) -> ManagementVerdict:
    """Classify winter green as managed cover crop vs incidental weeds via texture."""
    import pandas as pd
    f = ndvi_ds.by_id(target_id)
    tf = texture_ds.by_id(target_id)
    yrs = np.asarray(pd.to_datetime(ndvi_ds.dates).year)
    os_mask = offseason_mask(ndvi_ds.dates, f.lat)

    pre = os_mask & (yrs <= 2020)
    post = os_mask & (yrs >= 2021)
    pre_green = np.nanmean(f.ndvi[pre]) if np.any(pre & ~np.isnan(f.ndvi)) else np.nan
    post_green = np.nanmean(f.ndvi[post]) if np.any(post & ~np.isnan(f.ndvi)) else np.nan
    uplift = float(post_green - pre_green) if np.isfinite(pre_green) and np.isfinite(post_green) else 0.0

    # texture only where there is post green
    green_pts = post & ~np.isnan(tf.ndvi) & (f.ndvi > (pre_green + GREEN_MIN if np.isfinite(pre_green) else 0.3))
    texture = float(np.nanmean(tf.ndvi[green_pts])) if np.any(green_pts) else float(np.nanmean(tf.ndvi[post]))

    if uplift < GREEN_MIN:
        verdict = "NO COVER"
    elif texture <= TEXTURE_MAX:
        verdict = "MANAGED COVER CROP"
    else:
        verdict = "LIKELY WEEDS"
    return ManagementVerdict(target_id, uplift, texture, verdict, f.truth_label)
