import pytest
import rasterio.transform
from pyproj import Transformer

from app.point import point_info
from app.zones import ZONE_NAMES, zone_classes


def lonlat_of(products, row, col):
    x, y = rasterio.transform.xy(products.transform, row, col)
    return Transformer.from_crs(products.crs, 4326, always_xy=True).transform(x, y)


def test_point_kinds(products):
    k = lambda col, h=195.0: point_info(products, *lonlat_of(products, 5, col), h, 1.2, 0.3)
    assert k(3)["kind"] == "model" and k(3)["z_min"] == 193.0 and k(3)["z_max"] == 194.0
    aw = k(15)
    assert aw["kind"] == "always_water" and aw["depth_max"] is None and aw["depth_min"] == 1.95
    assert aw["clearance_max"] is None and aw["z_min"] is None
    land = k(22)
    assert land["kind"] == "land" and land["bottom_above_water_min"] == 1.0
    assert land["bottom_above_water_max"] is None
    assert k(27)["kind"] == "outside" and k(27)["zone"] is None
    assert k(29)["kind"] == "outside" and k(29)["z_min"] is None


def test_point_model_values(products):
    p = point_info(products, *lonlat_of(products, 5, 3), 195.0, 1.2, 0.3)
    assert (p["depth_min"], p["depth_max"]) == (1.0, 2.0)
    assert (p["clearance_min"], p["clearance_max"]) == (-0.2, 0.8)
    assert p["z"] == 193.5 and p["unc"] == 0.2 and p["obs_count"] == 5
    assert p["bottom_above_water_min"] is None


def test_point_zone_equals_zone_raster(products):
    c = zone_classes(195.0, 1.2, 0.3, products.z_lo, products.z_hi, products.in_model)
    for col in (3, 15, 22):
        assert point_info(products, *lonlat_of(products, 5, col), 195.0, 1.2, 0.3)["zone"] == ZONE_NAMES[c[5, col]]


def test_point_far_away_is_outside(products):
    assert point_info(products, 21.0, 52.2, 195.0, 1.2, 0.3)["kind"] == "outside"


def test_point_endpoint_json_has_no_infinity(client, products):
    lon, lat = lonlat_of(products, 5, 15)
    r = client.get("/api/point", params={"lon": lon, "lat": lat, "h": 195.0, "draft": 1.2})
    assert r.status_code == 200 and "Infinity" not in r.text and "NaN" not in r.text
    assert r.json()["kind"] == "always_water"


@pytest.mark.parametrize("q", [{"lon": "nan", "lat": 50.4, "h": 195}, {"lon": 17.0, "lat": "inf", "h": 195},
                               {"lon": 17.0, "lat": 50.4, "h": "nan"}, {"lon": 17.0, "lat": 50.4, "h": 150},
                               {"lon": 17.0, "lat": 50.4, "h": 195, "draft": 5},
                               {"lon": 17.0, "lat": 50.4, "h": 195, "margin": 2}, {"lat": 50.4, "h": 195}])
def test_point_validation_422(client, q):
    assert client.get("/api/point", params=q).status_code == 422


def test_outside_model_obs_count_is_none(products):
    for col in (25, 26, 27, 28, 29):                     # 25-27: obs 65535 w pliku, 28-29: obs 0
        p = point_info(products, *lonlat_of(products, 5, col), 195.0, 1.2, 0.3)
        assert p["kind"] == "outside" and p["obs_count"] is None
    assert point_info(products, 21.0, 52.2, 195.0, 1.2, 0.3)["obs_count"] is None


def test_point_h_out_of_slider_has_standard_422_body(client):
    d = client.get("/api/point", params={"lon": 17.0, "lat": 50.4, "h": 150}).json()["detail"]
    assert isinstance(d, list) and d[0]["loc"] == ["query", "h"]
