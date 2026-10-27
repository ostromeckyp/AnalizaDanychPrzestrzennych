"""Reguła stref głębokości (brief §6.4) i podsumowanie powierzchni.

Co robi: dla poziomu wody h, zanurzenia d i zapasu m klasyfikuje każdy piksel modelu na strefę
  bezpieczną / ryzykowną / zbyt płytką (danger) oraz liczy powierzchnie stref w km².
Dlaczego tak: reguła musi istnieć w JEDNYM miejscu - korzystają z niej /api/zones, /api/point i
  podsumowanie, więc nie mogą się rozjechać. Dno znamy tylko jako przedział [z_min, z_max], stąd dwie
  głębokości: D_lo = h − z_max (najpłycej) i D_hi = h − z_min (najgłębiej). Granice ±∞ (zawsze woda /
  zawsze ląd) działają bez specjalnych przypadków. Zbyt płytka wygrywa przy sprzeczności.
Wejście → wyjście: h, d, m + z_lo, z_hi, in_model → tablica uint8 (0 poza modelem, 1 safe, 2 risk,
  3 danger); klasy + h → słownik powierzchni i udziałów w akwenie; klasy + siatka → GeoJSON stref
  (EPSG:4326, max. 3 obiekty: safe, risk, danger).
Jak to obronić: zbyt płytka D_hi < d (w tym ląd); bezpieczna D_lo ≥ d + m − 1e-6 (tolerancja na
  zaokrąglenia zmiennoprzecinkowe, równość = bezpiecznie); ryzykowna to reszta. Parametry zaokrąglamy
  do 0,05 m, więc klucz cache i wynik są spójne. Piksel 10 m × 10 m = 1e-4 km².
"""
import geopandas as gpd
import numpy as np
import shapely
from affine import Affine
from rasterio import features
from shapely.geometry import shape
from shapely.validation import make_valid

NONE, SAFE, RISK, DANGER = 0, 1, 2, 3
ZONE_NAMES = {1: "safe", 2: "risk", 3: "danger"}
PIXEL_KM2 = 1e-4        # piksel 10 m × 10 m
EPS = 1e-6              # tolerancja porównania D_lo z d + m


def round_param(x: float, step: float = 0.05) -> float:
    """Zaokrągla parametr do kroku 0,05 m (potem do 2 miejsc, by pozbyć się szumu float)."""
    return round(round(x / step) * step, 2)


def zone_classes(h: float, draft: float, margin: float, z_lo: np.ndarray, z_hi: np.ndarray,
                 in_model: np.ndarray) -> np.ndarray:
    """Klasyfikuje piksele wg reguły §6.4; poza modelem (in_model False) zwraca NONE."""
    with np.errstate(invalid="ignore"):          # NaN poza modelem: porównania maskujemy in_model
        D_lo = h - z_hi                          # głębokość w najpłytszym wariancie dna
        D_hi = h - z_lo                          # głębokość w najgłębszym wariancie dna
        too_shallow = D_hi < draft
        safe = D_lo >= draft + margin - EPS
    classes = np.full(np.shape(z_lo), RISK, dtype=np.uint8)
    classes[safe] = SAFE
    classes[too_shallow] = DANGER                # przy sprzeczności wygrywa zbyt płytka
    classes[~np.asarray(in_model, bool)] = NONE
    return classes


def zone_stats(classes: np.ndarray, h: float, z_lo: np.ndarray, in_model: np.ndarray) -> dict:
    """Powierzchnie stref [km²] i udział [%] pikseli akwenu (in_model & h > z_lo) w każdej strefie; suma = 100."""
    with np.errstate(invalid="ignore"):
        water = np.asarray(in_model, bool) & (h > z_lo)
    water_km2 = float(water.sum()) * PIXEL_KM2
    out = {"water_km2": water_km2}
    for code, name in ZONE_NAMES.items():
        km2 = float((classes == code).sum()) * PIXEL_KM2   # cały model, ląd wliczony do danger
        out[f"{name}_km2"] = km2
        in_water_km2 = float(((classes == code) & water).sum()) * PIXEL_KM2
        out[f"{name}_pct"] = in_water_km2 / water_km2 * 100.0 if water_km2 > 0 else 0
    return out


def zone_warnings(h: float, draft: float, margin: float, products) -> list[str]:
    """Ostrzeżenia dla frontu: h poza zakresem obserwacji i dna poniżej obserwowanego."""
    warnings = []
    if not (products.meta["h_min_obs"] <= h <= products.meta["h_max_obs"]):
        warnings.append("h_out_of_range")
    if h - draft - margin < products.z_max_floor:
        warnings.append("below_observed_bottom")
    return warnings


def zones_geojson(classes: np.ndarray, transform: Affine, crs: str, simplify_m: float = 5.0) -> dict:
    """Wektoryzuje raster klas do FeatureCollection w EPSG:4326 (jeden obiekt na obecną strefę).

    Kolejność kroków: poligonizacja (łączność 4) → scalenie po strefie → uproszczenie w metrach
    (CRS siatki, EPSG:2180) → reprojekcja do 4326 → siatka współrzędnych 1e-6°. Uproszczenie i
    zaokrąglenie mogą dać niepoprawną geometrię, więc na końcu `make_valid`.
    """
    mask = classes > 0
    if not mask.any():
        return {"type": "FeatureCollection", "features": []}
    rows = [{"geometry": shape(geom), "zone": ZONE_NAMES[int(value)]}
            for geom, value in features.shapes(classes.astype(np.uint8), mask=mask,
                                               transform=transform, connectivity=4)]
    gdf = gpd.GeoDataFrame(rows, crs=crs).dissolve("zone")
    gdf["geometry"] = gdf.simplify(simplify_m, preserve_topology=True)
    gdf = gdf.to_crs(4326)
    gdf["geometry"] = [make_valid(shapely.set_precision(g, 1e-6)) for g in gdf.geometry]
    gdf = gdf.reset_index()
    gdf["order"] = gdf["zone"].map(["safe", "risk", "danger"].index)
    gdf = gdf.sort_values("order").drop(columns="order")
    return gdf.__geo_interface__
