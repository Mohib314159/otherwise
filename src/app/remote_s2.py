"""Server-side Sentinel-2 reads for the live profile's control ring (prototype).

The live profile reads the control cells at 40 m from the COG overviews
(`fetch._fetch_live_ring` -> `s2.process_scene(res=40, require_zone0=False)`).
On a 0.1-CPU host the cost of that is fetching and inflating DEFLATE tiles for
five assets per scene. This module moves that work to the Planetary Computer
data API (titiler): ONE request per scene returns the cloud-masked index for
the whole ring window, on the grid the local read would have used, and the
per-cell means are taken locally with the same label image / bincount
reduction as `extract.py`.

Rules replicated from `s2.process_scene` (the reference; not modified here):
  * clear = SCL in {4, 5, 6} (`s2.SCL_CLEAR`); clear_frac = clear px / cell px
  * Baseline >= 04.00: DN - 1000 clipped at 0 (`s2.reflectance`); the /10000
    scale cancels in a normalised difference, so it is not sent
  * index = (a - b) / (a + b), undefined where a + b <= 0
  * cell mean over pixels that are clear AND have a defined index
  * cells with clear_frac < CLEAR_MIN are NaN
  * same window: zones bounds (60 m snapped, 20 m pad) clipped to the tile,
    same output shape (round(window px * native / res)), nearest resampling,
    and the same label grid convention (origin at the window corner, res_m px)

Measured (scripts/bench_remote_s2.py, 3 sites x 30 scenes): given the same
bbox and output size, titiler samples the same source pixels as the local
rasterio read and applies the expression per output pixel (bands are not
averaged before the expression), so the index rasters are identical to
float32 rounding. NB: with the 60 m window snap, the local 40 m read usually
does NOT hit the 40 m overview (window px / 4 is not integral), so both sides
nearest-sample native 10 m pixels; that is why a local read costs ~9-10 s CPU.

Wire format. titiler returns float64 uncompressed GeoTIFF for an expression
(12 MB for a 4-band ring window), and has no dtype option. So each index is
sent as a 16-bit code split into two uint8 PNG bands (hi, lo), with
`rescale=0,255` making the uint8 cast an identity:
    code = floor((v + 1) * SCALE + 0.5) + 1   usable pixel      (1 .. 2*SCALE + 1)
    code = CODE_UNDEF                         clear, index undefined (a + b <= 0)
    code = CODE_CLOUD                         not clear (SCL not in 4/5/6)
    code = CODE_MASKED (0)                    written by the server itself
Quantisation step 1/SCALE = 3.1e-5 in index units.

The one known deviation from the local path: the PC data API masks a pixel
when ANY asset in the expression has DN 0 (ESA's L2A NO_DATA value) and
writes 0 to every output band there; overriding `nodata` does not turn this
off (measured). Such pixels decode as "not clear, no value". The local path
treats DN 0 as data (NDVI = +-1 when one band is 0), so the two differ only
on those pixels: swath edges (not clear either way) and, in pre-04.00
baselines, zero-clipped dark pixels. See scripts/bench_remote_s2.py. PNG allows at most four
bands, so a request carries at most two indices (the controls only ever need
the run's primary index, plus NDVI for the donor despike).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import requests
from rasterio import Affine

from .extract import Zones, labels_for, zone_counts
from .s2 import CLEAR_MIN, DN_OFFSET, SCL_CLEAR, needs_offset

PC_DATA = "https://planetarycomputer.microsoft.com/api/data/v1"
COLLECTION = "sentinel-2-l2a"
SCALE = 32000.0
CODE_UNDEF = 65534
CODE_CLOUD = 65535
CODE_MASKED = 0
MAX_INDICES = 2                    # 2 PNG bands each; PNG caps at 4 bands
# (a, b) for (a - b) / (a + b), as in s2.indices_from_bands
INDEX_BANDS = {"NDVI": ("B08", "B04"), "NDWI": ("B03", "B08"), "NBR": ("B08", "B12")}
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


# --- expression builder (pure; unit-tested) ----------------------------------

def band_term(asset: str, baseline: str | None) -> str:
    """DN of `asset` as the local path sees it, as a numexpr term.

    With the Baseline-04 offset the local code does clip(DN - 1000, 0); float
    literals keep numexpr out of integer arithmetic on uint16."""
    v = f"{asset}_b1"
    if needs_offset(baseline):
        off = f"{DN_OFFSET:.1f}"
        return f"where({v}>{off},{v}-{off},0.0)"
    return f"({v}*1.0)"


def clear_term() -> str:
    return "(" + "|".join(f"(SCL_b1=={c})" for c in SCL_CLEAR) + ")"


def code_term(index: str, baseline: str | None) -> str:
    """16-bit code for one index (see module docstring)."""
    a_name, b_name = INDEX_BANDS[index]
    a, b = band_term(a_name, baseline), band_term(b_name, baseline)
    den = f"({a}+{b})"
    val = f"floor((({a}-{b})/{den}+1.0)*{SCALE:.1f}+1.5)"
    return f"where({clear_term()},where({den}>0,{val},{CODE_UNDEF:.1f}),{CODE_CLOUD:.1f})"


def build_expression(baseline: str | None, indices=("NDVI",)) -> str:
    """Two bands per index: hi byte, lo byte of the code."""
    indices = tuple(indices)
    if not 1 <= len(indices) <= MAX_INDICES:
        raise ValueError(f"1..{MAX_INDICES} indices per request, got {indices}")
    parts = []
    for i in indices:
        q = code_term(i, baseline)
        hi = f"floor({q}/256.0)"
        parts += [hi, f"{q}-{hi}*256.0"]
    return ";".join(parts)


def decode_codes(hi: np.ndarray, lo: np.ndarray):
    """(index value float64 with NaN where unusable, clear bool)."""
    q = hi.astype(np.int32) * 256 + lo.astype(np.int32)
    clear = (q != CODE_CLOUD) & (q != CODE_MASKED)
    ok = (q >= 1) & (q <= int(2 * SCALE) + 1)
    v = np.where(ok, (q - 1) / SCALE - 1.0, np.nan)
    return v, clear


def encode_value(v):
    """Reference encoder (what the server expression computes), for tests."""
    return np.floor((np.asarray(v, dtype="float64") + 1.0) * SCALE + 0.5) + 1


def output_grid(bounds, res_m: float, native_m: float = 10.0) -> tuple[int, int]:
    """(width, height) the local `read_window(out_res=res_m)` produces for this
    window from a `native_m` asset: window px * native/res, rounded."""
    minx, miny, maxx, maxy = bounds
    wpx, hpx = round((maxx - minx) / native_m), round((maxy - miny) / native_m)
    f = native_m / res_m
    return max(int(round(wpx * f)), 1), max(int(round(hpx * f)), 1)


def clip_bounds(bounds, tile_bounds):
    """The local read clips its window to the dataset; do the same."""
    if tile_bounds is None:
        return tuple(bounds)
    b = (max(bounds[0], tile_bounds[0]), max(bounds[1], tile_bounds[1]),
         min(bounds[2], tile_bounds[2]), min(bounds[3], tile_bounds[3]))
    if b[2] <= b[0] or b[3] <= b[1]:
        return None
    return b


def label_transform(bounds, res_m: float) -> Affine:
    """Grid convention of `extract.read_window` for a decimated read: origin at
    the window's top-left corner, square `res_m` pixels."""
    return Affine(res_m, 0.0, bounds[0], 0.0, -res_m, bounds[3])


def bbox_url(bounds, width: int, height: int, fmt: str = "png", base: str = PC_DATA) -> str:
    minx, miny, maxx, maxy = bounds
    return f"{base}/item/bbox/{minx:.3f},{miny:.3f},{maxx:.3f},{maxy:.3f}/{width}x{height}.{fmt}"


def request_params(item_id: str, epsg: int, expression: str, n_bands: int) -> list[tuple[str, str]]:
    p = [("collection", COLLECTION), ("item", item_id), ("expression", expression),
         ("coord_crs", f"epsg:{epsg}"), ("dst_crs", f"epsg:{epsg}"),
         ("resampling", "nearest"), ("return_mask", "false")]
    p += [("rescale", "0,255")] * n_bands
    return p


# --- zonal reduction (pure) ---------------------------------------------------

def reduce_cells(values: list[np.ndarray], clear: np.ndarray, labels: np.ndarray, n: int):
    """values: per-index arrays (NaN = unusable); clear: bool SCL-clear flag.

    Returns (means (k, n) NaN where no usable px, clear_frac (n,), n_px (n,)).
    CLEAR_MIN is not applied here."""
    n_clear, n_total = zone_counts(labels, n, clear)
    with np.errstate(invalid="ignore", divide="ignore"):
        clear_frac = np.where(n_total > 0, n_clear / np.maximum(n_total, 1), 0.0)
    lab = labels.ravel()
    means = np.full((len(values), n), np.nan)
    for k, arr in enumerate(values):
        band = arr.ravel()
        v = np.isfinite(band) & (lab > 0)
        cnt = np.bincount(lab[v], minlength=n + 1)[1:]
        s = np.bincount(lab[v], weights=band[v], minlength=n + 1)[1:]
        with np.errstate(invalid="ignore", divide="ignore"):
            means[k] = np.where(cnt > 0, s / np.maximum(cnt, 1), np.nan)
    return means, clear_frac, n_total


# --- network ------------------------------------------------------------------

@dataclass
class SceneCells:
    scene_id: str
    values: dict[str, np.ndarray]     # index -> (n,) mean, NaN where clear_frac < CLEAR_MIN
    clear_frac: np.ndarray
    n_px: np.ndarray
    stats: dict = field(default_factory=dict)   # timing, bytes, attempts
    raw: dict | None = None                     # decoded arrays, when keep_raw=True


class RemoteError(RuntimeError):
    pass


_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.mount("https://", requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=32))
        _session = s
    return _session


def get_bytes(url: str, params, timeout: float = 120.0, retries: int = 4,
              backoff: float = 2.0, sess: requests.Session | None = None):
    """GET with retries on 429/5xx/timeouts. Returns (bytes, attempts, statuses)."""
    sess = sess or session()
    statuses = []
    for attempt in range(retries + 1):
        try:
            r = sess.get(url, params=params, timeout=timeout)
            statuses.append(r.status_code)
            if r.status_code == 200:
                return r.content, attempt + 1, statuses
            if r.status_code not in RETRY_STATUS:
                raise RemoteError(f"HTTP {r.status_code}: {r.text[:200]}")
            ra = r.headers.get("Retry-After")
            wait = float(ra) if ra and ra.replace(".", "", 1).isdigit() else backoff * (2 ** attempt)
        except (requests.Timeout, requests.ConnectionError) as e:
            statuses.append(type(e).__name__)
            wait = backoff * (2 ** attempt)
        if attempt < retries:
            time.sleep(min(wait, 30.0))
    raise RemoteError(f"gave up after {retries + 1} attempts: {statuses}")


def decode_png(content: bytes) -> np.ndarray:
    from rasterio.io import MemoryFile
    with MemoryFile(content) as mf, mf.open() as ds:
        return ds.read()


_label_cache: dict = {}


def cell_labels(zones: Zones, transform, shape) -> np.ndarray:
    """Label image for the zones on this grid, cached: every scene of a run in
    one CRS and tile lands on the same grid, so the rasterisation is paid once."""
    key = (zones.epsg, id(zones), tuple(transform)[:6], tuple(shape))
    lab = _label_cache.get(key)
    if lab is None:
        if len(_label_cache) > 8:
            _label_cache.clear()
        lab = labels_for(zones, transform, shape)
        _label_cache[key] = lab
    return lab


def item_fields(item):
    """(id, baseline, epsg, tile_bounds) from a STAC item dict or providers.Scene.

    A Scene carries no tile extent unless props["tile_bounds"] is set (the
    provider would have to keep the SCL asset's proj:bbox)."""
    if isinstance(item, dict):
        p = item.get("properties", {})
        epsg = p.get("proj:epsg")
        if epsg is None and str(p.get("proj:code", "")).upper().startswith("EPSG:"):
            epsg = int(p["proj:code"].split(":")[1])
        tb = (item.get("assets", {}).get("SCL", {}) or {}).get("proj:bbox")
        return item["id"], p.get("s2:processing_baseline", "00.00"), epsg, tuple(tb) if tb else None
    tb = item.props.get("tile_bounds")
    return item.id, item.props.get("baseline", "00.00"), item.epsg, tuple(tb) if tb else None


def fetch_scene_cells(item, area_epsg: int, cells: list, res_m: float = 40.0,
                      index="NDVI", zones: Zones | None = None, timeout: float = 120.0,
                      retries: int = 4, base: str = PC_DATA, keep_raw: bool = False,
                      true_grid: bool = False) -> SceneCells:
    """Per-cell (mean, clear_frac, n_px) for one S2 scene from one server request.

    `cells` are polygons in `area_epsg` (the area's UTM, as `DonorGrid.cells`);
    the request is made in the scene's own CRS, as the local read is. `index` is
    one name or up to two names from INDEX_BANDS. Pass `zones` (built once per
    CRS with `Zones.build(cells, area_epsg, scene_epsg)`) to skip rebuilding it.

    `true_grid=True` labels pixels on the grid the server actually sampled
    (window / shape, e.g. 39.97 m) instead of the local convention (exact res_m
    from the window corner); see the bench for what that changes.
    """
    indices = (index,) if isinstance(index, str) else tuple(index)
    item_id, baseline, epsg, tile_bounds = item_fields(item)
    if epsg is None:
        raise RemoteError("scene has no proj:epsg; cannot request its native grid")
    if zones is None:
        zones = Zones.build(cells, area_epsg, epsg)
    t0, c0 = time.perf_counter(), time.process_time()
    bounds = clip_bounds(zones.bounds, tile_bounds)
    if bounds is None:
        raise RemoteError("window is outside the scene's tile")
    w, h = output_grid(bounds, res_m, 10.0)
    expr = build_expression(baseline, indices)
    content, attempts, statuses = get_bytes(bbox_url(bounds, w, h, "png", base),
                                            request_params(item_id, epsg, expr, 2 * len(indices)),
                                            timeout=timeout, retries=retries)
    t_net = time.perf_counter() - t0
    stack = decode_png(content)
    if stack.shape != (2 * len(indices), h, w):
        raise RemoteError(f"expected {(2 * len(indices), h, w)}, got {stack.shape}")
    vals, clear = [], None
    for k in range(len(indices)):
        v, c = decode_codes(stack[2 * k], stack[2 * k + 1])
        vals.append(v)
        clear = c if clear is None else clear
    if true_grid:
        tr = Affine((bounds[2] - bounds[0]) / w, 0.0, bounds[0], 0.0, -(bounds[3] - bounds[1]) / h, bounds[3])
    else:
        tr = label_transform(bounds, res_m)
    labels = cell_labels(zones, tr, (h, w))
    means, clear_frac, n_px = reduce_cells(vals, clear, labels, len(zones.polygons))
    values = {}
    for k, name in enumerate(indices):
        m = means[k]
        m[clear_frac < CLEAR_MIN] = np.nan
        values[name] = m
    stats = {"wall_s": time.perf_counter() - t0, "net_s": t_net,
             "cpu_s": time.process_time() - c0, "bytes": len(content),
             "attempts": attempts, "statuses": statuses, "shape": (h, w)}
    raw = {"values": vals, "clear": clear, "bounds": bounds, "shape": (h, w)} if keep_raw else None
    return SceneCells(item_id, values, clear_frac, n_px, stats, raw)


def process_scene_remote(scene, zones: Zones, sign=None, res: float = 40.0,
                         require_zone0: bool = False, indices=("NDVI",)):
    """Drop-in for `s2.process_scene` on a donor-only group (not wired in).

    Same return shape: (S2Observation, None) or (None, Receipt). Indices not
    requested come back as all-NaN columns, so `fetch._to_series` still finds
    every key; donor groups only ever use the run's primary index (run.py
    `_analyse_all`) and NDVI (`fetch._despike_donors`), so pass
    indices=("NDVI", primary) when primary != "NDVI" to keep both. `sign` is
    unused: the data API signs its own reads. Raises RemoteError on failure so
    a caller can fall back to the local read.
    """
    from .s2 import INDICES, Receipt, S2Observation
    if require_zone0:
        raise ValueError("remote reads are for donor-only groups (require_zone0=False)")
    sc = fetch_scene_cells(scene, zones.epsg, zones.polygons, res, index=tuple(indices), zones=zones)
    if not np.any(sc.clear_frac >= CLEAR_MIN):
        return None, Receipt("S2", scene.date, scene.id, "cloud", "No donor cell in this group is clear.")
    n = len(zones.polygons)
    values = {k: sc.values.get(k, np.full(n, np.nan)) for k in INDICES}
    props = dict(scene.props)
    props["read"] = "pc-data-api"
    return S2Observation(scene.id, scene.date, scene.minute_key, values, sc.clear_frac, sc.n_px,
                         props=props), None
