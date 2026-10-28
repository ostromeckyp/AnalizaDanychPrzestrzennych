"""Wariant A poziomu wody: rzędna NMT wzdłuż linii brzegowej sceny.

Co robi: próbkuje NMT (LiDAR) co 5 m wzdłuż linii brzegowej z obrazu Sentinel-2 i bierze medianę
  rzędnej z punktów leżących wyraźnie ponad wodą z nalotu; wynik to `h_t` sceny, a 1,4826·MAD
  to jej niepewność `h_sigma`. Dodatkowo wybiera epokę LiDAR (z niższą wodą niż przy scenie).
Dlaczego tak: brzeg widoczny na obrazie leży na rzędnej wody z dnia zdjęcia, a NMT mówi, ile to
  metrów n.p.m. Tylko punkty > h_lidar + 0,10 m są ziemią, a nie wodą ani mokrą plażą. Mediana i MAD
  tłumią korony zapory, pomosty i trzciny; kilkanaście procent odstających nie ruszy wyniku.
  Rozłożenie po obwodzie (>= 3 z 8 sektorów kątowych wokół środka jeziora) chroni przed wynikiem
  z jednego krótkiego odcinka brzegu (np. tylko z nasypu). Wybór epoki wymaga, by woda w nalocie
  była co najmniej 0,2 m niżej niż szacowany poziom sceny (inaczej brzeg sceny leży pod wodą nalotu).
Wejście → wyjście: współrzędne punktów [m, EPSG:2180], rzędne NMT w EVRF2007, poziom wody nalotu
  (EVRF2007) → (h_t, h_sigma, n) albo None; `diagnose` zwraca też liczbę sektorów.
Jak to obronić: patrz testy; progi (150 m od zapory, 0,10 m, 50 punktów, 3 sektory) są parametrami
  funkcji; odrzucenia są zapisywane z powodem w levels_a_detail.csv, nic nie jest zgadywane.
"""
from datetime import date

import numpy as np
import pandas as pd
import rasterio
import shapely
from shapely.geometry import LineString, MultiLineString

N_SECTORS = 8
MAD_TO_SIGMA = 1.4826
DAM_BUFFER_M = 150.0
EPOCH_MARGIN_M = 0.2
# środek siatki modelu ~ środek jeziora; domyślny środek sektorów (skrypt podaje środek obrysu)
DEFAULT_CENTER = (376500.0, 289000.0)


def sample_shoreline(line, step_m: float = 5) -> np.ndarray:
    """Punkty (N, 2) co `step_m` wzdłuż linii (LineString lub MultiLineString), z końcem każdej części."""
    parts = list(line.geoms) if isinstance(line, MultiLineString) else [line]
    pts = []
    for p in parts:
        if p.length == 0:
            continue
        d = np.append(np.arange(0.0, p.length, step_m), p.length)
        pts.append(shapely.get_coordinates(shapely.line_interpolate_point(p, d)))
    return np.vstack(pts) if pts else np.empty((0, 2))


def sectors_covered(xy: np.ndarray, center=DEFAULT_CENTER) -> int:
    """Liczba z 8 sektorów kątowych wokół `center`, w których jest choć jeden punkt."""
    if len(xy) == 0:
        return 0
    ang = np.arctan2(xy[:, 1] - center[1], xy[:, 0] - center[0])
    idx = np.floor((ang + np.pi) / (2 * np.pi / N_SECTORS)).astype(int) % N_SECTORS
    return int(len(np.unique(idx)))


def diagnose(xy: np.ndarray, dem_z: np.ndarray, h_lidar: float, *, min_above: float = 0.10,
             center=DEFAULT_CENTER) -> dict:
    """Statystyki bez bramek: n, sectors, h_t, h_sigma z punktów dem_z > h_lidar + min_above."""
    xy, z = np.asarray(xy, float), np.asarray(dem_z, float)
    keep = np.isfinite(z) & (z > h_lidar + min_above)
    xy, z = xy[keep], z[keep]
    if len(z) == 0:
        return {"n": 0, "sectors": 0, "h_t": np.nan, "h_sigma": np.nan}
    med = float(np.median(z))
    return {"n": int(len(z)), "sectors": sectors_covered(xy, center), "h_t": med,
            "h_sigma": float(MAD_TO_SIGMA * np.median(np.abs(z - med)))}


def level_from_dem(xy: np.ndarray, dem_z: np.ndarray, h_lidar: float, *, min_above: float = 0.10,
                   min_n: int = 50, min_sectors: int = 3, max_sigma: float | None = None, center=DEFAULT_CENTER):
    """(h_t, h_sigma, n) z mediany i MAD; None gdy n < min_n, pokrycie < min_sectors sektorów
    albo (opcjonalnie) h_sigma >= max_sigma (kryterium M3: < 0,3 m)."""
    s = diagnose(xy, dem_z, h_lidar, min_above=min_above, center=center)
    if s["n"] < min_n or s["sectors"] < min_sectors:
        return None
    if max_sigma is not None and s["h_sigma"] >= max_sigma:
        return None
    return s["h_t"], s["h_sigma"], s["n"]


def choose_epoch(epochs: pd.DataFrame, scene_date: date, h_guess: float):
    """Epoka z `h_water_evrf` < h_guess - 0,2 najbliższa w czasie (remis: mniejszy date_span_days); inaczej None.

    Czas epoki to kolumna `date` (dla epoki o rozpiętości dat - pierwszy dzień nalotu).
    """
    if h_guess is None or not np.isfinite(h_guess):
        return None
    e = epochs[(epochs["h_water_evrf"] < h_guess - EPOCH_MARGIN_M) & epochs["date"].notna() & (epochs["date"] != "")]
    if e.empty:
        return None
    gap = (pd.to_datetime(e["date"]).dt.date.map(lambda d: abs((d - scene_date).days)))
    e = e.assign(_gap=gap, _span=e["date_span_days"].fillna(1e9)).sort_values(["_gap", "_span"], kind="stable")
    return e.iloc[0].drop(["_gap", "_span"])


class Nmt:
    """Zestaw arkuszy NMT jednej epoki wczytanych do pamięci; `sample` zwraca rzędne lub NaN (brak danych)."""

    def __init__(self, paths):
        self.tiles = []
        for p in paths:
            with rasterio.open(p) as src:
                self.tiles.append((src.read(1).astype("float64"), src.transform, src.nodata))

    def sample(self, xy: np.ndarray) -> np.ndarray:
        z = np.full(len(xy), np.nan)
        for arr, tr, nd in self.tiles:
            col, row = ~tr @ (xy[:, 0], xy[:, 1])
            col, row = np.floor(col).astype(int), np.floor(row).astype(int)
            ok = (row >= 0) & (row < arr.shape[0]) & (col >= 0) & (col < arr.shape[1]) & np.isnan(z)
            v = arr[row[ok], col[ok]]
            if nd is not None:
                v = np.where(v == nd, np.nan, v)
            z[ok] = v
        return z
