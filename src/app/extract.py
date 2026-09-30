"""Windowed zonal statistics: many polygons, one read per band per scene.

The treated area and hundreds of donor cells are read from the same COG window,
rasterised to a label image once per resolution, and reduced with bincount.
That keeps a run to a few HTTP range requests per scene instead of hundreds.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window, from_bounds
from shapely.geometry import box

from .geometry import reproject

# VSI_CACHE_SIZE is per open file handle. At 50 MB, eight worker threads holding
# five band handles each can park 2 GB in GDAL's cache alone, which is most of a
# 512 MB container before a single array is allocated. 4 MB is enough to keep
# consecutive range requests cheap. GDAL_CACHEMAX defaults to a share of *host*
# RAM, which a container's cgroup limit does not constrain, so it is pinned too.
GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
                GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="1",
                GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                GDAL_HTTP_MULTIPLEX="YES", VSI_CACHE="TRUE",
                VSI_CACHE_SIZE=int(os.environ.get("APP_VSI_CACHE_BYTES", 4_000_000)),
                GDAL_CACHEMAX=int(os.environ.get("APP_GDAL_CACHEMAX_MB", 32)),
                GDAL_NUM_THREADS="1")

SNAP_M = 60.0     # Sentinel-2 tile origins are multiples of 60 m, so a 60 m snap
                  # makes the 10 m and 20 m windows cover the same ground exactly


@dataclass
class Zones:
    """Polygons in the scene CRS plus the snapped bounds that contain them."""
    polygons: list
    epsg: int
    bounds: tuple[float, float, float, float]
    # Label images already rasterised for this Zones, keyed by (transform, shape).
    # Every scene of one CRS whose window is not clipped by a tile edge has the
    # same transform and shape, so a run rasterises a handful of label images
    # instead of one per scene. Not part of equality or repr.
    _labels: dict = field(default_factory=dict, repr=False, compare=False)
    _lock: object = field(default_factory=threading.Lock, repr=False, compare=False)

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


def window_geometry(ds, zones: Zones, out_res: float | None = None):
    """Where the zone window sits in an open dataset and what `read_window`
    returns for it: (window, transform, out_shape), or None when the
    window falls entirely outside the dataset. `out_shape` is None for a
    native-resolution read. Same arithmetic `read_window` has always used."""
    if ds.crs is None or ds.crs.to_epsg() != zones.epsg:
        raise ValueError(f"scene CRS {ds.crs} != zones EPSG:{zones.epsg}")
    win = _window(ds, zones.bounds)
    if win is None:
        return None
    if out_res and (abs(ds.res[0] - out_res) > 1e-9 or abs(ds.res[1] - out_res) > 1e-9):
        fy, fx = ds.res[1] / out_res, ds.res[0] / out_res
        out_shape = (max(int(round(win.height * fy)), 1), max(int(round(win.width * fx)), 1))
        tr = ds.window_transform(win)
        tr = rasterio.Affine(out_res, 0, tr.c, 0, -out_res, tr.f)
        return win, tr, out_shape
    return win, ds.window_transform(win), None


def upsample_factor(win, out_shape) -> int | None:
    """k when `out_shape` is exactly the window upsampled k x k (k >= 2)."""
    if out_shape is None or win.height < 1:
        return None
    k = out_shape[0] // win.height
    return k if k >= 2 and out_shape == (win.height * k, win.width * k) else None


def read_geometry(ds, geom):
    """Read the window described by `window_geometry` from an open dataset.

    An integer upsample (20 m SCL/B12 to 10 m) is read at native resolution and
    replicated k x k in numpy. For an integer factor, GDAL's nearest-neighbour
    RasterIO maps output pixel i to source pixel floor((i + 0.5) / k) = i // k,
    which is exactly this replication, so the array is identical. Letting GDAL
    do it was the single largest cost of a run: its resampled read decoded the
    window's blocks over and over through a 32 MB block cache shared by all
    worker threads (measured: 12.5 s CPU and up to minutes of wall per B12
    read, against a fraction of a second for the same window at native
    resolution). Downsampling still goes through GDAL, which uses overviews.
    """
    win, tr, out_shape = geom
    k = upsample_factor(win, out_shape)
    if k is not None:
        return np.repeat(np.repeat(ds.read(1, window=win), k, axis=0), k, axis=1)
    if out_shape is not None:
        return ds.read(1, window=win, out_shape=out_shape,
                       resampling=rasterio.enums.Resampling.nearest)
    return ds.read(1, window=win)


def read_window(href: str, zones: Zones, out_res: float | None = None):
    """Read the zone window from a COG. Returns (array, transform, nodata) or None
    when the window falls entirely outside the dataset."""
    with rasterio.Env(**GDAL_ENV):
        with rasterio.open(href) as ds:
            geom = window_geometry(ds, zones, out_res)
            if geom is None:
                return None
            return read_geometry(ds, geom), geom[1], ds.nodata


def cached_labels(zones: Zones, transform, shape):
    """`labels_for` plus the `zone_bbox` of zone 1 (the first polygon),
    memoised on the Zones object. Returns (labels, bbox). The label image is
    shared between threads and marked read-only."""
    key = (tuple(transform)[:6], tuple(shape))
    with zones._lock:
        hit = zones._labels.get(key)
    if hit is not None:
        return hit
    lab = labels_for(zones, transform, shape)
    lab.flags.writeable = False
    entry = (lab, zone_bbox(lab, 1))
    with zones._lock:
        if key not in zones._labels and len(zones._labels) >= LABEL_CACHE_MAX:
            zones._labels.pop(next(iter(zones._labels)))
        return zones._labels.setdefault(key, entry)


LABEL_CACHE_MAX = 4    # distinct windows per CRS (tile edges clip some); 24 MB each at 6 Mpx


def zone_bbox(labels: np.ndarray, zone: int = 1):
    """(row0, row1, col0, col1), half-open, of the pixels labelled `zone` in a
    label image, or None if it has none."""
    rows = np.flatnonzero((labels == zone).any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero((labels[rows[0]:rows[-1] + 1] == zone).any(axis=0))
    return int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1


ROW_CHUNK = 512      # rows reduced at a time, so transients stay bounded


def zone_counts(labels: np.ndarray, n: int, valid: np.ndarray | None = None):
    """Pixels per zone (and, with `valid`, usable pixels per zone).

    Counting needs no value array; the old code allocated a full-size float32
    of zeros just to reach `zone_means`, which on a 6 Mpx window cost 24 MB per
    scene per thread for nothing.
    """
    lab = labels.ravel()
    n_total = np.bincount(lab, minlength=n + 1)[1:]
    if valid is None:
        return n_total
    v = valid.ravel() & (lab > 0)
    return np.bincount(lab[v], minlength=n + 1)[1:], n_total


def zone_means(values: np.ndarray, valid: np.ndarray, labels: np.ndarray, n: int):
    """Per-zone mean of `values` over pixels where `valid`, plus pixel counts.

    Returns (means[n], n_valid[n], n_total[n]); mean is NaN where no valid pixel.

    Reduced in row blocks: the boolean-indexed temporaries (`lab[v]`, and the
    float64 the weights are upcast to) are the largest allocations in a scene
    read, and chunking caps them at ROW_CHUNK rows instead of the whole window.
    """
    lab_full = labels.reshape(labels.shape[0], -1)
    val_full = values.reshape(labels.shape[0], -1)
    vld_full = valid.reshape(labels.shape[0], -1)
    n_total = np.zeros(n + 1, dtype=np.int64)
    n_valid = np.zeros(n + 1, dtype=np.int64)
    sums = np.zeros(n + 1, dtype=np.float64)
    for r0 in range(0, labels.shape[0], ROW_CHUNK):
        lab = lab_full[r0:r0 + ROW_CHUNK].ravel()
        n_total += np.bincount(lab, minlength=n + 1)
        v = vld_full[r0:r0 + ROW_CHUNK].ravel() & (lab > 0)
        if not v.any():
            continue
        labv = lab[v]
        n_valid += np.bincount(labv, minlength=n + 1)
        sums += np.bincount(labv, weights=val_full[r0:r0 + ROW_CHUNK].ravel()[v], minlength=n + 1)
        del lab, v, labv
    n_total, n_valid, sums = n_total[1:], n_valid[1:], sums[1:]
    with np.errstate(invalid="ignore", divide="ignore"):
        means = np.where(n_valid > 0, sums / np.maximum(n_valid, 1), np.nan)
    return means, n_valid, n_total
