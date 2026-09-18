"""Polygon handling: validation, local UTM projection and the candidate donor grid.

Everything the user draws arrives as GeoJSON in WGS84. Areas are measured in a
local UTM zone so the limits are real hectares, not degrees.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import Polygon, shape, mapping, box
from shapely.ops import transform as shp_transform
from shapely.validation import make_valid

MIN_AREA_HA = 0.5
MAX_AREA_HA = 500.0


class PolygonError(ValueError):
    pass


def utm_epsg(lon: float, lat: float) -> int:
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    zone = min(max(zone, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


def transformer(src_epsg: int, dst_epsg: int) -> Transformer:
    return Transformer.from_crs(CRS.from_epsg(src_epsg), CRS.from_epsg(dst_epsg), always_xy=True)


def reproject(geom, src_epsg: int, dst_epsg: int):
    if src_epsg == dst_epsg:
        return geom
    t = transformer(src_epsg, dst_epsg)
    return shp_transform(t.transform, geom)


@dataclass
class Area:
    """A validated drawn area: WGS84 polygon plus its local UTM version."""
    wgs84: Polygon
    utm: Polygon
    epsg: int
    area_ha: float
    lon: float
    lat: float

    @property
    def geojson(self) -> dict:
        return mapping(self.wgs84)


def validate_polygon(geojson: dict) -> Area:
    """Accept a GeoJSON Polygon (or Feature) in WGS84 and check it is usable."""
    if geojson.get("type") == "Feature":
        geojson = geojson["geometry"]
    if geojson.get("type") != "Polygon":
        raise PolygonError("Draw a single polygon.")
    geom = shape(geojson)
    if not geom.is_valid:
        geom = make_valid(geom)
        if geom.geom_type != "Polygon":
            raise PolygonError("The polygon crosses itself. Redraw it without overlapping edges.")
    lon, lat = geom.centroid.x, geom.centroid.y
    if not (-180 <= lon <= 180 and -85 <= lat <= 85):
        raise PolygonError("The polygon is outside the usable latitude range.")
    epsg = utm_epsg(lon, lat)
    utm = reproject(geom, 4326, epsg)
    ha = utm.area / 10_000.0
    if ha < MIN_AREA_HA:
        raise PolygonError(f"Area is {ha:.2f} ha; the minimum is {MIN_AREA_HA} ha "
                           f"(fewer than ~50 Sentinel pixels cannot give a stable signal).")
    if ha > MAX_AREA_HA:
        raise PolygonError(f"Area is {ha:.0f} ha; the maximum is {MAX_AREA_HA:.0f} ha.")
    return Area(wgs84=geom, utm=utm, epsg=epsg, area_ha=ha, lon=lon, lat=lat)


@dataclass
class DonorGrid:
    """Candidate control cells around the area, in the area's UTM CRS."""
    cells: list[Polygon]          # in UTM
    epsg: int
    cell_m: float
    distances_m: np.ndarray       # centroid distance to the treated polygon


def donor_grid(area: Area, inner_m: float = 1000.0, outer_m: float = 12000.0,
               max_cells: int = 400) -> DonorGrid:
    """Regular grid of cells with the treated area's footprint, in a ring around it.

    - Cells inside `inner_m` of the area are excluded: neighbouring land can be
      affected by the same event (spillover), so it is not a valid control.
    - Cells are the same size as the area so their noise level is comparable.
    - If the ring holds more than `max_cells`, cells are thinned evenly by
      distance so the pool still spans the whole ring.
    """
    side = max(math.sqrt(area.utm.area), 100.0)     # metres, at least 10 px
    cx, cy = area.utm.centroid.x, area.utm.centroid.y
    n = int(math.ceil(outer_m / side))
    cells, dists = [], []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            x0, y0 = cx + i * side, cy + j * side
            cell = box(x0 - side / 2, y0 - side / 2, x0 + side / 2, y0 + side / 2)
            d = cell.centroid.distance(area.utm)
            if d < inner_m or d > outer_m:
                continue
            if cell.intersects(area.utm):
                continue
            cells.append(cell)
            dists.append(d)
    order = np.argsort(dists)
    cells = [cells[k] for k in order]
    dists = np.asarray(dists, dtype=float)[order]
    if len(cells) > max_cells:
        keep = np.linspace(0, len(cells) - 1, max_cells).round().astype(int)
        cells = [cells[k] for k in keep]
        dists = dists[keep]
    return DonorGrid(cells=cells, epsg=area.epsg, cell_m=side, distances_m=dists)


def bbox_wgs84(area: Area, grid: DonorGrid | None = None, pad_m: float = 100.0) -> list[float]:
    """WGS84 bbox covering the area and (optionally) its donor grid, for STAC search."""
    geoms = [area.utm] + (grid.cells if grid else [])
    minx = min(g.bounds[0] for g in geoms) - pad_m
    miny = min(g.bounds[1] for g in geoms) - pad_m
    maxx = max(g.bounds[2] for g in geoms) + pad_m
    maxy = max(g.bounds[3] for g in geoms) + pad_m
    b = reproject(box(minx, miny, maxx, maxy), area.epsg, 4326).bounds
    return [float(v) for v in b]


def wide_candidates(area: Area, inner_m: float, outer_m: float, n: int = 600,
                    seed: int = 0) -> DonorGrid:
    """Candidate control cells spread uniformly over a wide annulus around the
    area (for events larger than the local ring). Cells keep the area's
    footprint. Land cover, terrain and pre-event similarity filter them later."""
    side = max(math.sqrt(area.utm.area), 100.0)
    cx, cy = area.utm.centroid.x, area.utm.centroid.y
    rng = np.random.default_rng(seed)
    u = rng.random(n); th = rng.random(n) * 2 * math.pi
    r = np.sqrt(u * (outer_m ** 2 - inner_m ** 2) + inner_m ** 2)      # uniform by area
    xs, ys = cx + r * np.cos(th), cy + r * np.sin(th)
    cells = [box(x - side / 2, y - side / 2, x + side / 2, y + side / 2) for x, y in zip(xs, ys)]
    order = np.argsort(r)
    return DonorGrid(cells=[cells[k] for k in order], epsg=area.epsg, cell_m=side,
                     distances_m=np.asarray(r, dtype=float)[order])
