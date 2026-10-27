"""Testy na prawdziwych produktach pipeline'u (`data/processed/`), marker `real`.

Co robi: sprawdza liczby z planu 1 (meta), czas zimnego `/api/zones`, pole bezpiecznej strefy
  i budowę `SceneContext` (której nie ćwiczą testy jednostkowe).
Dlaczego tak: syntetyczny zbiór 20×30 px nie wykryje błędu siatki, wydajności ani rozjazdu liczb.
Wejście → wyjście: `data/processed/model/all/` → asercje; brak modelu = cały moduł pominięty.
Jak to obronić: świeża aplikacja na test (pusty cache TTL) mierzy najgorszy przypadek, a przedział
  `safe_km2` pochodzi z ledgera planu 1 (128 908 px przed R25, R25 może tylko zmniejszyć).
"""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mielizna.grid import reference_grid
from mielizna.osm import lake_mask

from app.current import SceneContext
from app.data import load_products
from app.main import create_app
from app.settings import Settings

DATA = Path(__file__).resolve().parents[2] / "data"

pytestmark = [pytest.mark.real,
              pytest.mark.skipif(not (DATA / "processed" / "model" / "all" / "model_meta.json").exists(),
                                 reason="brak data/processed/model/all/")]


@pytest.fixture(scope="module")
def real_products():
    return load_products(DATA, "all")


@pytest.fixture
def real_client(real_products):
    """Świeża aplikacja na każdy test: pusty cache TTL = zimny start."""
    return TestClient(create_app(Settings(data_dir=DATA, live=False), real_products))


def test_zones_under_one_second_cold(real_client):
    t = time.perf_counter()
    r = real_client.get("/api/zones", params={"h": 195.5, "draft": 1.0, "margin": 0.3})
    dt = time.perf_counter() - t
    print(f"\n/api/zones cold: {dt:.3f} s")
    assert r.status_code == 200 and dt < 1.0          # brief M5


def test_real_meta_numbers(real_client):
    m = real_client.get("/api/meta").json()
    assert m["n_scenes"] == 218 and m["h_min_obs"] == 192.9 and m["z_max_floor"] == pytest.approx(193.05)
    assert m["model_version"].endswith("311e18c951a8")


def test_safe_area_matches_plan1(real_client, real_products):
    s = real_client.get("/api/zones", params={"h": 195.5, "draft": 1.0, "margin": 0.0}).json()["stats"]
    print(f"\nsafe_km2 (cały model) = {s['safe_km2']}")
    # Ledger planu 1 (w. 133) liczył 128 908 px w obrębie jeziora OSM (lake.gpkg) przed R25; R25 może tylko
    # zmniejszyć. API liczy cały model (AOI), a ~1000 px bezpiecznej strefy leży poza obrysem OSM.
    lake = lake_mask(reference_grid(), path=DATA / "processed" / "lake.gpkg")
    in_lake_km2 = float(((real_products.z_hi <= 195.5 - 1.0 + 1e-6) & lake).sum()) * 1e-4
    print(f"safe_km2 (w obrysie jeziora) = {in_lake_km2}")
    assert 12.70 <= in_lake_km2 <= 12.891
    assert s["safe_km2"] >= in_lake_km2 and s["safe_km2"] - in_lake_km2 < 0.15   # reszta: woda poza obrysem OSM


def test_scene_context_builds_on_real_data(real_products):
    ctx = SceneContext.build(real_products, DATA)
    assert ctx.grid.transform == real_products.transform and ctx.lake.shape == tuple(real_products.shape)
    assert ctx.bundle and ctx.lake.any() and ctx.aoi.any()
