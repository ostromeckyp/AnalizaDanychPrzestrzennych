"""Wczytanie produktów pipeline'u do pamięci przy starcie backendu.

Co robi: czyta rastry modelu dna, sceny, linie brzegowe, przystanie, krzywą powierzchnia↔poziom i
  metryki RF; wylicza pochodne (granice z ±∞, maska modelu, NPP i Max PP).
Dlaczego tak: model jest mały (kilka rastrów), a każde zapytanie o strefy to czysta arytmetyka na
  tablicach - trzymanie w RAM jest najprostsze i najszybsze. NaN w z_min znaczy „zawsze woda" (−∞),
  NaN w z_max „zawsze ląd" (+∞) - zgodnie z `meta["nan_semantics"]`; poza modelem zostaje NaN.
  NPP i Max PP liczymy z tabeli KŻ (`mielizna.capacity`), by była jedna implementacja interpolacji.
Wejście → wyjście: katalog danych + okres → `Products`. Do sceny wchodzą tylko `qc_ok` z `h_t`
  (scena z qc_ok False nie publikuje poziomu, powierzchni ani linii brzegowej).
Jak to obronić: „poza modelem" = obs_count 0 lub 65535 lub flags 255; bit 8 flag jest opisowy i
  nie wpływa na nic. Pojemności 65,69 i 121,70 mln m³ to stałe z briefu §4 (tabela KŻ Nysa).
"""
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
from affine import Affine

from mielizna import bottom, capacity, levels
from mielizna.levels import AreaLevelCurve

NPP_MLN_M3 = 65.69      # brief §4: normalny poziom piętrzenia, tabela KŻ Nysa [mln m³]
MAX_PP_MLN_M3 = 121.70  # brief §4: maksymalny poziom piętrzenia, tabela KŻ Nysa [mln m³]
CRS = "EPSG:2180"


@dataclass
class Products:
    transform: Affine
    crs: str
    shape: tuple[int, int]
    z_lo: np.ndarray        # float64, −∞ gdzie z_min = NaN (zawsze woda), NaN poza modelem
    z_hi: np.ndarray        # float64, +∞ gdzie z_max = NaN (zawsze ląd), NaN poza modelem
    z: np.ndarray           # float32
    unc: np.ndarray         # float32
    obs_count: np.ndarray   # uint16
    in_model: np.ndarray    # bool
    meta: dict
    version: str
    scenes: list[dict]
    shorelines: gpd.GeoDataFrame
    marinas: gpd.GeoDataFrame
    curve: AreaLevelCurve
    rf_metrics: dict
    z_max_floor: float
    npp: float
    max_pp: float
    data_dir: Path          # korzeń danych (dla tabeli KŻ czytanej przez `mielizna.capacity`)


@contextmanager
def _data_dir_env(data_dir: Path):
    """Na czas bloku ustawia MIELIZNA_DATA_DIR (czyta ją `mielizna.config.data_dir`)."""
    old = os.environ.get("MIELIZNA_DATA_DIR")
    os.environ["MIELIZNA_DATA_DIR"] = str(data_dir)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("MIELIZNA_DATA_DIR", None)
        else:
            os.environ["MIELIZNA_DATA_DIR"] = old


_ENV_LOCK = threading.Lock()   # endpointy sync idą w puli wątków; env procesu jest wspólne


def capacity_to_level(p: Products, v: float) -> float:
    """Pojemność [mln m³] → rzędna [m n.p.m.] z tabeli KŻ; poza tabelą NaN (jedna implementacja interpolacji)."""
    with _ENV_LOCK, _data_dir_env(p.data_dir):
        return float(capacity.capacity_to_level(v))


def level_to_capacity(p: Products, h: float) -> float:
    """Rzędna [m n.p.m.] → pojemność [mln m³] z tabeli KŻ; poza tabelą NaN."""
    with _ENV_LOCK, _data_dir_env(p.data_dir):
        return float(capacity.level_to_capacity(h))


def load_products(data_dir: Path, period: str = "all") -> Products:
    """Wczytuje wszystkie produkty z `data_dir/processed` (okres modelu `period`)."""
    data_dir = Path(data_dir)
    proc = data_dir / "processed"
    arrays, meta = bottom.read_model(proc / "model" / period)

    import rasterio
    with rasterio.open(proc / "model" / period / "bottom_zmin.tif") as ds:
        transform, crs = ds.transform, ds.crs.to_string()

    obs, flags = arrays["obs_count"], arrays["flags"]
    in_model = ~((obs == 0) | (obs == 65535) | (flags == 255))
    z_min, z_max = arrays["z_min"].astype(np.float64), arrays["z_max"].astype(np.float64)
    z_lo = np.where(in_model, np.where(np.isnan(z_min), -np.inf, z_min), np.nan)
    z_hi = np.where(in_model, np.where(np.isnan(z_max), np.inf, z_max), np.nan)
    finite_max = z_hi[in_model & np.isfinite(z_hi)]

    scenes = [s for s in json.loads((proc / "scenes.json").read_text(encoding="utf-8"))
              if s["qc_ok"] and s["h_t"] is not None]
    scenes.sort(key=lambda s: s["date"])
    dates = {s["date"] for s in scenes}

    shorelines = gpd.read_file(proc / "shorelines.gpkg")
    shorelines = shorelines[shorelines["date"].isin(dates)].set_index("date", drop=False)
    shorelines.index.name = None
    marinas = gpd.read_file(proc / "marinas.gpkg")

    rf_metrics = json.loads((proc / "model" / "rf_metrics.json").read_text(encoding="utf-8"))
    curve = levels.load_area_level_curve(proc / "model" / "area_level_curve.json")
    with _data_dir_env(data_dir):
        npp = float(capacity.capacity_to_level(NPP_MLN_M3))
        max_pp = float(capacity.capacity_to_level(MAX_PP_MLN_M3))

    return Products(
        transform=transform, crs=crs, shape=obs.shape, z_lo=z_lo, z_hi=z_hi, z=arrays["z"],
        unc=arrays["unc"], obs_count=obs, in_model=in_model, meta=meta,
        version=f"{period}-{meta['version']}", scenes=scenes, shorelines=shorelines, marinas=marinas,
        curve=curve, rf_metrics=rf_metrics, z_max_floor=float(finite_max.min()), npp=npp, max_pp=max_pp,
        data_dir=data_dir,
    )
