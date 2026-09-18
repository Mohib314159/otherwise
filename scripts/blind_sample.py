"""Draw a blind, seeded validation sample of real labelled events and null areas.

Nothing here is hand-picked. Given a seed, the script reads random windows of
public ground-truth rasters/vectors over the network and keeps whatever passes
fixed, documented criteria. The same seed reproduces the same sample.json bit
for bit, because the ground truth (Hansen GFC-2023 v1.11, MTBS perimeters)
is a fixed release and every random choice comes from a seeded generator.

Sources
-------
1. Hansen Global Forest Change 2023 v1.11 (30 m, lossyear + treecover2000),
   read as windows through /vsicurl/ from Google Cloud Storage. Events are
   connected components of one calendar year's loss; nulls are fully
   forested boxes with no loss 2001-2023 in the box or a 300 m buffer.
2. MTBS burned-area perimeters (USA, optional, --mtbs path/to/zip): events are
   boxes inside a fire perimeter with the ignition date; nulls are boxes of
   the same sizes in tree-covered land at least 5 km from every perimeter.

Usage
-----
    python -m scripts.blind_sample --seed 20260918 --n-events 60 --n-null 60 \
        --out showcase/blind/sample.json [--mtbs path/to/mtbs_perimeter_data.zip]

The pure functions `pick_component` and `pick_null_box` work on plain numpy
arrays so they are testable without the network (tests/test_blind_sample.py).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import subprocess
import sys
import time
import zipfile

import numpy as np
from scipy import ndimage

HANSEN_VERSION = "GFC-2023-v1.11"
HANSEN_URL = ("https://storage.googleapis.com/earthenginepartners-hansen/"
              f"{HANSEN_VERSION}/Hansen_{HANSEN_VERSION}_{{layer}}_{{tile}}.tif")
PIX_DEG = 0.00025                    # Hansen pixel, degrees
TILE_PX = 40000                      # 10 degrees per tile
M_PER_DEG = 111_320.0                # metres per degree of latitude (and of longitude at the equator)
PIX_M_LAT = PIX_DEG * M_PER_DEG      # 27.83 m north-south

# Tile names are the top-left corner (Hansen convention): 00N_060W covers 0..10S, 60W..50W.
# Climate class is a fixed per-tile mapping by the dominant Koppen group of the land in the tile.
HANSEN_TILES = ["00N_060W", "00N_020E", "00N_110E", "20N_100W", "50N_010E",
                "50N_130W", "60N_100E", "30S_060W", "30S_150E"]
TILE_CLIMATE = {
    "00N_060W": "tropical",     # 0-10S, 50-60W: eastern Amazon (Para, Amazonas, Mato Grosso north)
    "00N_020E": "tropical",     # 0-10S, 20-30E: Congo basin south (DRC)
    "00N_110E": "tropical",     # 0-10S, 110-120E: Borneo south / Java
    "20N_100W": "tropical",     # 10-20N, 90-100W: southern Mexico, Guatemala, Honduras
    "50N_010E": "temperate",    # 40-50N, 10-20E: central Europe and the Balkans
    "50N_130W": "temperate",    # 40-50N, 120-130W: Pacific Northwest (Oregon, Washington, BC)
    "60N_100E": "boreal",       # 50-60N, 100-110E: Siberia around Lake Baikal
    "30S_060W": "temperate",    # 30-40S, 50-60W: Uruguay, Rio Grande do Sul, Argentine pampas
    "30S_150E": "temperate",    # 30-40S, 150-160E: New South Wales coast
}
EVENT_YEARS = list(range(2018, 2023))    # 2018..2022; 2023 is added only when 12 months of post data exist
LOSSYEAR_FIRST = 2001                    # lossyear 1 = 2001

GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4",
                GDAL_HTTP_RETRY_DELAY="1", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                VSI_CACHE="TRUE", VSI_CACHE_SIZE="50000000")

# Event polygon criteria (Hansen)
WINDOW_PX = 200                 # random window side, pixels (6 km at the equator)
MIN_COMP_HA = 20.0
MAX_COMP_HA = 400.0
MAX_BOX_HA = 400.0
MIN_LOSS_FRAC = 0.60
TC_EVENT = 30                   # treecover2000 >= 30% for a loss pixel to count
TC_NULL = 50                    # treecover2000 >= 50% everywhere in a null box
NULL_BUFFER_M = 300.0
POST_MONTHS_CLEARING = 18

# MTBS criteria
MTBS_MIN_AC, MTBS_MAX_AC = 700, 12000
MTBS_DATE_LO, MTBS_DATE_HI = dt.date(2018, 6, 1), dt.date(2023, 6, 1)
MTBS_SHRINK_M = 200.0
MTBS_MIN_INSIDE = 0.80
MTBS_NULL_MIN_DIST_M = 5000.0
MTBS_NULL_MAX_DIST_M = 120_000.0
POST_MONTHS_BURN = 6


# ----------------------------------------------------------------------------
# pure functions (no network) -- tested
# ----------------------------------------------------------------------------

def pixel_size_m(lat: float) -> tuple[float, float]:
    """(north-south, east-west) size of a Hansen pixel in metres at latitude lat."""
    return PIX_M_LAT, PIX_M_LAT * math.cos(math.radians(lat))


def pixel_ha(lat: float) -> float:
    dy, dx = pixel_size_m(lat)
    return dy * dx / 10_000.0


def pick_component(lossyear: np.ndarray, treecover: np.ndarray, year: int, rng: np.random.Generator,
                   pix_ha: float, min_ha: float = MIN_COMP_HA, max_ha: float = MAX_COMP_HA,
                   max_box_ha: float = MAX_BOX_HA, min_frac: float = MIN_LOSS_FRAC,
                   tc_min: int = TC_EVENT) -> dict | None:
    """Pick one loss component of `year` in a window and return its polygon box.

    lossyear: uint8 window (0 none, 1..23 = 2001..2023); treecover: percent.
    Returns None when the window has no usable component (caller retries).
    The box is the component's bounding box shrunk by one pixel per side,
    cropped symmetrically around the component centroid to `max_box_ha`, and
    accepted only when at least `min_frac` of its pixels belong to the component.
    Components touching the window edge are skipped (their area is unknown).
    """
    code = year - LOSSYEAR_FIRST + 1
    mask = (lossyear == code) & (treecover >= tc_min)
    if not mask.any():
        return None
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    sizes = np.bincount(lab.ravel(), minlength=n + 1)
    H, W = mask.shape
    edge_ids = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
    ids = [i for i in range(1, n + 1)
           if min_ha <= sizes[i] * pix_ha <= max_ha and i not in edge_ids]
    if not ids:
        return None
    cid = int(ids[int(rng.integers(len(ids)))])
    comp = lab == cid
    sl = ndimage.find_objects(lab)[cid - 1]
    r0, r1 = sl[0].start, sl[0].stop
    c0, c1 = sl[1].start, sl[1].stop
    # shrink by one pixel on each side (keep at least 1x1)
    if r1 - r0 > 2:
        r0, r1 = r0 + 1, r1 - 1
    if c1 - c0 > 2:
        c0, c1 = c0 + 1, c1 - 1
    h, w = r1 - r0, c1 - c0
    box_ha = h * w * pix_ha
    cy, cx = ndimage.center_of_mass(comp)
    if box_ha > max_box_ha:
        scale = math.sqrt(max_box_ha / box_ha)
        h2, w2 = max(1, int(math.floor(h * scale))), max(1, int(math.floor(w * scale)))
        nr0 = int(round(cy - h2 / 2.0))
        nc0 = int(round(cx - w2 / 2.0))
        nr0 = min(max(nr0, r0), r1 - h2)
        nc0 = min(max(nc0, c0), c1 - w2)
        r0, r1, c0, c1 = nr0, nr0 + h2, nc0, nc0 + w2
        h, w = h2, w2
        box_ha = h * w * pix_ha
    frac = float(comp[r0:r1, c0:c1].sum()) / float(h * w)
    if frac < min_frac:
        return None
    return {"row0": int(r0), "row1": int(r1), "col0": int(c0), "col1": int(c1),
            "component_px": int(sizes[cid]), "component_ha": round(float(sizes[cid] * pix_ha), 2),
            "box_ha": round(float(box_ha), 2), "loss_fraction": round(frac, 4),
            "n_candidates": len(ids), "centroid_rc": [round(float(cy), 1), round(float(cx), 1)]}


def pick_null_box(lossyear: np.ndarray, treecover: np.ndarray, h: int, w: int, rng: np.random.Generator,
                  buf_rows: int, buf_cols: int, tc_min: int = TC_NULL, tries: int = 40) -> dict | None:
    """Find an h x w box in the window with treecover >= tc_min everywhere and
    lossyear == 0 everywhere in the box and in its (buf_rows, buf_cols) buffer.
    Positions are drawn uniformly; returns None after `tries` failures."""
    H, W = lossyear.shape
    if h + 2 * buf_rows > H or w + 2 * buf_cols > W:
        return None
    for _ in range(tries):
        r0 = int(rng.integers(buf_rows, H - h - buf_rows + 1))
        c0 = int(rng.integers(buf_cols, W - w - buf_cols + 1))
        if (treecover[r0:r0 + h, c0:c0 + w] < tc_min).any():
            continue
        if lossyear[r0 - buf_rows:r0 + h + buf_rows, c0 - buf_cols:c0 + w + buf_cols].any():
            continue
        return {"row0": r0, "row1": r0 + h, "col0": c0, "col1": c0 + w,
                "min_treecover": int(treecover[r0:r0 + h, c0:c0 + w].min())}
    return None


def size_bucket(ha: float) -> str:
    return "<50 ha" if ha < 50 else ("50-150 ha" if ha <= 150 else ">150 ha")


def substream(seed: int, tag: int) -> np.random.Generator:
    """Independent, reproducible generators per sampling stage."""
    return np.random.default_rng([int(seed), int(tag)])


# ----------------------------------------------------------------------------
# Hansen tile access
# ----------------------------------------------------------------------------

class HansenTiles:
    """Lazily opened /vsicurl/ datasets, one per (tile, layer). Whole tiles are never downloaded."""

    def __init__(self, tiles: list[str]):
        import rasterio
        self._rio = rasterio
        self.tiles = tiles
        self._ds: dict[tuple[str, str], object] = {}
        self.failed: set[str] = set()
        self.reads = 0
        self.read_seconds = 0.0

    def open(self, tile: str, layer: str):
        key = (tile, layer)
        if key not in self._ds:
            with self._rio.Env(**GDAL_ENV):
                self._ds[key] = self._rio.open("/vsicurl/" + HANSEN_URL.format(layer=layer, tile=tile))
        return self._ds[key]

    def check(self) -> list[str]:
        """Return the tiles that open; record the ones that fail."""
        ok = []
        for t in self.tiles:
            try:
                self.open(t, "lossyear")
                self.open(t, "treecover2000")
                ok.append(t)
            except Exception as e:                       # noqa: BLE001
                print(f"  tile {t} failed to open, skipped: {e}", file=sys.stderr)
                self.failed.add(t)
        return ok

    def read(self, tile: str, layer: str, row: int, col: int, h: int, w: int) -> np.ndarray:
        from rasterio.windows import Window
        ds = self.open(tile, layer)
        t0 = time.time()
        with self._rio.Env(**GDAL_ENV):
            arr = ds.read(1, window=Window(col, row, w, h))
        self.reads += 1
        self.read_seconds += time.time() - t0
        return arr

    def bounds(self, tile: str):
        return self.open(tile, "lossyear").bounds

    def box_geojson(self, tile: str, row0: int, row1: int, col0: int, col1: int) -> dict:
        b = self.bounds(tile)
        lon0, lon1 = b.left + col0 * PIX_DEG, b.left + col1 * PIX_DEG
        lat0, lat1 = b.top - row1 * PIX_DEG, b.top - row0 * PIX_DEG
        return {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]}


def tile_for(lon: float, lat: float) -> str:
    """Hansen tile name (top-left corner) containing lon/lat."""
    top = int(math.ceil(lat / 10.0)) * 10
    left = int(math.floor(lon / 10.0)) * 10
    ns = f"{abs(top):02d}{'N' if top >= 0 else 'S'}"
    ew = f"{abs(left):03d}{'E' if left >= 0 else 'W'}"
    return f"{ns}_{ew}"


def window_lat(tile_bounds, row: int, h: int) -> float:
    return tile_bounds.top - (row + h / 2.0) * PIX_DEG


# ----------------------------------------------------------------------------
# Hansen sampling
# ----------------------------------------------------------------------------

def allowed_years(today: dt.date) -> list[int]:
    years = list(EVENT_YEARS)
    if today >= dt.date(2024, 1, 1):
        years.append(2023)
    return years


def draw_hansen_events(tiles: HansenTiles, ok_tiles: list[str], n: int, rng: np.random.Generator,
                       years: list[int], max_attempts: int, log) -> tuple[list[dict], dict]:
    items, attempts, reasons = [], 0, {"no_loss": 0, "no_component": 0, "rejected_frac": 0, "read_error": 0}
    while len(items) < n and attempts < max_attempts:
        attempts += 1
        tile = ok_tiles[int(rng.integers(len(ok_tiles)))]
        row = int(rng.integers(0, TILE_PX - WINDOW_PX + 1))
        col = int(rng.integers(0, TILE_PX - WINDOW_PX + 1))
        year = int(years[int(rng.integers(len(years)))])
        # the component pick consumes one more draw only when candidates exist (rng passed through)
        try:
            ly = tiles.read(tile, "lossyear", row, col, WINDOW_PX, WINDOW_PX)
            lat = window_lat(tiles.bounds(tile), row, WINDOW_PX)
            ph = pixel_ha(lat)
            code = year - LOSSYEAR_FIRST + 1
            if (ly == code).sum() * ph < MIN_COMP_HA:
                reasons["no_loss"] += 1
                continue
            tc = tiles.read(tile, "treecover2000", row, col, WINDOW_PX, WINDOW_PX)
        except Exception as e:                            # noqa: BLE001
            reasons["read_error"] += 1
            log(f"  read error {tile} r{row} c{col}: {e}")
            continue
        pick = pick_component(ly, tc, year, rng, ph)
        if pick is None:
            reasons["no_component"] += 1
            continue
        r0, r1, c0, c1 = row + pick["row0"], row + pick["row1"], col + pick["col0"], col + pick["col1"]
        geo = tiles.box_geojson(tile, r0, r1, c0, c1)
        clat = window_lat(tiles.bounds(tile), r0, r1 - r0)
        clon = tiles.bounds(tile).left + (c0 + c1) / 2.0 * PIX_DEG
        dy, dx = pixel_size_m(clat)
        k = len(items) + 1
        items.append({
            "id": f"ev-hansen-{k:03d}", "kind": "event", "source": "hansen",
            "change_type": "clearing", "expected": "REAL",
            "event_date": f"{year}-01-01", "event_year": year, "date_precision": "year",
            "post_months": POST_MONTHS_CLEARING, "climate": TILE_CLIMATE[tile],
            "box_ha": pick["box_ha"], "size_bucket": size_bucket(pick["box_ha"]),
            "box_m": [round((r1 - r0) * dy), round((c1 - c0) * dx)],
            "lon": round(clon, 5), "lat": round(clat, 5), "geojson": geo,
            "label": f"Blind sample {k:03d}: Hansen forest loss {year}, tile {tile}",
            "provenance": {"dataset": f"Hansen {HANSEN_VERSION} lossyear/treecover2000", "tile": tile,
                           "window_rc": [row, col], "window_px": WINDOW_PX, "attempt": attempts,
                           "box_rc": [r0, r1, c0, c1], "box_px": [r1 - r0, c1 - c0],
                           "component_px": pick["component_px"], "component_ha": pick["component_ha"],
                           "loss_fraction": pick["loss_fraction"], "n_candidates": pick["n_candidates"],
                           "treecover_min": TC_EVENT, "window_lat": round(lat, 4)},
        })
        log(f"  event {k}/{n}: {tile} {year} box {pick['box_ha']} ha frac {pick['loss_fraction']} "
            f"(attempt {attempts}, {tiles.reads} reads)")
    return items, {"attempts": attempts, **reasons}


def draw_hansen_nulls(tiles: HansenTiles, ok_tiles: list[str], n: int, rng: np.random.Generator,
                      events: list[dict], max_attempts: int, log) -> tuple[list[dict], dict]:
    items, attempts, reasons = [], 0, {"no_box": 0, "read_error": 0}
    sizes_m = [e["box_m"] for e in events] or [[600, 600]]
    years = [e["event_year"] for e in events] or EVENT_YEARS
    while len(items) < n and attempts < max_attempts:
        attempts += 1
        tile = ok_tiles[int(rng.integers(len(ok_tiles)))]
        row = int(rng.integers(0, TILE_PX - WINDOW_PX + 1))
        col = int(rng.integers(0, TILE_PX - WINDOW_PX + 1))
        year = int(years[int(rng.integers(len(years)))])
        hm, wm = sizes_m[int(rng.integers(len(sizes_m)))]
        lat = window_lat(tiles.bounds(tile), row, WINDOW_PX)
        dy, dx = pixel_size_m(lat)
        h, w = max(1, int(round(hm / dy))), max(1, int(round(wm / dx)))
        br, bc = int(math.ceil(NULL_BUFFER_M / dy)), int(math.ceil(NULL_BUFFER_M / dx))
        try:
            tc = tiles.read(tile, "treecover2000", row, col, WINDOW_PX, WINDOW_PX)
            if (tc >= TC_NULL).sum() < h * w:
                reasons["no_box"] += 1
                continue
            ly = tiles.read(tile, "lossyear", row, col, WINDOW_PX, WINDOW_PX)
        except Exception as e:                            # noqa: BLE001
            reasons["read_error"] += 1
            log(f"  read error {tile} r{row} c{col}: {e}")
            continue
        pick = pick_null_box(ly, tc, h, w, rng, br, bc)
        if pick is None:
            reasons["no_box"] += 1
            continue
        r0, r1, c0, c1 = row + pick["row0"], row + pick["row1"], col + pick["col0"], col + pick["col1"]
        geo = tiles.box_geojson(tile, r0, r1, c0, c1)
        clat = window_lat(tiles.bounds(tile), r0, r1 - r0)
        clon = tiles.bounds(tile).left + (c0 + c1) / 2.0 * PIX_DEG
        box_ha = round(h * w * pixel_ha(clat), 2)
        k = len(items) + 1
        items.append({
            "id": f"nl-hansen-{k:03d}", "kind": "null", "source": "hansen",
            "change_type": "clearing", "expected": "NOT_REAL",
            "event_date": f"{year}-01-01", "event_year": year, "date_precision": "year",
            "post_months": POST_MONTHS_CLEARING, "climate": TILE_CLIMATE[tile],
            "box_ha": box_ha, "size_bucket": size_bucket(box_ha), "box_m": [round(h * dy), round(w * dx)],
            "lon": round(clon, 5), "lat": round(clat, 5), "geojson": geo,
            "label": f"Blind sample null {k:03d}: intact forest, no Hansen loss 2001-2023, tile {tile}",
            "provenance": {"dataset": f"Hansen {HANSEN_VERSION} lossyear/treecover2000", "tile": tile,
                           "window_rc": [row, col], "window_px": WINDOW_PX, "attempt": attempts,
                           "box_rc": [r0, r1, c0, c1], "box_px": [h, w], "buffer_px": [br, bc],
                           "size_from_event_box_m": [hm, wm], "treecover_min_required": TC_NULL,
                           "treecover_min_found": pick["min_treecover"], "window_lat": round(lat, 4)},
        })
        log(f"  null {k}/{n}: {tile} {year} box {box_ha} ha (attempt {attempts}, {tiles.reads} reads)")
    return items, {"attempts": attempts, **reasons}


# ----------------------------------------------------------------------------
# MTBS (optional)
# ----------------------------------------------------------------------------

def mtbs_climate(lon: float, lat: float) -> str:
    """Fixed rule: the interior West (between 118W and 100W) is 'dry'
    (Great Basin, Rockies, Southwest); everything else in the USA is 'temperate'."""
    return "dry" if -118.0 <= lon <= -100.0 else "temperate"


def mtbs_reader(path: str, log=print):
    """pyshp Reader for the MTBS shapefile. `path` is the zip (extracted once,
    beside it) or the .shp itself."""
    import shapefile
    if path.lower().endswith(".zip"):
        d = path[:-4] + "_extracted"
        z = zipfile.ZipFile(path)
        shp = next(n for n in z.namelist() if n.lower().endswith(".shp"))
        if not os.path.exists(os.path.join(d, shp)):
            log(f"  extracting {path} to {d}")
            z.extractall(d)
        path = os.path.join(d, shp)
    return shapefile.Reader(path)


def load_mtbs(path: str, log) -> list[dict]:
    """Read eligible MTBS wildfire perimeters with pyshp. Returns dicts with
    event id, name, state, ignition date, acres and shapely geometry (WGS84)."""
    from shapely.geometry import shape
    rd = mtbs_reader(path, log)
    fields = [f[0] for f in rd.fields[1:]]
    log(f"  MTBS records: {len(rd)}; fields: {fields}")
    fi = {f.lower(): i for i, f in enumerate(fields)}      # field names are lower-case in the 2024+ release
    out = []
    for i, rec in enumerate(rd.iterRecords()):
        try:
            ig = rec[fi["ig_date"]]
            if isinstance(ig, str):
                ig = dt.date.fromisoformat(ig[:10])
            elif isinstance(ig, dt.datetime):
                ig = ig.date()
            ac = float(rec[fi["burnbndac"]])
        except Exception:                                 # noqa: BLE001
            continue
        if not (MTBS_DATE_LO <= ig <= MTBS_DATE_HI and MTBS_MIN_AC <= ac <= MTBS_MAX_AC):
            continue
        if str(rec[fi["incid_type"]]).strip().lower() != "wildfire":
            continue
        s = rd.shape(i)
        out.append({"index": i, "event_id": str(rec[fi["event_id"]]), "name": str(rec[fi["incid_name"]]),
                    "state": str(rec[fi["event_id"]])[:2], "ig_date": ig.isoformat(), "acres": ac,
                    "geom": shape(s.__geo_interface__)})
    out.sort(key=lambda d: d["index"])
    return out


def mtbs_perimeters_near(path: str, events: list[dict], radius_m: float):
    """Perimeters (all years, all types) whose bbox falls within radius_m of any sampled
    event centre, for the 5 km exclusion. Reads only record bboxes outside those regions."""
    from shapely.geometry import shape
    rd = mtbs_reader(path)
    seen, out = set(), []
    for e in events:
        dlat = radius_m / M_PER_DEG
        dlon = radius_m / (M_PER_DEG * math.cos(math.radians(e["lat"])))
        bbox = [e["lon"] - dlon, e["lat"] - dlat, e["lon"] + dlon, e["lat"] + dlat]
        for s in rd.iterShapes(bbox=bbox):
            key = (tuple(s.bbox), len(s.points))
            if key in seen:
                continue
            seen.add(key)
            out.append(shape(s.__geo_interface__))
    return out


def mtbs_interior_box(geom_wgs, lon: float, lat: float):
    """Box inside the perimeter shrunk by 200 m, capped at 400 ha, with >= 80% of
    its area inside the (unshrunk) perimeter. Returns (box_utm, epsg, inside_frac, ha) or None."""
    from shapely.geometry import box
    from src.app.geometry import reproject, utm_epsg
    epsg = utm_epsg(lon, lat)
    g = reproject(geom_wgs, 4326, epsg)
    core = g.buffer(-MTBS_SHRINK_M)
    if core.is_empty:
        return None
    if core.geom_type == "MultiPolygon":
        core = max(core.geoms, key=lambda p: p.area)
    minx, miny, maxx, maxy = core.bounds
    cx, cy = core.centroid.x, core.centroid.y
    w, h = maxx - minx, maxy - miny
    if w * h / 1e4 > MAX_BOX_HA:
        s = math.sqrt(MAX_BOX_HA * 1e4 / (w * h))
        w, h = w * s, h * s
    for _ in range(8):
        b = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        ha = b.area / 1e4
        if ha < MIN_COMP_HA:
            return None
        frac = b.intersection(g).area / b.area
        if frac >= MTBS_MIN_INSIDE:
            return b, epsg, frac, ha
        w, h = w * 0.75, h * 0.75
    return None


def draw_mtbs(zip_path: str, n_events: int, n_nulls: int, rng: np.random.Generator, tiles: HansenTiles,
              max_attempts: int, log) -> tuple[list[dict], list[dict], dict]:
    from shapely.geometry import box, mapping
    from shapely.strtree import STRtree
    from src.app.geometry import reproject
    fires = load_mtbs(zip_path, log)
    log(f"  MTBS eligible wildfires ({MTBS_DATE_LO}..{MTBS_DATE_HI}, {MTBS_MIN_AC}-{MTBS_MAX_AC} ac): {len(fires)}")
    if not fires:
        return [], [], {"eligible": 0}
    events, attempts, rej = [], 0, {"no_interior_box": 0}
    order = rng.permutation(len(fires))
    for j in order:
        if len(events) >= n_events or attempts >= max_attempts:
            break
        attempts += 1
        f = fires[int(j)]
        c = f["geom"].centroid
        r = mtbs_interior_box(f["geom"], c.x, c.y)
        if r is None:
            rej["no_interior_box"] += 1
            continue
        b, epsg, frac, ha = r
        bw = reproject(b, epsg, 4326)
        k = len(events) + 1
        cc = bw.centroid
        events.append({
            "id": f"ev-mtbs-{k:03d}", "kind": "event", "source": "mtbs", "change_type": "burn",
            "expected": "REAL", "event_date": f["ig_date"], "date_precision": "day",
            "post_months": POST_MONTHS_BURN, "climate": mtbs_climate(cc.x, cc.y),
            "box_ha": round(ha, 2), "size_bucket": size_bucket(ha),
            "box_m": [round(b.bounds[3] - b.bounds[1]), round(b.bounds[2] - b.bounds[0])],
            "lon": round(cc.x, 5), "lat": round(cc.y, 5), "geojson": mapping(bw),
            "label": f"Blind sample burn {k:03d}: MTBS {f['name'].title()} fire, {f['state']}, {f['ig_date']}",
            "provenance": {"dataset": "MTBS burned area boundaries (mtbs_perimeter_data.zip)",
                           "event_id": f["event_id"], "incident_name": f["name"], "state": f["state"],
                           "burn_bnd_ac": f["acres"], "inside_fraction": round(frac, 4),
                           "shrink_m": MTBS_SHRINK_M, "attempt": attempts},
        })
        log(f"  mtbs event {k}/{n_events}: {f['name']} {f['state']} {f['ig_date']} {ha:.0f} ha inside {frac:.2f}")
    # nulls: same sizes, tree-covered (Hansen), >= 5 km from every perimeter, within 120 km of a sampled fire
    log("  loading MTBS perimeters around the sampled fires for the exclusion index...")
    perims = mtbs_perimeters_near(zip_path, events, MTBS_NULL_MAX_DIST_M + 2 * MTBS_NULL_MIN_DIST_M)
    log(f"  {len(perims)} perimeters indexed")
    tree = STRtree(perims)
    nulls, nattempts, nrej = [], 0, {"near_perimeter": 0, "not_forest": 0, "read_error": 0}
    while len(nulls) < n_nulls and nattempts < max_attempts and events:
        nattempts += 1
        e = events[int(rng.integers(len(events)))]
        ang = float(rng.uniform(0, 2 * math.pi))
        dist = float(rng.uniform(MTBS_NULL_MIN_DIST_M * 2, MTBS_NULL_MAX_DIST_M))
        hm, wm = e["box_m"]
        lat0, lon0 = e["lat"], e["lon"]
        lat = lat0 + dist * math.sin(ang) / M_PER_DEG
        lon = lon0 + dist * math.cos(ang) / (M_PER_DEG * math.cos(math.radians(lat0)))
        dy, dx = pixel_size_m(lat)
        h, w = max(1, int(round(hm / dy))), max(1, int(round(wm / dx)))
        cand = box(lon - w * PIX_DEG / 2, lat - h * PIX_DEG / 2, lon + w * PIX_DEG / 2, lat + h * PIX_DEG / 2)
        near = cand.buffer(MTBS_NULL_MIN_DIST_M / M_PER_DEG * 1.5)     # generous degree buffer, then check in metres
        # degrees -> metres with the shorter (longitude) scale, so the 5 km rule is conservative
        deg_to_m = M_PER_DEG * math.cos(math.radians(lat))
        hit = any(perims[int(idx)].distance(cand) * deg_to_m < MTBS_NULL_MIN_DIST_M for idx in tree.query(near))
        if hit:
            nrej["near_perimeter"] += 1
            continue
        tile = tile_for(lon, lat)
        try:
            b = tiles.bounds(tile)
            r0 = int(round((b.top - (lat + h * PIX_DEG / 2)) / PIX_DEG))
            c0 = int(round((lon - w * PIX_DEG / 2 - b.left) / PIX_DEG))
            br, bc = int(math.ceil(NULL_BUFFER_M / dy)), int(math.ceil(NULL_BUFFER_M / dx))
            if r0 - br < 0 or c0 - bc < 0 or r0 + h + br > TILE_PX or c0 + w + bc > TILE_PX:
                nrej["not_forest"] += 1
                continue
            tc = tiles.read(tile, "treecover2000", r0 - br, c0 - bc, h + 2 * br, w + 2 * bc)
            ly = tiles.read(tile, "lossyear", r0 - br, c0 - bc, h + 2 * br, w + 2 * bc)
        except Exception as ex:                           # noqa: BLE001
            nrej["read_error"] += 1
            log(f"  read error {tile}: {ex}")
            continue
        inner_tc = tc[br:br + h, bc:bc + w]
        if (inner_tc < TC_EVENT).mean() > 0.2 or ly.any():
            nrej["not_forest"] += 1
            continue
        geo = tiles.box_geojson(tile, r0, r0 + h, c0, c0 + w)
        k = len(nulls) + 1
        ha = round(h * w * pixel_ha(lat), 2)
        nulls.append({
            "id": f"nl-mtbs-{k:03d}", "kind": "null", "source": "mtbs", "change_type": "burn",
            "expected": "NOT_REAL", "event_date": e["event_date"], "date_precision": "day",
            "post_months": POST_MONTHS_BURN, "climate": mtbs_climate(lon, lat),
            "box_ha": ha, "size_bucket": size_bucket(ha), "box_m": [round(h * dy), round(w * dx)],
            "lon": round(lon, 5), "lat": round(lat, 5), "geojson": geo,
            "label": f"Blind sample burn null {k:03d}: tree-covered land >= 5 km from any MTBS perimeter, near {e['provenance']['state']}",
            "provenance": {"dataset": "MTBS perimeters (exclusion) + Hansen treecover2000/lossyear (cover check)",
                           "paired_event": e["id"], "distance_from_event_m": round(dist), "tile": tile,
                           "box_rc": [r0, r0 + h, c0, c0 + w], "treecover_min_required": TC_EVENT,
                           "treecover_mean": round(float(inner_tc.mean()), 1), "attempt": nattempts},
        })
        log(f"  mtbs null {k}/{n_nulls}: {tile} {ha} ha near {e['id']} (attempt {nattempts})")
    return events, nulls, {"eligible": len(fires), "event_attempts": attempts, **rej,
                           "null_attempts": nattempts, **{"null_" + k: v for k, v in nrej.items()}}


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:                                     # noqa: BLE001
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n-events", type=int, default=60, help="Hansen loss events")
    ap.add_argument("--n-null", type=int, default=60, help="Hansen no-loss areas")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mtbs", default=None, help="path to mtbs_perimeter_data.zip (optional)")
    ap.add_argument("--n-mtbs-events", type=int, default=15)
    ap.add_argument("--n-mtbs-null", type=int, default=15)
    ap.add_argument("--max-attempts", type=int, default=4000)
    ap.add_argument("--today", default=None, help="override today's date (YYYY-MM-DD), for reproducibility")
    a = ap.parse_args(argv)

    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    years = allowed_years(today)
    log = lambda s: print(s, flush=True)                  # noqa: E731
    t0 = time.time()
    log(f"blind_sample seed={a.seed} events={a.n_events} nulls={a.n_null} years={years}")
    tiles = HansenTiles(HANSEN_TILES)
    ok_tiles = tiles.check()
    log(f"  tiles open: {ok_tiles}")

    events, ev_stats = draw_hansen_events(tiles, ok_tiles, a.n_events, substream(a.seed, 1), years, a.max_attempts, log)
    nulls, nl_stats = draw_hansen_nulls(tiles, ok_tiles, a.n_null, substream(a.seed, 2), events, a.max_attempts, log)
    mtbs_events, mtbs_nulls, mtbs_stats = [], [], {"used": False}
    if a.mtbs:
        if os.path.exists(a.mtbs):
            try:
                mtbs_events, mtbs_nulls, st = draw_mtbs(a.mtbs, a.n_mtbs_events, a.n_mtbs_null,
                                                        substream(a.seed, 3), tiles, a.max_attempts, log)
                mtbs_stats = {"used": True, **st}
            except Exception as e:                        # noqa: BLE001
                log(f"  MTBS skipped: {e}")
                mtbs_stats = {"used": False, "error": str(e)}
        else:
            mtbs_stats = {"used": False, "error": f"{a.mtbs} not found"}

    items = events + nulls + mtbs_events + mtbs_nulls
    out = {
        "seed": a.seed, "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "today": today.isoformat(), "git_commit": git_commit(),
        "command": "python -m scripts.blind_sample " + " ".join(sys.argv[1:] if argv is None else argv),
        "hansen": {"version": HANSEN_VERSION, "url": HANSEN_URL, "tiles_requested": HANSEN_TILES,
                   "tiles_open": ok_tiles, "tiles_failed": sorted(tiles.failed), "climate_by_tile": TILE_CLIMATE,
                   "years": years, "reads": tiles.reads, "read_seconds": round(tiles.read_seconds, 1)},
        "criteria": {"window_px": WINDOW_PX, "component_ha": [MIN_COMP_HA, MAX_COMP_HA], "max_box_ha": MAX_BOX_HA,
                     "min_loss_fraction": MIN_LOSS_FRAC, "treecover_event": TC_EVENT, "treecover_null": TC_NULL,
                     "null_buffer_m": NULL_BUFFER_M, "post_months_clearing": POST_MONTHS_CLEARING,
                     "mtbs": {"acres": [MTBS_MIN_AC, MTBS_MAX_AC], "dates": [MTBS_DATE_LO.isoformat(), MTBS_DATE_HI.isoformat()],
                              "shrink_m": MTBS_SHRINK_M, "min_inside": MTBS_MIN_INSIDE,
                              "null_min_dist_m": MTBS_NULL_MIN_DIST_M, "post_months_burn": POST_MONTHS_BURN}},
        "stats": {"hansen_events": ev_stats, "hansen_nulls": nl_stats, "mtbs": mtbs_stats,
                  "seconds": round(time.time() - t0, 1)},
        "n_items": len(items), "items": items,
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    log(f"wrote {a.out}: {len(events)} events, {len(nulls)} nulls, {len(mtbs_events)} MTBS events, "
        f"{len(mtbs_nulls)} MTBS nulls in {time.time() - t0:.0f}s ({tiles.reads} window reads)")


if __name__ == "__main__":
    main()
