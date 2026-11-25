"""Regresja ścieżki głębokości na prawdziwych danych (`data/processed/`), marker `real`.

Co robi: przelicza strefy (sha1 klas, statystyki, ostrzeżenia) i `point_info` dla zapisanych punktów
  i porównuje z `tests/fixtures/depth_baseline.json`.
Dlaczego tak: refaktor ścieżki głębokości nie może zmienić żadnego piksela; testy syntetyczne tego nie
  pokażą. Referencję wygenerował `depth_baseline.py` na kodzie sprzed refaktoru.
Wejście → wyjście: produkty z `load_products(DATA, "all")` + fixture → równość `==`; brak modelu = moduł pominięty.
Jak to obronić: ten sam kod i dane dają wynik identyczny co do bitu, więc nie potrzeba tolerancji.
"""
import json
import os
from pathlib import Path

import pytest

from depth_baseline import FIXTURE, compute_point, compute_zones
from app.data import load_products

DATA = Path(__file__).resolve().parents[2] / "data"

pytestmark = [pytest.mark.real,
              pytest.mark.skipif(not (DATA / "processed" / "model" / "all" / "model_meta.json").exists(),
                                 reason="brak data/processed/model/all/")]

BASELINE = json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def products():
    """Referencja dotyczy samego satelity: bez nadpisania z zewnątrz wyłączamy rastry łączone (`MIELIZNA_NO_KZ=1`).

    Uruchomienie z `MIELIZNA_NO_KZ=0` pokazuje, co zmienia mapa KŻ (testy mają wtedy zawieść).
    """
    mp = pytest.MonkeyPatch()
    if "MIELIZNA_NO_KZ" not in os.environ:
        mp.setenv("MIELIZNA_NO_KZ", "1")
    try:
        yield load_products(DATA, "all")
    finally:
        mp.undo()


@pytest.mark.parametrize("key", list(BASELINE["zones"]))
def test_zones_match_baseline(products, key):
    h, draft, margin = map(float, key.split("|"))
    assert compute_zones(products, h, draft, margin) == BASELINE["zones"][key]


@pytest.mark.parametrize("case", BASELINE["points"], ids=lambda c: f"{c['lon']:.5f},{c['lat']:.5f}@{c['h']}")
def test_point_info_matches_baseline(products, case):
    out = compute_point(products, case["lon"], case["lat"], case["h"], case["draft"], case["margin"])
    # pola KŻ doszły po zamrożeniu referencji; przy wyłączonym KŻ muszą mieć wartości „tylko satelita"
    new = {k: out.pop(k) for k in ("bottom_source", "kz_conflict", "kz_interp", "z_max_sat", "kz_nearest")}
    if not products.combined:           # sam satelita: surowa granica = serwowana granica
        assert new == {"bottom_source": "satellite", "kz_conflict": False, "kz_interp": None, "z_max_sat": out["z_max"],
                       "kz_nearest": None}
    assert out == case["out"]
