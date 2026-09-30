"""Sentinel-2 L2A: cloud masking, baseline harmonisation, index means, receipts.

Order of operations per scene:
  1. read SCL (20 m) for the window; compute the clear fraction of every zone
  2. if the treated area is not clear enough -> receipt, stop (no band reads)
  3. read B03/B04/B08 (10 m) and B12 (20 m, resampled to 10 m), remove the
     Baseline-04 offset by processing baseline, compute NDVI / NDWI / NBR per
     pixel, and take the per-zone mean over clear pixels only
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import rasterio
from rasterio.windows import Window

from .extract import (GDAL_ENV, Zones, cached_labels, read_geometry, read_window,
                      upsample_factor, window_geometry, zone_counts, zone_means)
from .providers import Scene

# SCL classes kept as "clear ground": vegetation, bare soil, water. Everything
# else (nodata, saturated, dark, cloud shadow, unclassified, cloud, cirrus, snow)
# is treated as unusable. Conservative on purpose: a missed thin cloud pulls NDVI
# down and looks exactly like clearing.
SCL_CLEAR = (4, 5, 6)
SCL_NAMES = {0: "no data", 1: "saturated", 2: "dark", 3: "cloud shadow", 4: "vegetation",
             5: "bare", 6: "water", 7: "unclassified", 8: "cloud (medium)",
             9: "cloud (high)", 10: "cirrus", 11: "snow"}
CLEAR_MIN = 0.80          # zone must be at least this clear to yield an observation
INDICES = ("NDVI", "NDWI", "NBR")
OFFSET_BASELINE = "04.00"
DN_OFFSET = 1000.0


def needs_offset(baseline: str) -> bool:
    try:
        return float(baseline) >= float(OFFSET_BASELINE)
    except (TypeError, ValueError):
        return False


def reflectance(dn: np.ndarray, baseline: str) -> np.ndarray:
    # In place on one float32 buffer: the same float32 operations in the same
    # order as clip(x - 1000, 0, None) / 10000, without three temporaries.
    x = dn.astype("float32")
    if needs_offset(baseline):
        np.subtract(x, DN_OFFSET, out=x)
        np.maximum(x, 0.0, out=x)
    np.divide(x, 10000.0, out=x)
    return x


def _nd(a, b):
    den = a + b
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, (a - b) / den, np.nan)


def indices_from_bands(b03, b04, b08, b12) -> dict[str, np.ndarray]:
    return {"NDVI": _nd(b08, b04), "NDWI": _nd(b03, b08), "NBR": _nd(b08, b12)}


@dataclass
class S2Observation:
    scene_id: str
    date: str
    minute_key: str
    values: dict[str, np.ndarray]      # index -> (n_zones,) mean, NaN where not clear
    clear_frac: np.ndarray             # (n_zones,)
    n_pixels: np.ndarray               # (n_zones,) total pixels in the zone
    props: dict = field(default_factory=dict)


@dataclass
class Receipt:
    sensor: str
    date: str
    scene_id: str
    reason: str          # short machine-ish label
    detail: str          # human sentence
    value: float | None = None


def scl_breakdown(scl: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    m = labels == 1
    if not m.any():
        return {}
    vals, counts = np.unique(scl[m], return_counts=True)
    tot = counts.sum()
    return {SCL_NAMES.get(int(v), str(v)): float(c / tot) for v, c in zip(vals, counts)}


def _cloud_receipt(scene: Scene, scl: np.ndarray, labels: np.ndarray, frac0) -> Receipt:
    bd = scl_breakdown(scl, labels)
    worst = max(((k, v) for k, v in bd.items() if k not in ("vegetation", "bare", "water")),
                key=lambda kv: kv[1], default=("cloud", 1 - frac0))
    return Receipt("S2", scene.date, scene.id, "cloud",
                   f"Only {frac0:.0%} of the area is clear "
                   f"({worst[0]} over {worst[1]:.0%}); dropped.",
                   value=float(frac0))


def _zone0_gate(ds, geom, labels: np.ndarray, bbox0, scene: Scene) -> Receipt | None:
    """Decide the treated-area gate from the SCL pixels under zone 0 alone.

    Most scenes fail the gate (cloud), and the gate depends only on zone 0, yet
    the whole donor window (~6 Mpx at 10 m) used to be read, upsampled and
    reduced to find that out. Here only the SCL blocks under zone 0's bounding
    box are read, at native resolution, and replicated k x k in numpy -- the
    same pixel mapping the full nearest-neighbour read uses for an integer
    factor k -- and counted against the same cached label image. The counts are
    the same integers as the full path's `n_clear[0]` / `n_total[0]`, so the
    receipt is identical. Returns the receipt when the scene is dropped, None
    when the full read must go ahead (gate passed, or a non-integer factor).
    """
    if bbox0 is None:                                   # n_total[0] == 0
        return Receipt("S2", scene.date, scene.id, "outside",
                       "Scene footprint does not cover the area.")
    win, _, out_shape = geom
    k = 1 if out_shape is None else upsample_factor(win, out_shape)
    if k is None:
        return None
    r0, r1, c0, c1 = bbox0
    sr0, sc0, sr1, sc1 = r0 // k, c0 // k, -(-r1 // k), -(-c1 // k)
    sub = ds.read(1, window=Window(win.col_off + sc0, win.row_off + sr0, sc1 - sc0, sr1 - sr0))
    if k > 1:
        sub = np.repeat(np.repeat(sub, k, axis=0), k, axis=1)
    dr, dc = r0 - sr0 * k, c0 - sc0 * k
    scl0 = sub[dr:dr + (r1 - r0), dc:dc + (c1 - c0)]
    lab0 = labels[r0:r1, c0:c1]
    in0 = lab0 == 1
    n_total0 = np.int64(np.count_nonzero(in0))
    n_clear0 = np.int64(np.count_nonzero(in0 & np.isin(scl0, SCL_CLEAR)))
    frac0 = (np.asarray([n_clear0]) / np.maximum(np.asarray([n_total0]), 1))[0]
    if frac0 < CLEAR_MIN:
        return _cloud_receipt(scene, scl0, lab0, frac0)
    return None


def process_scene(scene: Scene, zones: Zones, sign, res: float = 10.0,
                  require_zone0: bool = True) -> tuple[S2Observation | None, Receipt | None]:
    """Extract one S2 scene for all zones. zone 0 is the treated area unless
    `require_zone0` is False (a donor-only group), in which case the scene is
    kept whenever any zone is usable. `res` is the read resolution in metres;
    donor-only groups are read coarser, from the COG overviews.

    Bands are read, reduced and released one at a time. Holding B03/B04/B08/B12
    and three whole index rasters at once was the single largest allocation in
    a run; only B08 (needed by all three indices) is kept across steps.
    """
    n = len(zones.polygons)
    with rasterio.Env(**GDAL_ENV), rasterio.open(sign(scene.hrefs["SCL"])) as ds:
        geom = window_geometry(ds, zones, res)
        if geom is None:
            return None, Receipt("S2", scene.date, scene.id, "outside",
                                 "Scene footprint does not cover the area.")
        win, tr, out_shape = geom
        labels, bbox0 = cached_labels(zones, tr, out_shape or (win.height, win.width))
        if require_zone0:
            dropped = _zone0_gate(ds, geom, labels, bbox0, scene)
            if dropped is not None:
                return None, dropped
        scl = read_geometry(ds, geom)
    clear = np.isin(scl, SCL_CLEAR)
    n_clear, n_total = zone_counts(labels, n, clear)
    with np.errstate(invalid="ignore", divide="ignore"):
        clear_frac = np.where(n_total > 0, n_clear / np.maximum(n_total, 1), 0.0)
    if not require_zone0:
        if not np.any(clear_frac >= CLEAR_MIN):
            return None, Receipt("S2", scene.date, scene.id, "cloud", "No donor cell in this group is clear.")
    elif n_total[0] == 0:
        return None, Receipt("S2", scene.date, scene.id, "outside",
                             "Scene footprint does not cover the area.")
    elif clear_frac[0] < CLEAR_MIN:
        return None, _cloud_receipt(scene, scl, labels, clear_frac[0])
    del scl
    baseline = scene.props.get("baseline", "00.00")

    def band(name):
        rr = read_window(sign(scene.hrefs[name]), zones, out_res=res)
        if rr is None or rr[0].shape != labels.shape:
            return None
        return reflectance(rr[0], baseline)

    b08 = band("B08")
    if b08 is None:
        return None, Receipt("S2", scene.date, scene.id, "read-error",
                             "Band B08 window did not match the mask window.")
    values = {}
    for name, partner, order in (("NDVI", "B04", "b08_first"), ("NDWI", "B03", "partner_first"),
                                 ("NBR", "B12", "b08_first")):
        other = band(partner)
        if other is None:
            return None, Receipt("S2", scene.date, scene.id, "read-error",
                                 f"Band {partner} window did not match the mask window.")
        arr = _nd(b08, other) if order == "b08_first" else _nd(other, b08)
        del other
        v = clear & np.isfinite(arr)
        np.nan_to_num(arr, copy=False)
        m, _, _ = zone_means(arr, v, labels, n)
        del arr, v
        m[clear_frac < CLEAR_MIN] = np.nan
        values[name] = m
    del b08, clear, labels
    return S2Observation(scene.id, scene.date, scene.minute_key, values, clear_frac, n_total,
                         props=dict(scene.props)), None


def merge_duplicates(obs):
    """Two MGRS tiles (or two S1 frames) can carry the same acquisition, each
    covering some of the donor cells. Merge them zone by zone (mean of the
    copies that have a value) so no cell loses coverage to a tile boundary."""
    groups: dict[str, list] = {}
    for o in sorted(obs, key=lambda o: o.minute_key):
        groups.setdefault(o.minute_key, []).append(o)
    out, receipts = [], []
    for k, g in groups.items():
        if len(g) == 1:
            out.append(g[0])
            continue
        g.sort(key=lambda o: -float(_frac(o)[0]))
        base = g[0]
        with np.errstate(invalid="ignore"):
            for name in base.values:
                base.values[name] = np.nanmean(np.vstack([o.values[name] for o in g]), axis=0)
            _set_frac(base, np.max(np.vstack([_frac(o) for o in g]), axis=0))
        base.props["merged_with"] = [o.scene_id for o in g[1:]]
        out.append(base)
        for o in g[1:]:
            receipts.append(Receipt(base.__class__.__name__[:2], o.date, o.scene_id, "duplicate",
                                    f"Same acquisition as {base.scene_id} (tile overlap); the two copies were merged."))
    return out, receipts


def _frac(o):
    return o.clear_frac if hasattr(o, "clear_frac") else o.valid_frac


def _set_frac(o, v):
    if hasattr(o, "clear_frac"):
        o.clear_frac = v
    else:
        o.valid_frac = v


dedupe_by_minute = merge_duplicates


def despike(dates: np.ndarray, ndvi: np.ndarray, window_days: int = 40,
            min_drop: float = 0.12, k_mad: float = 3.0) -> np.ndarray:
    """Flag residual cloud/haze the SCL missed: an NDVI value far below the
    median of its temporal neighbours. Returns a boolean 'suspect' array.

    Cloud contamination only ever lowers NDVI, so the test is one-sided; a real
    clearing also lowers NDVI but stays low, so its neighbours drop with it.
    """
    n = len(ndvi)
    suspect = np.zeros(n, dtype=bool)
    d = dates.astype("datetime64[D]").astype(int)
    for i in range(n):
        if not np.isfinite(ndvi[i]):
            continue
        near = (np.abs(d - d[i]) <= window_days) & (np.arange(n) != i) & np.isfinite(ndvi)
        if near.sum() < 2:
            continue
        nb = ndvi[near]
        med = np.median(nb)
        mad = np.median(np.abs(nb - med)) * 1.4826
        thr = max(min_drop, k_mad * mad)
        if med - ndvi[i] > thr:
            suspect[i] = True
    return suspect
