import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.data import load_products
from app.main import create_app
from app.settings import Settings

REPO_HAZARDS = Path(__file__).resolve().parents[2] / "data" / "reference" / "locja_przeszkody.geojson"


def _client(dataset: Path, body: str | None = None) -> TestClient:
    """Klient na kopii zbioru testowego; `body` zapisuje jako plik przeszkód (None = plik z repo)."""
    dest = dataset / "reference" / "locja_przeszkody.geojson"
    if body is None:
        shutil.copy(REPO_HAZARDS, dest)
    else:
        dest.write_text(body, encoding="utf-8")
    return TestClient(create_app(Settings(data_dir=dataset, live=False), load_products(dataset, "all")))


def _feature(**props) -> dict:
    p = {"id": "x", "name": "X", "kind": "przeszkoda", "z": 193.7, "z_kind": "wierzchołek", "description": "opis",
         "coords_as_published": "50°N", "note": "", "source_url": "https://kz.nysa.pl/jezioro-nyskie/locja/"}
    p.update(props)
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [17.29, 50.45]}, "properties": p}


def _fc(*features) -> str:
    return json.dumps({"type": "FeatureCollection", "source": "Źródło testowe", "features": list(features)})


def test_hazards_present_file(dataset):
    c = _client(dataset)
    r = c.get("/api/hazards")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection" and len(body["features"]) == 5
    assert body["source"].startswith("Klub Żeglarski NYSA")
    assert body["source_url"] == "https://kz.nysa.pl/jezioro-nyskie/locja/"
    f = body["features"][0]
    assert f["geometry"]["type"] == "Point"
    lon, lat = f["geometry"]["coordinates"]
    assert 15 < lon < 20 and 49 < lat < 52
    assert {"id", "name", "kind", "z", "z_kind", "description", "coords_as_published", "note", "source_url"} <= set(f["properties"])
    assert {x["properties"]["kind"] for x in body["features"]} <= {"przeszkoda", "spłycenie"}


def test_hazards_etag_304(dataset):
    c = _client(dataset)
    etag = c.get("/api/hazards").headers["etag"]
    assert c.get("/api/hazards", headers={"If-None-Match": etag}).status_code == 304


def test_hazards_missing_file_is_empty_not_error(client_no_eval):
    r = client_no_eval.get("/api/hazards")
    assert r.status_code == 200
    assert r.json()["features"] == []


def test_hazards_broken_json_is_empty(dataset):
    r = _client(dataset, "{ nie json").get("/api/hazards")
    assert r.status_code == 200 and r.json()["features"] == []


def test_hazards_non_object_is_empty(dataset):
    r = _client(dataset, "[1, 2]").get("/api/hazards")
    assert r.status_code == 200 and r.json()["features"] == []


def test_hazards_drops_invalid_features(dataset):
    bad_geom = _feature(id="line")
    bad_geom["geometry"] = {"type": "LineString", "coordinates": [[17.0, 50.0], [17.1, 50.1]]}
    bad_kind = _feature(id="kind", kind="wrak")
    missing = _feature(id="noz")
    del missing["properties"]["z"]
    bad_z = _feature(id="nan", z="wysoko")
    out_of_range = _feature(id="far")
    out_of_range["geometry"]["coordinates"] = [200.0, 50.0]
    bad_url = _feature(id="js", source_url="javascript:alert(1)")
    r = _client(dataset, _fc(_feature(id="ok"), bad_url, bad_geom, bad_kind, missing, bad_z, out_of_range, "śmieć", None)).get("/api/hazards")
    assert r.status_code == 200
    assert [f["properties"]["id"] for f in r.json()["features"]] == ["ok"]
    assert r.json()["source"] == "Źródło testowe"


def test_hazards_duplicate_id_keeps_first_and_warns(dataset, caplog):
    with caplog.at_level("WARNING"):
        r = _client(dataset, _fc(_feature(id="a", name="Pierwsza"), _feature(id="a", name="Druga"), _feature(id="b"))).get("/api/hazards")
    assert [(f["properties"]["id"], f["properties"]["name"]) for f in r.json()["features"]] == [("a", "Pierwsza"), ("b", "X")]
    assert "powtórzone id" in caplog.text


def test_hazards_source_url_is_constant(dataset):
    r = _client(dataset, _fc(_feature(id="a", source_url="https://example.org/x"))).get("/api/hazards")
    assert r.json()["source_url"] == "https://kz.nysa.pl/jezioro-nyskie/locja/"
