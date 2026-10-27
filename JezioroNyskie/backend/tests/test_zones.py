import geopandas as gpd
import numpy as np
import pytest

from app.zones import (DANGER, NONE, RISK, SAFE, ZONE_NAMES, round_param, zone_classes, zone_stats,
                       zone_warnings, zones_geojson)


def arr(*v): return np.array(v, dtype=float).reshape(1, -1)


def test_zone_rule_brief_6_4():
    z_lo = arr(193.0, 193.0, 193.0, -np.inf, 196.0)
    z_hi = arr(193.4, 194.0, 195.0, 193.05, np.inf)
    c = zone_classes(195.0, 1.2, 0.3, z_lo, z_hi, np.ones_like(z_lo, bool))
    # D_lo=1.6>=1.5 safe; D_lo=1.0, D_hi=2.0 risk; D_hi=2.0, D_lo=0 risk; always water D_lo=1.95 safe; land h<z_min danger
    assert c.tolist() == [[SAFE, RISK, RISK, SAFE, DANGER]]
    assert c.dtype == np.uint8


def test_boundary_equality_is_safe():
    c = zone_classes(195.5, 1.2, 0.3, arr(190.0), arr(194.0), np.ones((1, 1), bool))
    assert c[0, 0] == SAFE            # D_lo == d + m dokładnie


def test_danger_wins_on_inverted_bounds():
    c = zone_classes(195.0, 0.5, 0.0, arr(194.8), arr(194.0), np.ones((1, 1), bool))
    assert c[0, 0] == DANGER          # D_lo=1.0 >= 0.5, ale D_hi=0.2 < 0.5


def test_outside_model_is_none():
    c = zone_classes(195.0, 1.2, 0.3, arr(193.0), arr(194.0), np.zeros((1, 1), bool))
    assert c[0, 0] == NONE


def test_outside_model_nan_no_warnings():
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        c = zone_classes(195.0, 1.2, 0.3, arr(np.nan, 193.0), arr(np.nan, 194.0),
                         np.array([[False, True]]))
    assert c.tolist() == [[NONE, RISK]]


def test_round_param():
    assert round_param(195.2300001) == 195.25 and round_param(1.224) == 1.2 and round_param(0.3) == 0.3


def test_stats_empty_water_gives_zero_pct():
    z_lo = arr(196.0, 196.0); c = zone_classes(192.0, 1.0, 0.3, z_lo, arr(np.inf, np.inf), np.ones((1, 2), bool))
    s = zone_stats(c, 192.0, z_lo, np.ones((1, 2), bool))
    assert s["water_km2"] == 0 and s["safe_pct"] == s["risk_pct"] == s["danger_pct"] == 0
    assert s["danger_km2"] == pytest.approx(2e-4)


def test_stats_counts_and_pct():
    z_lo = arr(193.0, 193.0, 193.0, 196.0, np.nan)
    z_hi = arr(193.4, 194.0, 195.0, np.inf, np.nan)
    m = np.array([[True, True, True, True, False]])
    c = zone_classes(195.0, 1.2, 0.3, z_lo, z_hi, m)
    s = zone_stats(c, 195.0, z_lo, m)
    assert s["water_km2"] == pytest.approx(3e-4)
    assert s["safe_km2"] == pytest.approx(1e-4) and s["risk_km2"] == pytest.approx(2e-4)
    assert s["danger_km2"] == pytest.approx(1e-4)
    assert s["safe_pct"] == pytest.approx(100 / 3) and s["risk_pct"] == pytest.approx(200 / 3)
    assert s["danger_pct"] == 0          # ląd (danger) nie należy do akwenu


def test_pct_sums_to_100_on_products(products):
    c = zone_classes(195.0, 1.2, 0.3, products.z_lo, products.z_hi, products.in_model)
    s = zone_stats(c, 195.0, products.z_lo, products.in_model)
    assert s["water_km2"] > 0
    assert s["safe_pct"] + s["risk_pct"] + s["danger_pct"] == pytest.approx(100)


def test_warnings(products):
    assert zone_warnings(195.0, 1.2, 0.3, products) == []
    assert "h_out_of_range" in zone_warnings(198.5, 1.2, 0.3, products)
    assert "below_observed_bottom" in zone_warnings(194.0, 1.0, 0.3, products)


def _first_coord(geometry):
    """Pierwsza para (lon, lat) z geometrii (Multi)Polygon z GeoJSON."""
    c = geometry["coordinates"]
    while isinstance(c[0], (list, tuple)):
        c = c[0]
    return c[0], c[1]


def test_zones_geojson_shape_and_crs(products):
    c = zone_classes(195.0, 1.2, 0.3, products.z_lo, products.z_hi, products.in_model)
    fc = zones_geojson(c, products.transform, products.crs)
    assert fc["type"] == "FeatureCollection"
    assert [f["properties"]["zone"] for f in fc["features"]] == sorted(
        {ZONE_NAMES[v] for v in np.unique(c) if v}, key=["safe", "risk", "danger"].index)
    lon, lat = _first_coord(fc["features"][0]["geometry"])
    assert 17.0 < lon < 17.5 and 50.3 < lat < 50.6          # lon pierwsza (Review Focus 2)
    area = gpd.GeoDataFrame.from_features(fc["features"], crs=4326).to_crs(2180).area.sum()
    assert area == pytest.approx((c > 0).sum() * 100, rel=0.02)


def test_zones_geojson_valid_rounded_and_empty(products):
    c = zone_classes(195.0, 1.2, 0.3, products.z_lo, products.z_hi, products.in_model)
    fc = zones_geojson(c, products.transform, products.crs)
    gdf = gpd.GeoDataFrame.from_features(fc["features"], crs=4326)
    assert gdf.is_valid.all()
    lon, lat = _first_coord(fc["features"][0]["geometry"])
    assert lon == round(lon, 6) and lat == round(lat, 6)
    empty = zones_geojson(np.zeros_like(c), products.transform, products.crs)
    assert empty == {"type": "FeatureCollection", "features": []}
