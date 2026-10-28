"""Układ wysokościowy: przesunięcie KRON86 -> EVRF2007 z siatek quasi-geoidy GUGiK.

Co robi: liczy w punkcie (x, y) [EPSG:2180] stałą do DODANIA do wysokości w PL-KRON86-NH, aby
  dostać wysokość w PL-EVRF2007-NH. Wartość pochodzi z różnicy dwóch siatek wysokości quasi-geoidy
  (nad elipsoidą): N_kron - N_evrf, bo H = h - N, więc H_evrf - H_kron = N_kron - N_evrf.
Dlaczego tak: LiDAR 2011 i 2017 jest w KRON86, 2022 i 2024 w EVRF2007; różnica kilkunastu
  centymetrów jest rzędu szukanych zmian poziomu wody, więc nie wolno jej pominąć ani wpisać
  z głowy. Siatki czytamy przez PROJ (vgridshift), po ID z cdn.proj.org:
    pl_gugik_geoid2011-PL-KRON86-NH.tif   (quasi-geoida PL-geoid-2011 dla KRON86)
    pl_gugik_geoid2021-PL-EVRF2007-NH.tif (quasi-geoida PL-geoid-2021 dla EVRF2007)
  Taki zestaw wskazuje brief. Uwaga: wariant z jednym modelem (oba z geoid2011) daje ok. 0,016 m
  mniej (0,175 vs 0,191 m w środku jeziora); różnica jest poniżej błędu LiDAR (0,08-0,15 m).
  Nazwy w briefie ("...NH" bez sufiksu .tif) odpowiadają plikom GeoTIFF z CDN PROJ.
Wejście → wyjście: x, y [m, EPSG:2180] + siatki w katalogu danych PROJ (pyproj.datadir lub
  katalog użytkownika) → przesunięcie [m]. Brak siatek -> GridsMissing (nic nie jest zgadywane;
  pobranie: `projsync --file pl_gugik_geoid2011-PL-KRON86-NH` albo set_network_enabled(True)).
Jak to obronić: wartość wynika z oficjalnych siatek GUGiK, nie ze stałej; test sprawdza tylko
  rząd wielkości (0,05-0,30 m), a konkretna liczba trafia do epochs.csv z uruchomienia skryptu.
"""
from functools import lru_cache

from pyproj import Transformer

GRID_KRON86 = "pl_gugik_geoid2011-PL-KRON86-NH.tif"
GRID_EVRF2007 = "pl_gugik_geoid2021-PL-EVRF2007-NH.tif"


class GridsMissing(RuntimeError):
    """Siatki quasi-geoidy GUGiK niedostępne lokalnie (ani w cache PROJ)."""


def offset_from_geoid(n_kron: float, n_evrf: float) -> float:
    """Przesunięcie [m] do dodania do H_KRON86 z wysokości quasi-geoidy obu układów w tym samym punkcie."""
    return n_kron - n_evrf


@lru_cache(maxsize=4)
def _geoid_transformer(grid: str) -> Transformer:
    """vgridshift: h elipsoidalne 0 -> +N (wysokość quasi-geoidy nad elipsoidą) dla jednej siatki."""
    try:
        return Transformer.from_pipeline(f"+proj=vgridshift +grids={grid} +multiplier=1")
    except Exception as e:  # ProjError: siatka nieznaleziona
        raise GridsMissing(f"{grid}: {e}") from e


_to_lonlat = Transformer.from_crs(2180, 4326, always_xy=True)


def geoid_height(x: float, y: float, grid: str) -> float:
    """Wysokość quasi-geoidy N [m] nad elipsoidą w (x, y) EPSG:2180 z danej siatki."""
    lon, lat = _to_lonlat.transform(x, y)
    n = _geoid_transformer(grid).transform(lon, lat, 0.0)[2]
    if n != n or abs(n) == float("inf"):  # poza zasięgiem siatki
        raise GridsMissing(f"{grid}: punkt ({x}, {y}) poza zasięgiem siatki")
    return float(n)


def kron86_to_evrf2007(x: float, y: float) -> float:
    """Przesunięcie [m] KRON86 -> EVRF2007 w punkcie (x, y) EPSG:2180."""
    return offset_from_geoid(geoid_height(x, y, GRID_KRON86), geoid_height(x, y, GRID_EVRF2007))
