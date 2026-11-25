"""Zapytanie punktowe (popup na mapie): cztery warianty - model, zawsze woda, ląd, poza modelem.

Co robi: dla współrzędnych lon/lat i parametrów h / draft / margin znajduje piksel modelu i zwraca
  głębokość, prześwit względem zanurzenia, strefę oraz wartości dna (z_min, z_max, z, unc).
Dlaczego tak: strefa pochodzi z `depth.classify` liczonego na tablicach 1×1, więc to ta sama
  reguła co w `/api/zones` (jedno źródło prawdy, spec §4). Liczby nieskończone (zawsze woda → brak
  górnej głębokości, zawsze ląd → brak górnej rzędnej dna) oddajemy jako `None`, bo JSON nie zna ∞.
Wejście → wyjście: `point_info(products, lon, lat, h, draft, margin)` → słownik zgodny z `PointResponse`.
  Wariant (kolejno): poza siatką lub poza modelem → `outside`; h ≤ z_lo → `land`; z_lo = −∞ →
  `always_water`; inaczej `model`. Pola `bottom_source`, `kz_conflict`, `kz_interp` mówią, czy dno piksela
  pochodzi z mapy KŻ (`kz_interp` = p5/p95 błędu interpolacji), czy KŻ przeczy satelicie. `z_max_sat` to surowa
  górna granica satelity (przed kalibracją); `z_max` to granica serwowana (po kalibracji, gdy wczytano rastry łączone).
  `kz_nearest` = najbliższy punkt mapy KŻ dla „zawsze woda” z dnem satelitarnym, bez sprzeczności z KŻ, poza żwirownią
  (tylko informacja).
Jak to obronić: D_lo = h − z_hi (najpłycej), D_hi = h − z_lo (najgłębiej); prześwit to głębokość minus
  zanurzenie. Piksel wybiera `rasterio.transform.rowcol` na współrzędnych siatki (EPSG:2180).
"""
import math
import threading

import numpy as np
import rasterio.transform
from pyproj import Transformer

from app.data import Products
from app.depth import SOURCE_KZ, Bounds, classify, depth_range, point_kind
from app.zones import ZONE_NAMES


_local = threading.local()


def _to_grid(crs: str) -> Transformer:
    """Transformer EPSG:4326 → układ siatki, tworzony raz na wątek (budowa jest droga, a `Transformer` nie jest wątkowo-bezpieczny)."""
    cache = _local.__dict__.setdefault("t", {})
    if crs not in cache:
        cache[crs] = Transformer.from_crs(4326, crs, always_xy=True)
    return cache[crs]


def _r(x) -> float | None:
    """Liczba skończona zaokrąglona do 2 miejsc albo None (∞, NaN)."""
    if x is None:
        return None
    x = float(x)
    return round(x, 2) if math.isfinite(x) else None


def _pixel(products: Products, lon: float, lat: float) -> tuple[int, int] | None:
    """Wiersz i kolumna piksela dla lon/lat albo None, gdy punkt leży poza siatką."""
    x, y = _to_grid(products.crs).transform(lon, lat)
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    row, col = rasterio.transform.rowcol(products.transform, x, y)
    h_px, w_px = products.shape
    return (int(row), int(col)) if 0 <= row < h_px and 0 <= col < w_px else None


def in_gravel(products: Products, lon: float, lat: float) -> bool:
    """Czy punkt leży w obrysie żwirowni (dno zmienne, model może być nieaktualny); False, gdy brak pliku obrysu."""
    if products.gravel_geom is None:
        return False
    from shapely.geometry import Point
    x, y = _to_grid(products.crs).transform(lon, lat)
    return bool(math.isfinite(x) and math.isfinite(y) and products.gravel_geom.contains(Point(x, y)))


def nearest_kz_spot(products: Products, lon: float, lat: float) -> dict | None:
    """Najbliższy punkt rzędnej mapy KŻ do lon/lat: {"z", "distance_m"} albo None (brak punktów). Tylko informacja."""
    spots = products.kz_spots
    if spots is None or not len(spots):
        return None
    x, y = _to_grid(products.crs).transform(lon, lat)
    d = np.hypot(spots[:, 0] - x, spots[:, 1] - y)
    i = int(np.argmin(d))
    return {"z": round(float(spots[i, 2]), 2), "distance_m": round(float(d[i]), 1)}


def point_info(products: Products, lon: float, lat: float, h: float, draft: float, margin: float) -> dict:
    out = {"kind": "outside", "lon": lon, "lat": lat, "h": h, "draft": draft, "margin": margin,
           "zone": None, "depth_min": None, "depth_max": None, "clearance_min": None,
           "clearance_max": None, "z_min": None, "z_max": None, "z": None, "unc": None,
           "bottom_above_water_min": None, "bottom_above_water_max": None, "obs_count": None,
           "gravel": in_gravel(products, lon, lat),
           "bottom_source": "satellite", "kz_conflict": False, "kz_interp": None, "z_max_sat": None,
           "kz_nearest": None}
    px = _pixel(products, lon, lat)
    if px is None:
        return out
    r, c = px
    if not products.in_model[r, c]:
        return out          # poza modelem obs_count zostaje None (0 i 65535 to wartości wartownicze)
    out["obs_count"] = int(products.obs_count[r, c])

    z_lo, z_hi = float(products.z_lo[r, c]), float(products.z_hi[r, c])
    one = Bounds.from_arrays([[z_lo]], [[z_hi]], [[True]])
    if products.bounds.source[r, c] == SOURCE_KZ:       # dno z mapy KŻ: podajemy też parametry interpolacji (p5, p95)
        out.update(bottom_source="kz", kz_interp=products.kz_interp)
    out["kz_conflict"] = bool(products.bounds.kz_conflict[r, c])
    out["zone"] = ZONE_NAMES[int(classify(h, draft, margin, one)[0, 0])]
    out["kind"] = point_kind(h, z_lo)

    d_lo, d_hi = (float(v[0, 0]) for v in depth_range(h, one.z_lo, one.z_hi))
    out.update(depth_min=_r(max(d_lo, 0.0)), depth_max=_r(d_hi),
               clearance_min=_r(d_lo - draft), clearance_max=_r(d_hi - draft),
               z_min=_r(z_lo), z_max=_r(z_hi), z=_r(products.z[r, c]), unc=_r(products.unc[r, c]))
    if products.z_hi_sat is not None:                  # surowa górna granica satelity (przed kalibracją), np. „zawsze woda"
        out["z_max_sat"] = _r(products.z_hi_sat[r, c])
    if (out["kind"] == "always_water" and out["bottom_source"] == "satellite" and not out["kz_conflict"]
            and not out["gravel"]):                                 # poza zasięgiem interpolacji KŻ (sprzeczność jest w zasięgu)
        out["kz_nearest"] = nearest_kz_spot(products, lon, lat)     # tylko informacja, strefy jej nie używają
    if out["kind"] == "land":
        out.update(bottom_above_water_min=_r(z_lo - h), bottom_above_water_max=_r(z_hi - h))
    return out
