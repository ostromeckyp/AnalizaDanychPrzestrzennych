"""Dym na prawdziwych rastrach łączonych (`data/processed/model/all_kz/`), marker `real`.

Co robi: wczytuje produkty z mapą KŻ (`use_kz=True`) i sprawdza spójność masek, parametry interpolacji z meta.json,
  przyrostek wersji, obrys `/api/kz-deep` i źródło dna w pikselu „zawsze woda” pokrytym mapą KŻ.
Dlaczego tak: testy syntetyczne nie wykryją rozjazdu siatki ani formatu rastrów z `14_kz_deep.py`.
Wejście → wyjście: `data/processed/model/all{,_kz}/` → asercje; brak katalogu `all_kz` = moduł pominięty.
"""
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio.transform
from fastapi.testclient import TestClient
from pyproj import Transformer

from app.data import load_products
from app.main import create_app
from app.settings import Settings

DATA = Path(__file__).resolve().parents[2] / "data"
KZ_DIR = DATA / "processed" / "model" / "all_kz"

pytestmark = [pytest.mark.real,
              pytest.mark.skipif(not (KZ_DIR / "bottom_zlo.tif").exists()
                                 or not (DATA / "processed" / "model" / "all" / "model_meta.json").exists(),
                                 reason="brak data/processed/model/all_kz/")]


@pytest.fixture(scope="module")
def kz_products():
    return load_products(DATA, "all", use_kz=True)


@pytest.fixture(scope="module")
def sat_products():
    return load_products(DATA, "all", use_kz=False)


def test_masks_consistent_with_model(kz_products):
    b = kz_products.bounds
    assert kz_products.combined
    assert not (b.source == 1)[~b.in_model].any() and not b.kz_conflict[~b.in_model].any()
    assert not (b.kz_conflict & (b.source == 1)).any()
    assert np.isnan(b.z_lo[~b.in_model]).all() and np.isnan(b.z_hi[~b.in_model]).all()
    assert not np.isnan(b.z_lo[b.in_model]).any() and not np.isnan(b.z_hi[b.in_model]).any()
    assert np.isfinite(b.z_lo[b.source == 1]).all() and np.isfinite(b.z_hi[b.source == 1]).all()


def test_interp_and_version(kz_products, sat_products):
    meta = json.loads((KZ_DIR / "meta.json").read_text(encoding="utf-8"))
    assert kz_products.kz_interp == {"p5": float(meta["p5"]), "p95": float(meta["p95"])}
    assert "-kz" in kz_products.version and kz_products.version.startswith(sat_products.version)


def test_kz_deep_layer_and_point(kz_products, sat_products):
    client = TestClient(create_app(Settings(data_dir=DATA, live=False), kz_products))
    assert len(client.get("/api/kz-deep").json()["features"]) == 1
    rows, cols = np.nonzero((kz_products.bounds.source == 1) & np.isneginf(sat_products.z_lo))
    assert len(rows), "brak pikseli „zawsze woda” z dnem z mapy KŻ"
    r, c = int(rows[len(rows) // 2]), int(cols[len(cols) // 2])
    x, y = rasterio.transform.xy(kz_products.transform, r, c)
    lon, lat = Transformer.from_crs(kz_products.crs, 4326, always_xy=True).transform(x, y)
    b = client.get("/api/point", params={"lon": lon, "lat": lat, "h": 194.5, "draft": 0.5, "margin": 0.3}).json()
    assert b["bottom_source"] == "kz" and b["kz_interp"] == kz_products.kz_interp and b["kz_nearest"] is None
    assert b["z_max_sat"] is not None                       # surowa górna granica satelity jest skończona
    assert kz_products.kz_spots is not None and len(kz_products.kz_spots) > 100
