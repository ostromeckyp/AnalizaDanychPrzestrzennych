"""Testy na prawdziwych produktach pipeline'u (`data/processed/`), marker `real`.

Co robi: sprawdza liczby z planu 1 (meta), czas zimnego `/api/zones`, pole bezpiecznej strefy
  i budowę `SceneContext` (której nie ćwiczą testy jednostkowe).
Dlaczego tak: syntetyczny zbiór 20×30 px nie wykryje błędu siatki, wydajności ani rozjazdu liczb.
Wejście → wyjście: `data/processed/model/all/` → asercje; brak modelu = cały moduł pominięty.
Jak to obronić: świeża aplikacja na test (pusty cache TTL) mierzy najgorszy przypadek, a przedział
  `safe_km2` pochodzi z ledgera planu 1 (z zapasem m = 0,3: 128 908 px przed R25, 128 901 px po R25; bez zapasu 129 880 px).
"""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
    assert m["model_version"].endswith("45a102652c33")


def test_safe_area_matches_plan1(real_client):
    # Ledger planu 1 liczył z zapasem m = 0,3 w całym modelu: 128 908 px przed R25, 128 901 px po R25 (12,890 km²).
    q = {"h": 195.5, "draft": 1.0}
    s = real_client.get("/api/zones", params={**q, "margin": 0.3}).json()["stats"]
    print(f"\nsafe_km2 m=0.3: {s['safe_km2']}")
    assert 12.70 <= s["safe_km2"] <= 12.90  # górna granica 12.891 -> 12.90: wariant A (plan 4) zmienił dane
    s0 = real_client.get("/api/zones", params={**q, "margin": 0.0}).json()["stats"]
    print(f"safe_km2 m=0.0: {s0['safe_km2']}")
    assert s0["safe_km2"] == pytest.approx(13.0442, abs=0.001)    # było 12.988 (129 880 px, ledger planu 1); po wariancie A (plan 4)


def test_scene_context_builds_on_real_data(real_products):
    ctx = SceneContext.build(real_products, DATA)
    assert ctx.grid.transform == real_products.transform and ctx.lake.shape == tuple(real_products.shape)
    assert ctx.bundle and ctx.lake.any() and ctx.aoi.any()
