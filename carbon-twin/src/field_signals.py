"""
Sub-5m per-field signal extractors. Each turns a pixel cube into a 1-D signal per
parcel over time -> FieldSeries -> the SAME SCM engine (fit + placebo_test). No
core changes: the engine never knew what NDVI meant; it only sees arrays.

Ready to fire the moment sub-5m Iowa data lands. (The NZ demo cube is 10m, so a
small parcel is only a few pixels and texture is weak there; on sub-5m a field is
thousands of pixels and these signals come alive — confirm resolution with live data.)

  texture_std       within-field NDVI std           cover crop uniform (LOW) vs weeds patchy (HIGH)
  texture_contrast  mean sq adjacent-pixel diff      GLCM-contrast proxy, same discriminator
  albedo            mean visible+NIR brightness      bare window -> no-till/tillage + SOC-by-colour proxy
  perimeter_ratio   outer-ring mean / core mean      boundary-bleed fraud (inputs dumped at the fence)
"""
from __future__ import annotations

import numpy as np
from scipy.stats import kurtosis, skew

from .contract import Dataset, FieldSeries


def _texture_std(block):                      # block: (T, h, w) NDVI
    return np.array([np.nanstd(block[t]) if np.isfinite(block[t]).any() else np.nan
                     for t in range(block.shape[0])])


def _texture_contrast(block):                 # GLCM-contrast proxy
    out = np.full(block.shape[0], np.nan)
    for t in range(block.shape[0]):
        a = block[t]
        dh, dv = np.diff(a, axis=1), np.diff(a, axis=0)
        d = np.concatenate([dh[np.isfinite(dh)].ravel(), dv[np.isfinite(dv)].ravel()])
        if d.size:
            out[t] = float(np.mean(d ** 2))
    return out


def _albedo(bright):                          # bright: (T, h, w) mean reflectance
    return np.array([np.nanmean(bright[t]) if np.isfinite(bright[t]).any() else np.nan
                     for t in range(bright.shape[0])])


def _perimeter_ratio(block, ring=2):
    out = np.full(block.shape[0], np.nan)
    for t in range(block.shape[0]):
        a = block[t]; h, w = a.shape
        if h <= 2 * ring or w <= 2 * ring:
            continue
        core = a[ring:-ring, ring:-ring]
        mask = np.ones_like(a, bool); mask[ring:-ring, ring:-ring] = False
        cm, pm = np.nanmean(core), np.nanmean(a[mask])
        if np.isfinite(cm) and cm != 0:
            out[t] = float(pm / cm)
    return out


def _texture_skew(block):                     # asymmetry of the within-field pixel cloud
    out = np.full(block.shape[0], np.nan)
    for t in range(block.shape[0]):
        v = block[t][np.isfinite(block[t])]
        if v.size >= 8:
            out[t] = float(skew(v))
    return out


def _texture_bimodality(block):               # Sarle's bimodality coefficient (uniform vs split)
    out = np.full(block.shape[0], np.nan)
    for t in range(block.shape[0]):
        v = block[t][np.isfinite(block[t])]
        if v.size >= 8:
            k = kurtosis(v, fisher=False)
            if k > 0:
                g = skew(v)
                out[t] = float((g * g + 1.0) / k)
    return out


_EXTRACTORS = {"texture_std": _texture_std, "texture_contrast": _texture_contrast,
               "albedo": _albedo, "perimeter_ratio": _perimeter_ratio,
               "texture_skew": _texture_skew, "texture_bimodality": _texture_bimodality}


def signal_dataset(path: str, signal: str = "texture_std", tile: int = 20,
                   index: str = "NDVI") -> "Dataset":
    """Open a Sentinel-2 cube and build a Dataset whose per-parcel series is the
    chosen sub-5m signal — then audit it with the normal pipeline."""
    import xarray as _xr

    from .spectral import harmonise_reflectance, index_stack

    if signal not in _EXTRACTORS:
        raise ValueError(f"signal must be one of {list(_EXTRACTORS)}")
    cube = _xr.open_zarr(path)
    dates = cube["time"].values.astype("datetime64[D]")

    if signal == "albedo":
        R = harmonise_reflectance(cube)
        bands = [b for b in ("B02", "B03", "B04", "B08") if b in R]
        arr = np.nanmean(np.stack([R[b] for b in bands]), axis=0)
    else:
        arr = index_stack(cube)[index]
    T, ny, nx = arr.shape
    extract = _EXTRACTORS[signal]
    ys = cube["y"].values if "y" in cube.coords else np.arange(ny)
    xs = cube["x"].values if "x" in cube.coords else np.arange(nx)

    fields, pid = [], 0
    for iy in range(0, ny - tile + 1, tile):
        for ix in range(0, nx - tile + 1, tile):
            series = extract(arr[:, iy:iy + tile, ix:ix + tile])
            if np.isfinite(series).sum() < max(4, T // 4):
                continue
            fields.append(FieldSeries(
                field_id=f"P{pid:03d}", ndvi=series,
                lat=float(np.mean(ys[iy:iy + tile])), lon=float(np.mean(xs[ix:ix + tile])),
                area_ha=float((tile * 10) ** 2 / 1e4),
                claims_adoption=False, truth_label=signal))
            pid += 1
    return Dataset(dates=dates, fields=fields)
