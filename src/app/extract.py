"""Windowed zonal statistics: many polygons, one read per band per scene.

The treated area and hundreds of donor cells are read from the same COG window,
rasterised to a label image once per resolution, and reduced with bincount.
That keeps a run to a few HTTP range requests per scene instead of hundreds.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window, from_bounds
from shapely.geometry import box

from .geometry import reproject

GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
                GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="1",
                GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                GDAL_HTTP_MULTIPLEX="YES", VSI_CACHE="TRUE", VSI_CACHE_SIZE="50000000")

SNAP_M = 60.0     # Sentinel-2 tile origins are multiples of 60 m, so a 60 m snap
                  # makes the 10 m and 20 m windows cover the same ground exactly


@dataclass
class Zones:
    """Polygons in the scene CRS plus the snapped bounds that contain them."""
    polygons: list
    epsg: int
    bounds: tuple[float, float, float, float]

    @classmethod
    def build(cls, polygons_utm: list, src_epsg: int, dst_epsg: int, pad_m: float = 20.0,
              snap_m: float | None = SNAP_M) -> "Zones":
        polys = [reproject(p, src_epsg, dst_epsg) for p in polygons_utm]
        geographic = dst_epsg == 4326
        pad = pad_m / 111_000.0 if geographic else pad_m
        minx = min(p.bounds[0] for p in polys) - pad
        miny = min(p.bounds[1] for p in polys) - pad
        maxx = max(p.bounds[2] for p in polys) + pad
        maxy = max(p.bounds[3] for p in polys) + pad
        if geographic or not snap_m:
            return cls(polys, dst_epsg, (minx, miny, maxx, maxy))
        snap = lambda v, up: (np.ceil(v / snap_m) if up else np.floor(v / snap_m)) * snap_m
        return cls(polys, dst_epsg, (snap(minx, False), snap(miny, False), snap(maxx, True), snap(maxy, True)))


def _window(ds, bounds) -> Window:
    w = from_bounds(*bounds, transform=ds.transform)
    col0, row0 = int(np.floor(w.col_off)), int(np.floor(w.row_off))
    col1, row1 = int(np.ceil(w.col_off + w.width)), int(np.ceil(w.row_off + w.height))
    # clip to the dataset; areas outside are nodata
    col0c, row0c = max(col0, 0), max(row0, 0)
    col1c, row1c = min(col1, ds.width), min(row1, ds.height)
    if col1c <= col0c or row1c <= row0c:
        return None
    return Window(col0c, row0c, col1c - col0c, row1c - row0c)


def labels_for(zones: Zones, transform, shape) -> np.ndarray:
    """Label image: 0 = background, k = zones.polygons[k-1]."""
    shapes = [(p, i + 1) for i, p in enumerate(zones.polygons)]
    return rasterize(shapes, out_shape=shape, transform=transform, fill=0,
                     dtype="int32", all_touched=False)


def read_window(href: str, zones: Zones, out_res: float | None = None):
    """Read the zone window from a COG. Returns (array, transform, nodata) or None
    when the window falls entirely outside the dataset."""
    with rasterio.Env(**GDAL_ENV):
        with rasterio.open(href) as ds:
            if ds.crs is None or ds.crs.to_epsg() != zones.epsg:
                raise ValueError(f"scene CRS {ds.crs} != zones EPSG:{zones.epsg}")
            win = _window(ds, zones.bounds)
            if win is None:
                return None
            if out_res and abs(ds.res[0] - out_res) > 1e-6:
                f = ds.res[0] / out_res
                out_shape = (int(round(win.height * f)), int(round(win.width * f)))
                arr = ds.read(1, window=win, out_shape=out_shape,
                              resampling=rasterio.enums.Resampling.nearest)
                tr = ds.window_transform(win)
                tr = rasterio.Affine(out_res, 0, tr.c, 0, -out_res, tr.f)
            else:
                arr = ds.read(1, window=win)
                tr = ds.window_transform(win)
            return arr, tr, ds.nodata


def zone_means(values: np.ndarray, valid: np.ndarray, labels: np.ndarray, n: int):
    """Per-zone mean of `values` over pixels where `valid`, plus pixel counts.

    Returns (means[n], n_valid[n], n_total[n]); mean is NaN where no valid pixel.
    """
    lab = labels.ravel()
    n_total = np.bincount(lab, minlength=n + 1)[1:]
    v = valid.ravel() & (lab > 0)
    n_valid = np.bincount(lab[v], minlength=n + 1)[1:]
    sums = np.bincount(lab[v], weights=values.ravel()[v].astype(float), minlength=n + 1)[1:]
    with np.errstate(invalid="ignore", divide="ignore"):
        means = np.where(n_valid > 0, sums / np.maximum(n_valid, 1), np.nan)
    return means, n_valid, n_total
