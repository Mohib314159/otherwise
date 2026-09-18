"""
Multi-spectral extraction from a real Sentinel-2 cube (Treefera demo format).

One cube of raw bands becomes a *stack of physical signals*, each a lens on the
field — and CarbonTwin's engine runs causal verification on any of them:

  NDVI  (B08,B04)        greenness / biomass
  NDRE  (B08,B05)        red-edge chlorophyll / nitrogen stress (pre-symptomatic)
  NDWI  (B03,B08)        open-water / surface moisture
  NDMI  (B08,B11)        vegetation moisture (SWIR)
  NDTI  (B11,B12)        tillage / crop-residue (SWIR)  -> the no-till signal
  BSI   (B11,B04,B08,B02) bare-soil exposure
  EVI   (B08,B04,B02)    biomass, less saturation/soil noise

Two real-data gotchas, both handled here (documented in the demo notebook):
  * Baseline 04.00: scenes on/after 2022-01-25 sit +1000 DN high. We subtract it
    (clamp 0) BEFORE computing indices — otherwise every cross-2022 NDVI is wrong.
  * n_obs == 0 means no clear observation that month -> masked to NaN, never
    interpolated into a fake value.
"""
from __future__ import annotations

import numpy as np

OPTICAL = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
BASELINE_CUTOVER = np.datetime64("2022-01-25")


def harmonise_reflectance(cube):
    """Undo the Baseline-04.00 +1000 DN offset, mask nodata, return reflectance.

    Returns a dict {band: float32 array (reflectance 0-1, NaN where no obs)}.
    Accepts an xarray Dataset with uint16 bands B0x and a `n_obs` variable.
    """
    import xarray as xr  # noqa

    times = cube["time"].values.astype("datetime64[D]")
    post = (times >= BASELINE_CUTOVER)[:, None, None]
    nodata = (cube["n_obs"].values == 0)

    out = {}
    for b in OPTICAL:
        if b not in cube:
            continue
        dn = cube[b].values.astype("float32")
        dn = np.where(post, np.clip(dn - 1000.0, 0, None), dn)   # harmonise
        refl = dn / 10000.0
        refl[nodata] = np.nan
        out[b] = refl
    return out


def _nd(a, b):
    """Normalised difference (a-b)/(a+b), NaN-safe."""
    denom = a + b
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(denom != 0, (a - b) / denom, np.nan)


def index_stack(cube) -> dict:
    """Compute the full stack of indices from a Sentinel-2 cube.

    Returns {index_name: array[time, y, x]}. Missing bands are skipped.
    """
    R = harmonise_reflectance(cube)
    g = R.get

    stack = {}
    if "B08" in R and "B04" in R:
        stack["NDVI"] = _nd(g("B08"), g("B04"))
        if "B02" in R:
            denom = g("B08") + 6 * g("B04") - 7.5 * g("B02") + 1.0
            with np.errstate(invalid="ignore", divide="ignore"):
                stack["EVI"] = np.where(denom != 0, 2.5 * (g("B08") - g("B04")) / denom, np.nan)
    if "B08" in R and "B05" in R:
        stack["NDRE"] = _nd(g("B08"), g("B05"))          # red-edge stress
    if "B03" in R and "B08" in R:
        stack["NDWI"] = _nd(g("B03"), g("B08"))          # water
    if "B08" in R and "B11" in R:
        stack["NDMI"] = _nd(g("B08"), g("B11"))          # veg moisture
    if "B11" in R and "B12" in R:
        stack["NDTI"] = _nd(g("B11"), g("B12"))          # tillage / residue
    if all(b in R for b in ("B11", "B04", "B08", "B02")):
        num = (g("B11") + g("B04")) - (g("B08") + g("B02"))
        den = (g("B11") + g("B04")) + (g("B08") + g("B02"))
        with np.errstate(invalid="ignore", divide="ignore"):
            stack["BSI"] = np.where(den != 0, num / den, np.nan)
    return stack


def available_indices(cube) -> list[str]:
    return list(index_stack(cube).keys())
