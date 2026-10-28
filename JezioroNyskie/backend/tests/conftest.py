"""Mały syntetyczny zbiór danych dla testów backendu (bez sieci i bez prawdziwych danych).

Co robi: `make_dataset(root)` zapisuje w `root` strukturę `processed/` i `reference/` jak pipeline.
Dlaczego tak: ręcznie ułożone kolumny (przedział, zawsze woda, zawsze ląd, poza modelem) pozwalają
  w testach strefowych przewidzieć wynik z głowy.
Wejście → wyjście: katalog → ten sam katalog; fixtury `dataset`, `dataset_qc_false_date`, `products`.
Jak to obronić: rastry przechodzą przez prawdziwe `bottom.write_model`, więc format jest ten sam co w produkcji.
"""
import json
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import MultiLineString, Point, box

from mielizna.bottom import write_model
from mielizna.grid import Grid
from mielizna.levels import AreaLevelCurve, save_area_level_curve

from app.data import load_products

REPO_REFERENCE = Path(__file__).resolve().parents[2] / "data" / "reference" / "kz_pojemnosc_rzedna.csv"
H, W = 20, 30
QC_FALSE_DATE = "2026-10-05"


def _scenes() -> list[dict]:
    def scene(date, h, method, ok):
        return {"date": date, "tiles": "33UXR;33UXS", "h_t": h, "h_method": method, "h_source": "test",
                "h_sigma": 0.15, "h_datum": "test", "area_km2": 12.0, "area_otsu_km2": 11.8,
                "lake_nodata_pct": 0.1, "otsu_threshold": 0.1, "local_cloud_pct": 0.5,
                "capacity_mln_m3": 40.0, "qc_ok": ok, "qc_reason": "" if ok else "test"}
    return [scene("2026-10-20", 193.5, "B", True), scene(QC_FALSE_DATE, None, "B", False),
            scene("2026-09-30", 193.2, "B", True)]


GRAVEL_BOX = (375020, 289920, 375070, 289980)   # E0, N0, E1, N1 (EPSG:2180): kolumny 2-6, wiersze 2-8 siatki testowej


def write_eval(root: Path, period: str = "all") -> None:
    """Pliki oceny w kształcie produkowanym przez `pipeline/08_evaluate.py` (wartości testowe)."""
    ev = Path(root) / "processed" / "eval"
    ev.mkdir(parents=True, exist_ok=True)
    files = {
        "bottom_vs_nmt": {"by_epoch": {}, "all": {"n": 100, "mae": 1.0, "rmse": 1.5, "bias": 1.1, "note": "x"},
                          "pre_flood": {"n": 50, "mae": 0.9, "rmse": 1.2, "bias": 0.7, "share_in_bounds": 0.25}},
        "levels": {"a_vs_b": {"n": 92, "mae": 0.47, "rmse": 0.58, "bias": -0.08}},
        "bottom_change": {"share_significant": 0.015},
        "model_choice": {"period": period, "reason": f"powód {period}", "share_significant": 0.015},
        "variant_d": {"n_scenes": 107, "share_within_0_2": 0.47, "population": "h_t < h_max_valid and d_valid"},
    }
    for name, body in files.items():
        (ev / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")


def write_gravel(root: Path) -> None:
    ref = Path(root) / "reference"
    ref.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame({"name": ["rejon"], "source": ["mapa KŻ Nysa, W. Wróblewski 2023"],
                      "licence_ref": ["data/reference/KZ_ZRODLO_I_WARUNKI.md"]},
                     geometry=[box(*GRAVEL_BOX)], crs="EPSG:2180").to_file(ref / "zwirownia.gpkg", driver="GPKG")


def make_dataset(root: Path, with_eval: bool = True) -> Path:
    root = Path(root)
    proc = root / "processed"
    model = proc / "model"
    grid = Grid("EPSG:2180", Affine(10, 0, 375000, 0, -10, 290000), W, H)

    z_min = np.full((H, W), np.nan, np.float32)
    z_max = np.full((H, W), np.nan, np.float32)
    z = np.full((H, W), np.nan, np.float32)
    unc = np.full((H, W), np.nan, np.float32)
    obs = np.full((H, W), 5, np.uint16)
    flags = np.zeros((H, W), np.uint8)
    z_min[:, 0:10], z_max[:, 0:10], z[:, 0:10], unc[:, 0:10] = 193.0, 194.0, 193.5, 0.2
    z_max[:, 10:20], z[:, 10:20], unc[:, 10:20] = 193.05, 193.0, 0.3   # zawsze woda: z_min NaN
    z_min[:, 20:25], z[:, 20:25], unc[:, 20:25] = 196.0, 196.5, 0.3    # zawsze ląd: z_max NaN
    obs[:, 25:] = 0                                                    # poza modelem (kol. 28-29: obs 0 w AOI)
    aoi = np.ones((H, W), bool)
    aoi[:, 25:28] = False                                              # kol. 25-27: write_model da obs 65535, flags 255
    result = {"z_min": z_min, "z_max": z_max, "z": z, "unc": unc, "obs_count": obs,
              "n_conflict": np.zeros((H, W), np.uint16), "flags": flags}
    meta = {"version": "testver00001", "period": "all", "period_dates": ["2017-01-01", "2026-12-31"],
            "n_scenes": 3, "n_scenes_by_method": {"B": 2, "C": 1}, "h_min_obs": 192.9, "h_max_obs": 197.92}
    write_model(result, grid, model / "all", meta, aoi)

    save_area_level_curve(AreaLevelCurve([10.5, 12.0, 14.0], [192.9, 194.0, 197.0], 0.4, 10, 0.45),
                          model / "area_level_curve.json")
    metrics = {k: {"oa": 0.8, "bacc": 0.77, "kappa": 0.37, "n": 185, "n_land": 21} for k in ("rf_t", "otsu")}
    (model / "rf_metrics.json").write_text(
        json.dumps({"by_block": {"per_stratum": {"shore": metrics}}}), encoding="utf-8")
    (proc / "scenes.json").write_text(json.dumps(_scenes(), indent=1), encoding="utf-8")

    def line(dy):  # linia brzegowa wewnątrz siatki (EPSG:2180)
        return MultiLineString([[(375050, 289900 - dy), (375150, 289900 - dy)]])
    shore = gpd.GeoDataFrame(
        {"date": ["2026-09-30", "2026-10-20", QC_FALSE_DATE], "area_km2": [11.9, 12.1, 9.0],
         "lake_nodata_pct": 0.1, "otsu_threshold": 0.1, "local_cloud_pct": 0.5, "core_water_frac": 0.9,
         "rf_otsu_ratio": 1.0, "qc_ok": [True, True, False], "qc_reason": ["", "", "test"],
         "h_t": [193.2, 193.5, None], "h_method": "B"},
        geometry=[line(0), line(20), line(40)], crs="EPSG:2180")   # produkcja zapisuje też sceny QC-false
    shore.to_file(proc / "shorelines.gpkg", driver="GPKG")
    marinas = gpd.GeoDataFrame(
        {"osm_id": [1, 2], "kind": ["marina", "slipway"], "name": ["Przystań A", "Pochylnia B"]},
        geometry=[Point(375100, 289900), Point(375200, 289850)], crs="EPSG:2180")
    marinas.to_file(proc / "marinas.gpkg", driver="GPKG")

    ref = root / "reference"
    ref.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_REFERENCE, ref / REPO_REFERENCE.name)
    if with_eval:
        write_eval(root)
        write_gravel(root)
    return root


@pytest.fixture
def dataset(tmp_path) -> Path:
    return make_dataset(tmp_path)


@pytest.fixture
def dataset_qc_false_date() -> str:
    return QC_FALSE_DATE


@pytest.fixture
def products(dataset):
    return load_products(dataset, "all")


@pytest.fixture
def app(dataset, products):
    from app.main import create_app
    from app.settings import Settings
    return create_app(Settings(data_dir=dataset, live=False), products)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def dataset_no_eval(tmp_path) -> Path:
    return make_dataset(tmp_path / "no_eval", with_eval=False)


@pytest.fixture
def client_no_eval(dataset_no_eval):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.settings import Settings
    return TestClient(create_app(Settings(data_dir=dataset_no_eval, live=False), load_products(dataset_no_eval, "all")))
