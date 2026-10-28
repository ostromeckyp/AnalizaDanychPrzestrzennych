import rasterio.transform
from pyproj import Transformer


def _lonlat(products, row, col):
    x, y = rasterio.transform.xy(products.transform, row, col)
    return Transformer.from_crs(products.crs, 4326, always_xy=True).transform(x, y)


def test_point_gravel_flag(client, products):
    lon, lat = _lonlat(products, 5, 3)             # wewnątrz obrysu (kol. 2-6, wiersze 2-8)
    assert client.get("/api/point", params={"lon": lon, "lat": lat, "h": 195.0}).json()["gravel"] is True
    lon, lat = _lonlat(products, 15, 15)
    assert client.get("/api/point", params={"lon": lon, "lat": lat, "h": 195.0}).json()["gravel"] is False


def test_point_gravel_false_without_file(client_no_eval, products):
    lon, lat = _lonlat(products, 5, 3)
    assert client_no_eval.get("/api/point", params={"lon": lon, "lat": lat, "h": 195.0}).json()["gravel"] is False
