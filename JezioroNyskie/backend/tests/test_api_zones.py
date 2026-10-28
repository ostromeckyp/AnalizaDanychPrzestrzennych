import pytest

from app.cache import TTLStore
from app.main import create_app
from app.settings import Settings


def test_zones_endpoint(client):
    r = client.get("/api/zones", params={"h": 195.0, "draft": 1.2})
    assert r.status_code == 200
    j = r.json()
    assert j["params"] == {"h": 195.0, "draft": 1.2, "margin": 0.3}
    assert {f["properties"]["zone"] for f in j["features"]} <= {"safe", "risk", "danger"}
    assert abs(j["stats"]["safe_pct"] + j["stats"]["risk_pct"] + j["stats"]["danger_pct"] - 100) < 1e-6
    assert j["model_version"] == "all-testver00001"
    assert r.headers["cache-control"] == "public, max-age=300"


def test_rounding_shares_etag(client):
    a = client.get("/api/zones", params={"h": 195.2300001, "draft": 1.2})
    b = client.get("/api/zones", params={"h": 195.25, "draft": 1.2})
    assert a.headers["etag"] == b.headers["etag"] and a.json()["params"]["h"] == 195.25
    assert a.headers["etag"] == 'W/"all-testver00001-195.25-1.20-0.30"'


def test_if_none_match_304(client):
    e = client.get("/api/zones", params={"h": 195.0, "draft": 1.2}).headers["etag"]
    r = client.get("/api/zones", params={"h": 195.0, "draft": 1.2}, headers={"If-None-Match": e})
    assert r.status_code == 304 and r.content == b""
    assert r.headers["etag"] == e


@pytest.mark.parametrize("q", [{"h": 150, "draft": 1}, {"h": 195, "draft": 5}, {"h": 195, "draft": 1, "margin": 2},
                               {"h": 199.5, "draft": 1}, {"h": "nan", "draft": 1}, {"h": "inf", "draft": 1}])
def test_validation_422(client, q):
    assert client.get("/api/zones", params=q).status_code == 422


@pytest.mark.parametrize("h", [150, 199.5])
def test_zones_h_out_of_slider_has_standard_422_body(client, h):
    d = client.get("/api/zones", params={"h": h, "draft": 1}).json()["detail"]
    assert isinstance(d, list) and d[0]["loc"] == ["query", "h"] and d[0]["type"] == "value_error"
    assert "suwaka" in d[0]["msg"]


def test_zones_response_is_typed_geojson(client):
    from app.schemas import ZonesResponse
    j = client.get("/api/zones", params={"h": 195.0, "draft": 1.2}).json()
    ZonesResponse.model_validate(j)
    assert j["type"] == "FeatureCollection" and all(f["type"] == "Feature" for f in j["features"])


def test_zones_cached(app, client):
    q = {"h": 195.0, "draft": 1.2}
    client.get("/api/zones", params=q)
    assert app.state.cache.get(("zones", 195.0, 1.2, 0.3, "all-testver00001")) is not None


def test_zones_warning_out_of_range(client):
    j = client.get("/api/zones", params={"h": 198.5, "draft": 1.2}).json()
    assert "h_out_of_range" in j["warnings"]


def test_meta(client):
    r = client.get("/api/meta")
    m = r.json()
    assert m["slider"] == {"min": 192.4, "max": 198.9, "step": 0.05}
    assert m["npp"] < m["max_pp"] <= m["slider"]["max"] and m["n_scenes"] == 2
    assert m["defaults"] == {"h": 193.5, "draft": 1.2, "margin": 0.3}
    assert m["limits"] == {"draft": [0.1, 3.0], "margin": [0.0, 1.0]}
    assert m["first_scene_date"] == "2026-09-30" and m["last_scene_date"] == "2026-10-20"
    assert m["crs"] == "EPSG:2180" and m["presets_provisional"] is True
    assert [p["draft"] for p in m["draft_presets"]] == [0.9, 0.4, 1.25]
    assert {k: m["accuracy"][k] for k in ("rf_oa", "rf_ba", "rf_kappa", "otsu_ba", "n_labels")} == {
        "rf_oa": 0.8, "rf_ba": 0.77, "rf_kappa": 0.37, "otsu_ba": 0.77, "n_labels": 185}
    lon0, lat0, lon1, lat1 = m["bbox_wgs84"]
    assert lon0 < lon1 and lat0 < lat1 and 14 < lon0 < 25 and 49 < lat0 < 55
    assert [p["date"] for p in m["area_level"]["points"]] == ["2026-09-30", "2026-10-20"]
    assert m["area_level"]["nodes_h"] == [192.9, 194.0, 197.0]
    assert r.headers["etag"].startswith('W/"all-testver00001-')
    assert client.get("/api/meta", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_lazy_app_import_without_data(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, live=False))
    assert app.openapi()["info"]["title"]


def test_ttlstore_roundtrip():
    s = TTLStore(maxsize=2, ttl_s=60)
    assert s.get("a") is None
    s.set("a", 1)
    assert s.get("a") == 1


def test_zone_features_have_no_null_id_or_bbox(client):
    j = client.get("/api/zones", params={"h": 195.0, "draft": 1.2}).json()
    assert j["features"]
    for f in j["features"]:
        assert "bbox" not in f or isinstance(f["bbox"], list)
        assert "id" not in f or f["id"] is not None


def test_zone_features_without_id_bbox_omit_keys(client, monkeypatch):
    """Cecha bez id/bbox nie może dostać `null` w JSON-ie (RFC 7946)."""
    import app.main as m
    feat = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [17.0, 50.0]},
            "properties": {"zone": "safe"}}
    monkeypatch.setattr(m, "zones_geojson", lambda *a, **k: {"type": "FeatureCollection", "features": [feat]})
    f = client.get("/api/zones", params={"h": 195.0, "draft": 1.2, "margin": 0.31}).json()["features"][0]
    assert "id" not in f and "bbox" not in f
