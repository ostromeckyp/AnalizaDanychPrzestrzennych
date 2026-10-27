import pytest


def test_scenes_only_published(client):
    s = client.get("/api/scenes").json()
    assert len(s) == 2 and all(x["h_t"] is not None for x in s)
    assert [x["date"] for x in s] == sorted(x["date"] for x in s)
    assert {"date", "h_t", "h_sigma", "h_method", "area_km2", "area_otsu_km2", "otsu_threshold",
            "local_cloud_pct", "lake_nodata_pct"} == set(s[0])


def test_shoreline_feature_and_404(client, dataset_qc_false_date):
    d = client.get("/api/scenes").json()[0]["date"]
    f = client.get("/api/shorelines", params={"date": d}).json()
    assert f["type"] == "Feature" and f["properties"]["date"] == d
    assert f["properties"] == client.get("/api/scenes").json()[0]
    lon, lat = f["geometry"]["coordinates"][0][0]
    assert 14 < lon < 25 and 49 < lat < 55          # EPSG:4326
    assert client.get("/api/shorelines", params={"date": dataset_qc_false_date}).status_code == 404
    assert client.get("/api/shorelines", params={"date": "1999-01-01"}).status_code == 404


def test_capacity_roundtrip(client):
    h = client.get("/api/capacity-to-level", params={"v": 65.69}).json()
    assert h["in_table"] and h["h"] == pytest.approx(195.91, abs=0.01)
    v = client.get("/api/level-to-capacity", params={"h": h["h"]}).json()
    assert v["v"] == pytest.approx(65.69, abs=0.01)
    assert client.get("/api/capacity-to-level", params={"v": 150}).json() == {"v": 150.0, "h": None, "in_table": False}
    assert client.get("/api/level-to-capacity", params={"h": 185}).json() == {"h": 185.0, "v": None, "in_table": False}


@pytest.mark.parametrize("url,q", [("capacity-to-level", {"v": 0}), ("capacity-to-level", {"v": 201}),
                                   ("capacity-to-level", {"v": "nan"}), ("capacity-to-level", {"v": "inf"}),
                                   ("level-to-capacity", {"h": 179}), ("level-to-capacity", {"h": 211}),
                                   ("level-to-capacity", {"h": "nan"}), ("level-to-capacity", {"h": "inf"})])
def test_capacity_validation_422(client, url, q):
    assert client.get(f"/api/{url}", params=q).status_code == 422


def test_marinas(client):
    fc = client.get("/api/marinas").json()
    assert len(fc["features"]) == 2 and {"osm_id", "kind", "name"} <= set(fc["features"][0]["properties"])
    lon, lat = fc["features"][0]["geometry"]["coordinates"]
    assert 14 < lon < 25 and 49 < lat < 55


@pytest.mark.parametrize("url,q", [("scenes", {}), ("shorelines", {"date": "2026-10-20"}), ("marinas", {}),
                                   ("capacity-to-level", {"v": 65.69}), ("level-to-capacity", {"h": 195.0})])
def test_etag_and_304(client, url, q):
    r = client.get(f"/api/{url}", params=q)
    assert r.headers["etag"].startswith('W/"all-testver00001') and r.headers["cache-control"] == "public, max-age=3600"
    r2 = client.get(f"/api/{url}", params=q, headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304


def test_capacity_does_not_touch_environ(dataset, monkeypatch):
    import os
    from fastapi.testclient import TestClient
    from app.data import load_products
    from app.main import create_app
    from app.settings import Settings
    monkeypatch.delenv("MIELIZNA_DATA_DIR", raising=False)
    p = load_products(dataset, "all")
    assert "MIELIZNA_DATA_DIR" not in os.environ
    c = TestClient(create_app(Settings(data_dir=dataset, live=False), p))
    assert c.get("/api/capacity-to-level", params={"v": 65.69}).status_code == 200
    assert c.get("/api/level-to-capacity", params={"h": 195.0}).status_code == 200
    assert "MIELIZNA_DATA_DIR" not in os.environ


def test_geojson_endpoints_match_schemas(client):
    from app.schemas import MarinasResponse, ShorelineFeature
    ShorelineFeature.model_validate(client.get("/api/shorelines", params={"date": "2026-10-20"}).json())
    MarinasResponse.model_validate(client.get("/api/marinas").json())


def test_openapi_documents_geojson_and_404(app):
    paths = app.openapi()["paths"]
    for url in ("/api/shorelines", "/api/marinas"):
        assert paths[url]["get"]["responses"]["200"]["content"]["application/json"]["schema"] != {}
    assert "404" in paths["/api/shorelines"]["get"]["responses"]
    assert "2×" in paths["/api/layers/uncertainty.png"]["get"]["description"]
