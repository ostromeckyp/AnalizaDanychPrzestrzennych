import pytest

from app.settings import get_settings


def test_meta_accuracy_from_eval_files(client):
    m = client.get("/api/meta").json()
    a = m["accuracy"]
    assert a["bottom_rmse_nmt"] == 1.5 and a["bottom_bias_nmt"] == 1.1
    assert a["bottom_in_bounds_nmt"] is None          # blok zbiorczy modelu all nie ma share_in_bounds
    assert a["levels_mae_ab"] == 0.47 and a["variant_d_within_0_2"] == 0.47
    assert a["kz_rmse"] is None and a["kz_bias"] is None   # brak kz_compare.json
    assert m["model_period"] == "all" and m["model_period_reason"] == "powód all"


def test_meta_accuracy_nulls_without_eval_files(client_no_eval):
    a = client_no_eval.get("/api/meta").json()["accuracy"]
    assert a["bottom_rmse_nmt"] is None and a["levels_mae_ab"] is None and a["variant_d_within_0_2"] is None
    assert a["rf_oa"] > 0
    m = client_no_eval.get("/api/meta").json()
    assert m["model_period"] == "all" and m["model_period_reason"]


def test_kz_compare_read_when_present(dataset):
    import json
    from fastapi.testclient import TestClient
    from app.data import load_products
    from app.main import create_app
    from app.settings import Settings
    (dataset / "processed" / "eval" / "kz_compare.json").write_text(
        json.dumps({"points": {"rmse": 0.6, "bias": -0.2}}), encoding="utf-8")
    c = TestClient(create_app(Settings(data_dir=dataset, live=False), load_products(dataset, "all")))
    a = c.get("/api/meta").json()["accuracy"]
    assert a["kz_rmse"] == 0.6 and a["kz_bias"] == -0.2


def test_period_from_model_choice(tmp_path, monkeypatch):
    from conftest import write_eval
    write_eval(tmp_path, "post_flood")
    monkeypatch.setenv("MIELIZNA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MIELIZNA_PERIOD", raising=False)
    assert get_settings().period == "post_flood"
    monkeypatch.setenv("MIELIZNA_PERIOD", "pre_flood")       # zmienna środowiskowa wygrywa
    assert get_settings().period == "pre_flood"


def test_period_default_without_model_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("MIELIZNA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MIELIZNA_PERIOD", raising=False)
    assert get_settings().period == "all"


def _client(dataset):
    from fastapi.testclient import TestClient
    from app.data import load_products
    from app.main import create_app
    from app.settings import Settings
    return TestClient(create_app(Settings(data_dir=dataset, live=False), load_products(dataset, "all")))


def test_meta_etag_changes_with_eval_content(dataset):
    import json
    etag1 = _client(dataset).get("/api/meta").headers["etag"]
    (dataset / "processed" / "eval" / "kz_compare.json").write_text(
        json.dumps({"points": {"rmse": 0.6, "bias": -0.2}}), encoding="utf-8")
    assert _client(dataset).get("/api/meta").headers["etag"] != etag1


def test_gravel_etag_changes_with_file(dataset):
    from conftest import write_gravel
    e1 = _client(dataset).get("/api/gravel").headers["etag"]
    import geopandas as gpd
    from shapely.geometry import box
    f = dataset / "reference" / "zwirownia.gpkg"
    gpd.GeoDataFrame({"source": ["x"]}, geometry=[box(375000, 289900, 375010, 289910)], crs="EPSG:2180").to_file(f, driver="GPKG")
    assert _client(dataset).get("/api/gravel").headers["etag"] != e1


@pytest.mark.parametrize("body", ["null", "[]", '"x"', "12", "{bad json", '{"all": null}', '{"all": []}'])
def test_meta_survives_malformed_eval_files(dataset, body):
    for name in ("bottom_vs_nmt", "levels", "model_choice", "variant_d", "kz_compare", "bottom_change"):
        (dataset / "processed" / "eval" / f"{name}.json").write_text(body, encoding="utf-8")
    r = _client(dataset).get("/api/meta")
    assert r.status_code == 200
    a = r.json()["accuracy"]
    assert a["bottom_rmse_nmt"] is None and a["levels_mae_ab"] is None and a["kz_rmse"] is None
    assert r.json()["model_period_reason"]


def test_period_reason_default_vs_override(client_no_eval, dataset):
    assert client_no_eval.get("/api/meta").json()["model_period_reason"] == "Domyślny okres modelu (brak decyzji oceny zmian dna)."
    import json
    (dataset / "processed" / "eval" / "model_choice.json").write_text(json.dumps({"period": "post_flood", "reason": "r"}), encoding="utf-8")
    assert _client(dataset).get("/api/meta").json()["model_period_reason"].startswith("Okres modelu ustawiony ręcznie")
