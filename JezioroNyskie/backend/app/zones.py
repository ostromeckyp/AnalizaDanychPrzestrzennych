"""Reguła stref głębokości (brief §6.4) i podsumowanie powierzchni.

Co robi: dla poziomu wody h, zanurzenia d i zapasu m klasyfikuje każdy piksel modelu na strefę
  bezpieczną / ryzykowną / zbyt płytką (danger) oraz liczy powierzchnie stref w km².
Dlaczego tak: reguła musi istnieć w JEDNYM miejscu - korzystają z niej /api/zones, /api/point i
  podsumowanie, więc nie mogą się rozjechać. Dno znamy tylko jako przedział [z_min, z_max], stąd dwie
  głębokości: D_lo = h − z_max (najpłycej) i D_hi = h − z_min (najgłębiej). Granice ±∞ (zawsze woda /
  zawsze ląd) działają bez specjalnych przypadków. Zbyt płytka wygrywa przy sprzeczności.
Wejście → wyjście: h, d, m + z_lo, z_hi, in_model → tablica uint8 (0 poza modelem, 1 safe, 2 risk,
  3 danger); klasy + h → słownik powierzchni i udziałów w akwenie.
Jak to obronić: zbyt płytka D_hi < d (w tym ląd); bezpieczna D_lo ≥ d + m − 1e-6 (tolerancja na
  zaokrąglenia zmiennoprzecinkowe, równość = bezpiecznie); ryzykowna to reszta. Parametry zaokrąglamy
  do 0,05 m, więc klucz cache i wynik są spójne. Piksel 10 m × 10 m = 1e-4 km².
"""
import numpy as np

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
    """Powierzchnie stref [km²] i ich udział [%] w akwenie (akwen = in_model & h > z_lo)."""
    with np.errstate(invalid="ignore"):
        water = np.asarray(in_model, bool) & (h > z_lo)
    water_km2 = float(water.sum()) * PIXEL_KM2
    out = {"water_km2": water_km2}
    for code, name in ZONE_NAMES.items():
        km2 = float((classes == code).sum()) * PIXEL_KM2   # cały model, ląd wliczony do danger
        out[f"{name}_km2"] = km2
        out[f"{name}_pct"] = km2 / water_km2 * 100.0 if water_km2 > 0 else 0
    return out


def zone_warnings(h: float, draft: float, margin: float, products) -> list[str]:
    """Ostrzeżenia dla frontu: h poza zakresem obserwacji i dna poniżej obserwowanego."""
    warnings = []
    if not (products.meta["h_min_obs"] <= h <= products.meta["h_max_obs"]):
        warnings.append("h_out_of_range")
    if h - draft - margin < products.z_max_floor:
        warnings.append("below_observed_bottom")
    return warnings
