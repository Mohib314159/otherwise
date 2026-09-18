"""Static covariates per zone for donor shortlisting: ESA WorldCover land cover
and Copernicus DEM elevation/slope. Both are open, tiled COGs on AWS.

Attribution: WorldCover (c) ESA WorldCover project / Contains modified
Copernicus Sentinel data, CC BY 4.0. Copernicus DEM (c) DLR e.V. and Airbus
Defence and Space GmbH, provided under COPERNICUS by the European Union and ESA.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .extract import Zones, labels_for, read_window, zone_means

WC_CLASSES = {10: "tree cover", 20: "shrubland", 30: "grassland", 40: "cropland",
              50: "built-up", 60: "bare / sparse", 70: "snow and ice", 80: "water",
              90: "herbaceous wetland", 95: "mangroves", 100: "moss and lichen"}


def worldcover_url(lon: float, lat: float, year: int) -> str:
    lat0 = int(math.floor(lat / 3.0) * 3)
    lon0 = int(math.floor(lon / 3.0) * 3)
    ns = "N" if lat0 >= 0 else "S"
    ew = "E" if lon0 >= 0 else "W"
    tile = f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}"
    if year <= 2020:
        return f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v100/2020/map/ESA_WorldCover_10m_2020_v100_{tile}_Map.tif"
    return f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"


def dem_url(lon: float, lat: float) -> str:
    lat0 = int(math.floor(lat)); lon0 = int(math.floor(lon))
    ns = "N" if lat0 >= 0 else "S"; ew = "E" if lon0 >= 0 else "W"
    name = f"Copernicus_DSM_COG_10_{ns}{abs(lat0):02d}_00_{ew}{abs(lon0):03d}_00_DEM"
    return f"https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/{name}/{name}.tif"


def _tiles(bounds, step: float):
    minx, miny, maxx, maxy = bounds
    xs = np.arange(math.floor(minx / step) * step, maxx, step)
    ys = np.arange(math.floor(miny / step) * step, maxy, step)
    return [(x + step / 2, y + step / 2) for x in xs for y in ys]     # tile centres


@dataclass
class Covariates:
    landcover: np.ndarray        # (n,) dominant WorldCover class code, 0 if unknown
    landcover_frac: np.ndarray   # (n,) fraction of the zone in that class
    elevation: np.ndarray        # (n,) mean metres, NaN if unknown
    slope: np.ndarray            # (n,) mean slope in degrees, NaN if unknown
    year: int

    def label(self, i: int) -> str:
        return WC_CLASSES.get(int(self.landcover[i]), "unknown")


def _accumulate(url_fn, zones: Zones, step: float, reduce, out_res: float | None = None):
    """Read every tile touching the zone bounds and let `reduce` add to sums."""
    for cx, cy in _tiles(zones.bounds, step):
        url = url_fn(cx, cy)
        try:
            r = read_window(url, zones, out_res=out_res)
        except Exception:
            continue
        if r is None:
            continue
        arr, tr, nodata = r
        labels = labels_for(zones, tr, arr.shape)
        reduce(arr, labels, nodata, tr)


def fetch_covariates(polygons_utm: list, src_epsg: int, year: int, coarse: bool = False) -> Covariates:
    """coarse=True reads WorldCover at ~100 m and the DEM at ~60 m, for wide
    search areas where the native windows would be tens of millions of pixels."""
    zones = Zones.build(polygons_utm, src_epsg, 4326)
    wc_res = 8.333333333333333e-4 if coarse else None
    dem_res = 5.555555555555556e-4 if coarse else None
    n = len(polygons_utm)
    codes = sorted(WC_CLASSES)
    class_counts = np.zeros((n, len(codes)))
    elev_sum = np.zeros(n); elev_n = np.zeros(n)
    slope_sum = np.zeros(n); slope_n = np.zeros(n)

    def wc_reduce(arr, labels, nodata, tr):
        for k, c in enumerate(codes):
            _, nv, _ = zone_means(np.zeros_like(arr, dtype="float32"), arr == c, labels, n)
            class_counts[:, k] += nv

    def dem_reduce(arr, labels, nodata, tr):
        valid = np.isfinite(arr)
        if nodata is not None:
            valid &= arr != nodata
        m, nv, _ = zone_means(np.nan_to_num(arr), valid, labels, n)
        elev_sum[:] += np.nan_to_num(m) * nv; elev_n[:] += nv
        # slope from the gradient; pixel size in metres from the geographic transform
        lat = tr.f + tr.e * arr.shape[0] / 2
        dy = abs(tr.e) * 111_320.0
        dx = abs(tr.a) * 111_320.0 * math.cos(math.radians(lat))
        gy, gx = np.gradient(np.where(valid, arr, np.nan).astype(float), dy, dx)
        slope = np.degrees(np.arctan(np.hypot(gx, gy)))
        sv = valid & np.isfinite(slope)
        ms, ns_, _ = zone_means(np.nan_to_num(slope), sv, labels, n)
        slope_sum[:] += np.nan_to_num(ms) * ns_; slope_n[:] += ns_

    _accumulate(lambda x, y: worldcover_url(x, y, year), zones, 3.0, wc_reduce, out_res=wc_res)
    _accumulate(dem_url, zones, 1.0, dem_reduce, out_res=dem_res)

    tot = class_counts.sum(axis=1)
    dom = np.where(tot > 0, np.asarray(codes)[np.argmax(class_counts, axis=1)], 0)
    frac = np.where(tot > 0, class_counts.max(axis=1) / np.maximum(tot, 1), 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        elev = np.where(elev_n > 0, elev_sum / np.maximum(elev_n, 1), np.nan)
        slope = np.where(slope_n > 0, slope_sum / np.maximum(slope_n, 1), np.nan)
    return Covariates(dom.astype(int), frac, elev, slope, year)
