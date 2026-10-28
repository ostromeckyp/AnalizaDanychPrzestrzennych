def test_gravel_geojson(client):
    r = client.get("/api/gravel")
    assert r.status_code == 200
    f = r.json()["features"]
    assert len(f) == 1 and f[0]["geometry"]["type"] == "Polygon"
    assert f[0]["properties"]["attribution"] == "Obrys wg mapy KŻ Nysa (W. Wróblewski, 2023)"
    lon, lat = f[0]["geometry"]["coordinates"][0][0]
    assert 15 < lon < 20 and 49 < lat < 52          # EPSG:4326


def test_gravel_404_without_file(client_no_eval):
    assert client_no_eval.get("/api/gravel").status_code == 404


def test_gravel_single_feature_and_empty_source(dataset):
    import geopandas as gpd
    from fastapi.testclient import TestClient
    from shapely.geometry import box
    from app.data import load_products
    from app.main import create_app
    from app.settings import Settings
    gpd.GeoDataFrame({"source": [None, None]}, geometry=[box(375000, 289900, 375010, 289910), box(375050, 289900, 375060, 289910)],
                     crs="EPSG:2180").to_file(dataset / "reference" / "zwirownia.gpkg", driver="GPKG")
    c = TestClient(create_app(Settings(data_dir=dataset, live=False), load_products(dataset, "all")))
    f = c.get("/api/gravel").json()["features"]
    assert len(f) == 1 and f[0]["properties"]["source"] == ""
