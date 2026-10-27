"""Zapytanie punktowe (popup na mapie): cztery warianty - model, zawsze woda, ląd, poza modelem.

Co robi: dla współrzędnych lon/lat i parametrów h / draft / margin znajduje piksel modelu i zwraca
  głębokość, prześwit względem zanurzenia, strefę oraz wartości dna (z_min, z_max, z, unc).
Dlaczego tak: strefa pochodzi z `zones.zone_classes` liczonego na tablicach 1×1, więc to ta sama
  reguła co w `/api/zones` (jedno źródło prawdy, spec §4). Liczby nieskończone (zawsze woda → brak
  górnej głębokości, zawsze ląd → brak górnej rzędnej dna) oddajemy jako `None`, bo JSON nie zna ∞.
Wejście → wyjście: `point_info(products, lon, lat, h, draft, margin)` → słownik zgodny z `PointResponse`.
  Wariant (kolejno): poza siatką lub poza modelem → `outside`; h ≤ z_lo → `land`; z_lo = −∞ →
  `always_water`; inaczej `model`.
Jak to obronić: D_lo = h − z_hi (najpłycej), D_hi = h − z_lo (najgłębiej); prześwit to głębokość minus
  zanurzenie. Piksel wybiera `rasterio.transform.rowcol` na współrzędnych siatki (EPSG:2180).
"""
import math

import numpy as np
import rasterio.transform
from pyproj import Transformer

from app.data import Products
from app.zones import ZONE_NAMES, zone_classes


def _r(x) -> float | None:
    """Liczba skończona zaokrąglona do 2 miejsc albo None (∞, NaN)."""
    if x is None:
        return None
    x = float(x)
    return round(x, 2) if math.isfinite(x) else None


def _pixel(products: Products, lon: float, lat: float) -> tuple[int, int] | None:
    """Wiersz i kolumna piksela dla lon/lat albo None, gdy punkt leży poza siatką."""
    tr = Transformer.from_crs(4326, products.crs, always_xy=True)
    x, y = tr.transform(lon, lat)
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    row, col = rasterio.transform.rowcol(products.transform, x, y)
    h_px, w_px = products.shape
    return (int(row), int(col)) if 0 <= row < h_px and 0 <= col < w_px else None


def point_info(products: Products, lon: float, lat: float, h: float, draft: float, margin: float) -> dict:
    out = {"kind": "outside", "lon": lon, "lat": lat, "h": h, "draft": draft, "margin": margin,
           "zone": None, "depth_min": None, "depth_max": None, "clearance_min": None,
           "clearance_max": None, "z_min": None, "z_max": None, "z": None, "unc": None,
           "bottom_above_water_min": None, "bottom_above_water_max": None, "obs_count": None}
    px = _pixel(products, lon, lat)
    if px is None:
        return out
    r, c = px
    out["obs_count"] = int(products.obs_count[r, c])
    if not products.in_model[r, c]:
        return out

    z_lo, z_hi = float(products.z_lo[r, c]), float(products.z_hi[r, c])
    cls = zone_classes(h, draft, margin, np.array([[z_lo]]), np.array([[z_hi]]), np.array([[True]]))
    out["zone"] = ZONE_NAMES[int(cls[0, 0])]
    out["kind"] = "land" if h <= z_lo else "always_water" if z_lo == -math.inf else "model"

    d_lo, d_hi = h - z_hi, h - z_lo
    out.update(depth_min=_r(max(d_lo, 0.0)), depth_max=_r(d_hi),
               clearance_min=_r(d_lo - draft), clearance_max=_r(d_hi - draft),
               z_min=_r(z_lo), z_max=_r(z_hi), z=_r(products.z[r, c]), unc=_r(products.unc[r, c]))
    if out["kind"] == "land":
        out.update(bottom_above_water_min=_r(z_lo - h), bottom_above_water_max=_r(z_hi - h))
    return out
