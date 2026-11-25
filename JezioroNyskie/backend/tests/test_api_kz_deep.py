"""Rastry łączone (satelita skalibrowany + mapa KŻ) w API: punkt, wersja/ETag, obrys `/api/kz-deep`, `z_max_floor`."""
import numpy as np
import rasterio.transform
from pyproj import Transformer

from app.data import load_products
from conftest import KZ_CONFLICT_PIXEL


def _lonlat(products, row, col):
    x, y = rasterio.transform.xy(products.transform, row, col)
    return Transformer.from_crs(products.crs, 4326, always_xy=True).transform(x, y)


def _point(client, products, rc, h):
    lon, lat = _lonlat(products, *rc)
    return client.get("/api/point", params={"lon": lon, "lat": lat, "h": h, "draft": 0.5, "margin": 0.3}).json()


def test_point_in_kz_pixel(client_kz, products_kz):
    b = _point(client_kz, products_kz, (3, 13), 195.0)
    assert b["bottom_source"] == "kz" and b["kz_conflict"] is False
    assert b["kz_interp"] == {"p5": -2.0, "p95": 3.0}
    assert b["kind"] == "model"                       # z_lo skończone → zwykły piksel modelu (kind bez zmian)
    assert b["z_min"] == 193.0 and b["z_max"] == 194.0
    assert b["depth_min"] == 1.0 and b["depth_max"] == 2.0   # skończone głębokości


def test_point_kz_pixel_with_low_water_is_land(client_kz, products_kz):
    b = _point(client_kz, products_kz, (3, 13), 193.0)       # h ≤ z_lo → ląd, jak dotąd
    assert b["kind"] == "land" and b["bottom_source"] == "kz"


def test_point_conflict_pixel_stays_satellite(client_kz, products_kz):
    b = _point(client_kz, products_kz, KZ_CONFLICT_PIXEL, 195.0)
    assert b["kz_conflict"] is True and b["bottom_source"] == "satellite" and b["kz_interp"] is None
    assert b["kind"] == "always_water" and b["depth_max"] is None


def test_point_satellite_and_outside_fields(client_kz, products_kz):
    b = _point(client_kz, products_kz, (5, 3), 195.0)
    assert (b["bottom_source"], b["kz_conflict"], b["kz_interp"]) == ("satellite", False, None)
    b = _point(client_kz, products_kz, (5, 28), 195.0)
    assert b["kind"] == "outside" and (b["bottom_source"], b["kz_conflict"], b["kz_interp"]) == ("satellite", False, None)


def test_without_combined_dir_as_before(client, products):
    assert "-kz" not in products.version and products.kz_interp is None
    lon, lat = _lonlat(products, 3, 13)
    b = client.get("/api/point", params={"lon": lon, "lat": lat, "h": 195.0}).json()
    assert (b["bottom_source"], b["kz_conflict"], b["kz_interp"]) == ("satellite", False, None)
    assert b["z_min"] is None                          # zawsze woda, jak w satelicie
    r = client.get("/api/kz-deep")
    assert r.status_code == 200 and r.json() == {"type": "FeatureCollection", "features": []}


def test_kz_deep_outline(client_kz):
    r = client_kz.get("/api/kz-deep")
    f = r.json()["features"]
    assert len(f) == 1 and f[0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert f[0]["properties"]["attribution"] == "Mapa KŻ Nysa (W. Wróblewski, 2023)"
    assert "KZ_ZRODLO_I_WARUNKI" in f[0]["properties"]["note"]
    lon, lat = f[0]["geometry"]["coordinates"][0][0]
    assert 15 < lon < 20 and 49 < lat < 52
    assert client_kz.get("/api/kz-deep", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_version_and_etag_change_with_kz_loo(dataset_kz):
    a = load_products(dataset_kz, "all")
    assert "-kz" in a.version
    (dataset_kz / "processed" / "eval" / "kz_loo.json").write_text('{"n": 11}', encoding="utf-8")
    b = load_products(dataset_kz, "all")
    assert a.version != b.version and a.version.split("-kz")[0] == b.version.split("-kz")[0]


def test_zones_etag_has_kz_version(client_kz, products_kz):
    assert products_kz.version in client_kz.get("/api/zones", params={"h": 195.0}).headers["etag"]


def test_no_kz_env_disables_loading(dataset_kz, monkeypatch):
    monkeypatch.setenv("MIELIZNA_NO_KZ", "1")
    p = load_products(dataset_kz, "all")
    assert "-kz" not in p.version and not (p.bounds.source == 1).any()


def test_z_max_floor_from_raw_satellite(dataset, dataset_kz):
    sat, kz = load_products(dataset, "all"), load_products(dataset_kz, "all")
    assert kz.z_max_floor == sat.z_max_floor
    assert (kz.bounds.source == 1).any() and not np.array_equal(kz.z_lo, sat.z_lo, equal_nan=True)


def test_meta_calibration_coverage(client_kz, client):
    assert client_kz.get("/api/meta").json()["accuracy"]["calibration_coverage"] == 0.9
    assert client.get("/api/meta").json()["accuracy"]["calibration_coverage"] is None
