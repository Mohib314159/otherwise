"""Server-side Sentinel-1 RTC reads for the live profile's donor cells.

This is the S1 counterpart of `remote_s2`. The PC data API (titiler) decodes
the float32 gamma0 COGs and returns one small PNG per scene over the ring
window. The per-cell means are then taken locally, following the rules of
`s1.process_scene` (the reference, not modified here):

  * assets vv and vh, linear gamma0 power, same window and output grid
  * a pixel is valid when finite, > 0 and not nodata (-32768) in BOTH pols
  * valid_frac = valid px / cell px; cells below VALID_MIN are NaN
  * the cell mean is taken in LINEAR power and then converted to dB
  * RATIO = VH_dB - VV_dB (difference of the dB cell means)
  * donor-only group: the scene is dropped when no cell reaches VALID_MIN

Wire format. Linear power spans orders of magnitude, so each pixel is sent as
dB on a fixed 16-bit scale (two uint8 PNG bands per polarisation):
    code = floor((clip(dB, DB_MIN, DB_MAX) - DB_MIN) * SCALE + 0.5) + 1   valid
    code = CODE_INVALID                       not > 0, or NaN
    code = CODE_MASKED (0)                    the server's own nodata mask
The step is 1/SCALE dB, about 0.002 dB, so a pixel's linear power is within
0.023 % of the source. It is decoded back to linear before averaging, so the
linear-then-dB order of the local path is kept. The server masks nodata
(-32768) in either polarisation, and the local path treats those pixels as
invalid too, so here the mask carries no deviation (unlike DN 0 for S2).

Known deviation (measured, scripts/bench_remote_s1.py): when the window is
clipped to the scene grid and window px / 4 is not integral, the server's
nearest-neighbour row choice can differ from local GDAL's by one source row
for a few output rows (seen: 3 rows of 542). Over 3 sites x 30 scenes that
moved 3 of 8,973 VV cell values (2 VH, 3 RATIO) by more than 0.01 dB, max
0.13 dB; valid_frac decisions were unchanged.
"""
from __future__ import annotations

import time

import numpy as np

from .extract import Zones
from .remote_s2 import (RemoteError, SceneCells, bbox_url, cell_labels, clip_bounds, decode_png,
                        get_bytes, label_transform, output_grid)
from .s1 import POLS, VALID_MIN, to_db

COLLECTION = "sentinel-1-rtc"
DB_MIN, DB_MAX = -80.0, 50.0
SCALE = 64000.0 / (DB_MAX - DB_MIN)          # codes 1 .. 64001
CODE_INVALID = 65535
CODE_MASKED = 0
ASSET = {"VV": "vv", "VH": "vh"}


# --- expression builder (pure) ------------------------------------------------

def code_term(pol: str) -> str:
    v = f"{ASSET[pol]}_b1"
    db = f"(10.0*log10({v}))"
    clipped = f"where({db}<{DB_MIN:.1f},{DB_MIN:.1f},where({db}>{DB_MAX:.1f},{DB_MAX:.1f},{db}))"
    return f"where({v}>0,floor(({clipped}-({DB_MIN:.1f}))*{SCALE!r}+1.5),{CODE_INVALID:.1f})"


def build_expression(pols=POLS) -> str:
    """Two bands per polarisation: hi byte, lo byte of the code."""
    parts = []
    for p in pols:
        q = code_term(p)
        hi = f"floor({q}/256.0)"
        parts += [hi, f"{q}-{hi}*256.0"]
    return ";".join(parts)


def encode_db(db):
    """Reference encoder (what the server computes) for tests."""
    return np.floor((np.clip(np.asarray(db, dtype="float64"), DB_MIN, DB_MAX) - DB_MIN) * SCALE + 0.5) + 1


def decode_codes(hi: np.ndarray, lo: np.ndarray):
    """(linear power float64, NaN where invalid; valid bool)."""
    q = hi.astype(np.int32) * 256 + lo.astype(np.int32)
    valid = (q >= 1) & (q <= int(round((DB_MAX - DB_MIN) * SCALE)) + 1)
    db = np.where(valid, (q - 1) / SCALE + DB_MIN, np.nan)
    return np.where(valid, 10.0 ** (db / 10.0), np.nan), valid


def request_params(item_id: str, epsg: int, expression: str, n_bands: int):
    return ([("collection", COLLECTION), ("item", item_id), ("expression", expression),
             ("coord_crs", f"epsg:{epsg}"), ("dst_crs", f"epsg:{epsg}"),
             ("resampling", "nearest"), ("return_mask", "false")]
            + [("rescale", "0,255")] * n_bands)


def reduce_linear(lin: dict, valid: np.ndarray, labels: np.ndarray, n: int):
    """Per-cell linear mean over pixels valid in both pols, then dB; as s1.process_scene."""
    lab = labels.ravel()
    n_total = np.bincount(lab, minlength=n + 1)[1:]
    v = valid.ravel() & (lab > 0)
    n_valid = np.bincount(lab[v], minlength=n + 1)[1:]
    with np.errstate(invalid="ignore", divide="ignore"):
        vf = np.where(n_total > 0, n_valid / np.maximum(n_total, 1), 0.0)
    out = {}
    for pol, arr in lin.items():
        s = np.bincount(lab[v], weights=arr.ravel()[v], minlength=n + 1)[1:]
        with np.errstate(invalid="ignore", divide="ignore"):
            m = np.where(n_valid > 0, s / np.maximum(n_valid, 1), np.nan)
        m[vf < VALID_MIN] = np.nan
        out[pol] = to_db(m)
    out["RATIO"] = out["VH"] - out["VV"]
    return out, vf, n_total


# --- network ------------------------------------------------------------------

def item_fields(item):
    """(id, epsg, grid bounds) from a STAC item dict or a providers.Scene."""
    if isinstance(item, dict):
        p = item.get("properties", {})
        epsg = p.get("proj:epsg")
        if epsg is None and str(p.get("proj:code", "")).upper().startswith("EPSG:"):
            epsg = int(p["proj:code"].split(":")[1])
        gb = (item.get("assets", {}).get("vv", {}) or {}).get("proj:bbox") or p.get("proj:bbox")
        return item["id"], epsg, tuple(gb) if gb else None
    gb = item.props.get("grid_bounds")
    return item.id, item.epsg, tuple(gb) if gb else None


def fetch_scene_cells(item, area_epsg: int, cells: list, res_m: float = 40.0,
                      zones: Zones | None = None, timeout: float = 120.0, retries: int = 4,
                      base: str | None = None) -> SceneCells:
    """Per-cell VV/VH/RATIO (dB), valid_frac and n_px for one S1 RTC scene, one request."""
    from .remote_s2 import PC_DATA
    item_id, epsg, grid_bounds = item_fields(item)
    if epsg is None:
        raise RemoteError("scene has no proj:epsg; cannot request its native grid")
    if zones is None:
        zones = Zones.build(cells, area_epsg, epsg)
    t0, c0 = time.perf_counter(), time.process_time()
    bounds = clip_bounds(zones.bounds, grid_bounds)
    if bounds is None:
        raise RemoteError("window is outside the scene's grid")
    w, h = output_grid(bounds, res_m, 10.0)
    content, attempts, statuses = get_bytes(bbox_url(bounds, w, h, "png", base or PC_DATA),
                                            request_params(item_id, epsg, build_expression(), 4),
                                            timeout=timeout, retries=retries)
    t_net = time.perf_counter() - t0
    stack = decode_png(content)
    if stack.shape != (4, h, w):
        raise RemoteError(f"expected {(4, h, w)}, got {stack.shape}")
    vv, ok_vv = decode_codes(stack[0], stack[1])
    vh, ok_vh = decode_codes(stack[2], stack[3])
    labels = cell_labels(zones, label_transform(bounds, res_m), (h, w))
    values, vf, n_px = reduce_linear({"VV": vv, "VH": vh}, ok_vv & ok_vh, labels, len(zones.polygons))
    stats = {"wall_s": time.perf_counter() - t0, "net_s": t_net, "cpu_s": time.process_time() - c0,
             "bytes": len(content), "attempts": attempts, "statuses": statuses, "shape": (h, w),
             "clipped_px": int(np.sum((stack[0].astype(int) * 256 + stack[1] == 1)
                                      | (stack[0].astype(int) * 256 + stack[1] == 64001)))}
    return SceneCells(item_id, values, vf, n_px, stats)


def process_scene_remote(scene, zones: Zones, sign=None, res: float = 40.0,
                         require_zone0: bool = False):
    """Drop-in for `s1.process_scene` on a donor-only group. Raises RemoteError
    on failure so the caller can fall back to the local read."""
    from .s1 import S1Observation
    from .s2 import Receipt
    if require_zone0:
        raise ValueError("remote reads are for donor-only groups (require_zone0=False)")
    sc = fetch_scene_cells(scene, zones.epsg, zones.polygons, res, zones=zones)
    if not np.any(sc.clear_frac >= VALID_MIN):
        return None, Receipt("S1", scene.date, scene.id, "outside", "No donor cell in this group is covered.")
    props = dict(scene.props)
    props["read"] = "pc-data-api"
    return S1Observation(scene.id, scene.date, scene.minute_key, sc.values, sc.clear_frac, sc.n_px,
                         props=props), None
