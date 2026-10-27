import numpy as np
import pytest
from rasterio.transform import Affine

from mielizna.grid import Grid
from mielizna import osm
from mielizna.osm import lake_polygon, points_gdf

LAT, LON = 50.455, 17.26
DLAT, DLON = 0.0045, 0.007  # ~0.5 km i ~0.5 km


def _ring(lat0, lon0, dlat, dlon):
    return [
        {"lat": lat0 - dlat, "lon": lon0 - dlon},
        {"lat": lat0 - dlat, "lon": lon0 + dlon},
        {"lat": lat0 + dlat, "lon": lon0 + dlon},
        {"lat": lat0 + dlat, "lon": lon0 - dlon},
        {"lat": lat0 - dlat, "lon": lon0 - dlon},
    ]


@pytest.fixture
def sample_json():
    return {"elements": [
        {"type": "node", "id": 1, "lat": LAT, "lon": LON,
         "tags": {"leisure": "marina", "name": "Przystań"}},
        {"type": "node", "id": 2, "lat": LAT + 0.001, "lon": LON,
         "tags": {"leisure": "slipway"}},
        {"type": "relation", "id": 2908769, "tags": {"type": "multipolygon"},
         "members": [{"type": "way", "ref": 10, "role": "outer",
                      "geometry": _ring(LAT, LON, DLAT, DLON)}]},
    ]}


@pytest.fixture
def split_json():
    """Outer złożony z dwóch otwartych ścieżek + wyspa (inner)."""
    ring = _ring(LAT, LON, DLAT, DLON)
    return {"elements": [
        {"type": "relation", "id": 2908769, "members": [
            {"type": "way", "ref": 10, "role": "outer", "geometry": ring[:3]},
            {"type": "way", "ref": 11, "role": "outer", "geometry": ring[2:]},
            {"type": "way", "ref": 12, "role": "inner",
             "geometry": _ring(LAT, LON, DLAT / 4, DLON / 4)},
        ]},
    ]}


def test_points_gdf_kinds_and_crs(sample_json):
    g = points_gdf(sample_json)
    assert set(g.kind) == {"marina", "slipway"}
    assert g.crs.to_epsg() == 2180


def test_lake_polygon_area(sample_json):
    p = lake_polygon(sample_json)
    assert 0.8e6 < p.area < 1.2e6  # ~1 km²


def test_lake_polygon_joins_ways_and_cuts_holes(split_json):
    p = lake_polygon(split_json)
    full = lake_polygon({"elements": [{"type": "relation", "id": 2908769, "members": [
        {"type": "way", "role": "outer", "geometry": _ring(LAT, LON, DLAT, DLON)}]}]})
    assert p.geom_type == "Polygon"
    assert len(p.interiors) == 1
    assert p.area == pytest.approx(full.area * (1 - 1 / 16), rel=1e-3)


def test_masks_from_gpkg(tmp_path, monkeypatch, sample_json):
    import geopandas as gpd
    p = lake_polygon(sample_json)
    gpkg = tmp_path / "lake.gpkg"
    gpd.GeoDataFrame(geometry=[p], crs=2180).to_file(gpkg, layer="lake", driver="GPKG")
    gpd.GeoDataFrame(geometry=[p.buffer(500)], crs=2180).to_file(gpkg, layer="aoi", driver="GPKG")
    monkeypatch.setattr(osm, "data_path", lambda kind, *parts: gpkg)
    x0, y0, x1, y1 = p.buffer(1000).bounds
    grid = Grid(crs="EPSG:2180", transform=Affine(10, 0, x0, 0, -10, y1),
                width=int((x1 - x0) // 10), height=int((y1 - y0) // 10))
    lake, aoi = osm.lake_mask(grid), osm.aoi_mask(grid)
    assert lake.dtype == bool and lake.shape == (grid.height, grid.width)
    assert lake.sum() * 100 == pytest.approx(p.area, rel=0.05)
    assert aoi.sum() > lake.sum() and not (lake & ~aoi).any()
