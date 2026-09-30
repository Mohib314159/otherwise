"""Tests for src/app/geometry.py: polygon validation, UTM zones, donor grid, bbox."""
from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import Polygon, box, mapping

from src.app.geometry import (
    PolygonError,
    bbox_wgs84,
    donor_grid,
    utm_epsg,
    validate_polygon,
)


def _square_geojson(lon=-1.29, lat=52.9, dlon=0.0046, dlat=0.0028):
    """~10 ha square near (-1.29, 52.9)."""
    coords = [
        [lon, lat],
        [lon + dlon, lat],
        [lon + dlon, lat + dlat],
        [lon, lat + dlat],
        [lon, lat],
    ]
    return {"type": "Polygon", "coordinates": [coords]}


def _square_of_side_deg(lon, lat, side_deg):
    coords = [
        [lon, lat],
        [lon + side_deg, lat],
        [lon + side_deg, lat + side_deg],
        [lon, lat + side_deg],
        [lon, lat],
    ]
    return {"type": "Polygon", "coordinates": [coords]}


def test_validate_polygon_accepts_ten_hectare_square():
    area = validate_polygon(_square_geojson())
    assert 5 < area.area_ha < 20
    assert area.epsg == 32630


def test_validate_polygon_accepts_feature_wrapper():
    feature = {"type": "Feature", "properties": {}, "geometry": _square_geojson()}
    area = validate_polygon(feature)
    assert 5 < area.area_ha < 20
    assert area.epsg == 32630


def test_validate_polygon_rejects_tiny_area():
    tiny = _square_of_side_deg(-1.29, 52.9, 0.0003)  # well under 0.5 ha
    with pytest.raises(PolygonError):
        validate_polygon(tiny)


def test_validate_polygon_rejects_huge_area():
    huge = _square_of_side_deg(-1.29, 52.9, 0.3)  # well over 500 ha
    with pytest.raises(PolygonError):
        validate_polygon(huge)


def test_validate_polygon_rejects_point():
    point = {"type": "Point", "coordinates": [-1.29, 52.9]}
    with pytest.raises(PolygonError):
        validate_polygon(point)


@pytest.mark.parametrize(
    "lon,lat,expected",
    [
        (-1.3, 52.9, 32630),
        (151.2, -33.9, 32756),
        (-122.4, 37.8, 32610),
    ],
)
def test_utm_epsg(lon, lat, expected):
    assert utm_epsg(lon, lat) == expected


def test_donor_grid_properties():
    area = validate_polygon(_square_geojson())
    grid = donor_grid(area, inner_m=1000.0, outer_m=6000.0, max_cells=50)

    assert len(grid.cells) <= 50
    assert len(grid.cells) == len(grid.distances_m)
    assert len(grid.cells) > 0

    target_area = area.utm.area
    for cell in grid.cells:
        assert isinstance(cell, Polygon)
        assert abs(cell.area - target_area) / target_area < 0.02
        assert not cell.intersects(area.utm)

    for d in grid.distances_m:
        assert 1000.0 <= d <= 6000.0

    dists = list(grid.distances_m)
    assert dists == sorted(dists)


def test_bbox_wgs84_contains_area_bounds():
    area = validate_polygon(_square_geojson())
    grid = donor_grid(area, inner_m=1000.0, outer_m=6000.0, max_cells=50)
    bbox = bbox_wgs84(area, grid)

    assert len(bbox) == 4
    minlon, minlat, maxlon, maxlat = bbox
    assert minlon < maxlon
    assert minlat < maxlat

    area_minlon, area_minlat, area_maxlon, area_maxlat = area.wgs84.bounds
    assert minlon <= area_minlon
    assert minlat <= area_minlat
    assert maxlon >= area_maxlon
    assert maxlat >= area_maxlat


# --- CRITIQUE #16 / REDTEAM E2: the inner spillover gap is edge-to-edge -----------

def _utm_square_area(ha, lon=-1.286, lat=52.908):
    """Axis-aligned square of `ha` hectares in the local UTM zone."""
    from shapely.geometry import Point
    from src.app.geometry import Area, reproject
    epsg = utm_epsg(lon, lat)
    c = reproject(Point(lon, lat), 4326, epsg)
    s = math.sqrt(ha * 10_000)
    utm = box(c.x - s / 2, c.y - s / 2, c.x + s / 2, c.y + s / 2)
    return Area(wgs84=reproject(utm, epsg, 4326), utm=utm, epsg=epsg, area_ha=ha, lon=lon, lat=lat)


def _old_rule_keys(area, inner_m, outer_m):
    """Grid indices the pre-fix rule admitted: cell CENTROID >= inner_m from the polygon."""
    side = max(math.sqrt(area.utm.area), 100.0)
    cx, cy = area.utm.centroid.x, area.utm.centroid.y
    n = int(math.ceil(outer_m / side))
    keys = set()
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            x0, y0 = cx + i * side, cy + j * side
            cell = box(x0 - side / 2, y0 - side / 2, x0 + side / 2, y0 + side / 2)
            d = cell.centroid.distance(area.utm)
            if inner_m <= d <= outer_m and not cell.intersects(area.utm):
                keys.add((i, j))
    return keys


def _grid_keys(area, grid):
    cx, cy = area.utm.centroid.x, area.utm.centroid.y
    return {(round((c.centroid.x - cx) / grid.cell_m), round((c.centroid.y - cy) / grid.cell_m))
            for c in grid.cells}


def _cell(area, side, i, j):
    x0, y0 = area.utm.centroid.x + i * side, area.utm.centroid.y + j * side
    return box(x0 - side / 2, y0 - side / 2, x0 + side / 2, y0 + side / 2)


def test_large_area_no_longer_admits_an_adjacent_cell():
    """400 ha square (2 km side): an adjacent cell's centroid is exactly 1 km
    from the area, so the old centroid rule kept it whenever float rounding
    left a ~1e-9 m sliver that `intersects` missed. It shares an edge."""
    area = _utm_square_area(400.0)
    side = math.sqrt(area.utm.area)
    old = _old_rule_keys(area, 1000.0, 12000.0)
    touching = {k for k in old if _cell(area, side, *k).distance(area.utm) < 1.0}
    assert touching, "expected the old rule to admit a cell touching the area"
    assert (0, 1) in touching                       # directly north, shares the whole edge

    grid = donor_grid(area, inner_m=1000.0, outer_m=12000.0, max_cells=10_000)
    keys = _grid_keys(area, grid)
    assert not (touching & keys)
    edge = np.asarray([c.distance(area.utm) for c in grid.cells])
    assert edge.min() >= 1000.0 - 1e-6


def test_small_area_is_effectively_unchanged():
    area = validate_polygon(_square_geojson())      # ~10 ha, side ~320 m
    old = _old_rule_keys(area, 1000.0, 6000.0)
    grid = donor_grid(area, inner_m=1000.0, outer_m=6000.0, max_cells=10_000)
    new = _grid_keys(area, grid)
    assert len(new) == len(grid.cells)
    assert new <= old                               # only ever removes cells
    assert len(old - new) / len(old) < 0.05         # and only a thin inner shell
    dropped_edge = []                               # the dropped cells sat within half a cell of 1 km
    side = grid.cell_m
    for i, j in old - new:
        dropped_edge.append(_cell(area, side, i, j).distance(area.utm))
    assert all(1000.0 - side / 2 - 1e-6 <= d < 1000.0 for d in dropped_edge)


@pytest.mark.parametrize("ha", [1.0, 10.0, 50.0, 200.0, 400.0, 500.0])
@pytest.mark.parametrize("inner_m", [1000.0, 2500.0])
def test_every_ring_cell_clears_the_edge_gap(ha, inner_m):
    area = _utm_square_area(ha)
    grid = donor_grid(area, inner_m=inner_m, outer_m=12000.0)
    assert len(grid.cells) > 0
    for c in grid.cells:
        assert c.distance(area.utm) >= inner_m - 1e-6


def test_strip_area_cells_clear_the_edge_gap():
    """A long thin area (road, river bank) is where centroid rules leak most."""
    from shapely.geometry import Point
    from src.app.geometry import Area, reproject
    lon, lat = -1.286, 52.908
    epsg = utm_epsg(lon, lat)
    c = reproject(Point(lon, lat), 4326, epsg)
    utm = box(c.x - 70, c.y - 1770, c.x + 70, c.y + 1770)
    area = Area(wgs84=reproject(utm, epsg, 4326), utm=utm, epsg=epsg,
                area_ha=utm.area / 1e4, lon=lon, lat=lat)
    grid = donor_grid(area)
    assert min(c.distance(area.utm) for c in grid.cells) >= 1000.0 - 1e-6


@pytest.mark.parametrize("ha,inner_m,outer_m", [(400.0, 1000.0, 12000.0), (500.0, 2000.0, 20000.0),
                                                (100.0, 20000.0, 150000.0)])
def test_wide_candidates_use_the_same_edge_gap(ha, inner_m, outer_m):
    from src.app.geometry import wide_candidates
    area = _utm_square_area(ha)
    cands = wide_candidates(area, inner_m, outer_m, n=300)
    assert len(cands.cells) == 300
    assert list(cands.distances_m) == sorted(cands.distances_m)
    for c in cands.cells:
        assert c.distance(area.utm) >= inner_m - 1e-6


def test_wide_candidates_unchanged_when_nothing_is_rejected():
    """When no draw falls in the thin shell the edge rule removes, the result is
    exactly the plain uniform-by-area sample with the same seed (checked here
    for a 100 ha area at 20-150 km, n=200, seed 0)."""
    from src.app.geometry import wide_candidates
    area = _utm_square_area(100.0)
    inner_m, outer_m, n = 20_000.0, 150_000.0, 200
    rng = np.random.default_rng(0)
    u = rng.random(n); rng.random(n)
    r = np.sort(np.sqrt(u * (outer_m ** 2 - inner_m ** 2) + inner_m ** 2))
    cands = wide_candidates(area, inner_m, outer_m, n=n, seed=0)
    np.testing.assert_allclose(cands.distances_m, r)
