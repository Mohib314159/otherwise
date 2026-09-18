"""Tests for src/app/geometry.py: polygon validation, UTM zones, donor grid, bbox."""
from __future__ import annotations

import math

import pytest
from shapely.geometry import Polygon, mapping

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
