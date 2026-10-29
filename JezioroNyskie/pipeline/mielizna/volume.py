"""Objętość z modelu dna vs tabela pojemność ↔ rzędna (KŻ/RZGW).

Co robi: z rastrów modelu (z, z_min, z_max) liczy przyrost objętości wody między dwoma poziomami i porównuje go z tabelą
  pojemności; z tabeli i części dna o znanej rzędnej szacuje średnią rzędną „rdzenia” (piksele zawsze mokre, dla których
  model zna tylko z_max).
Dlaczego tak: przyrost ΔV między h1 a h2 to całka powierzchni wody po h, więc dla h1 powyżej z_max rdzenia nie zależy od
  nieznanej głębokości rdzenia (każdy jego piksel dokłada pełne h2 − h1). To jedyny test, który obejmuje cały akwen.
  Całkowita objętość V(h) zależy już od rdzenia, więc zamiast ją „sprawdzać” odwracamy rachunek: V_tabela − V_reszta =
  objętość nad dnem rdzenia, z której wychodzi jego średnia rzędna.
Uwaga: tabela i poziomy wariantu B są w tym samym (nieznanym) układzie wysokości, a h_t sceny B pochodzi z tej tabeli,
  więc test sprawdza spójność geometrii modelu (powierzchnie z satelity) z krzywą pojemności, a nie układ wysokości.
"""
from __future__ import annotations

import numpy as np

CELL_M2 = 100.0  # piksel 10 m × 10 m


def bottom_bounds(model: dict) -> dict[str, np.ndarray]:
    """Rzędne dna do całkowania: dolna, środkowa i górna, z ±inf zamiast NaN; poza modelem NaN.

    `model` to wynik `bottom.read_model`. NaN w z_min → −inf (zawsze woda), NaN w z_max → +inf (zawsze ląd).
    Środek: z, a gdzie go brak, −inf dla zawsze mokrych i +inf dla zawsze suchych. Zwraca też maskę rdzenia `core`
    (z_min nieznane, z_max skończone) i maskę obszaru modelu `aoi`.
    """
    flags = model["flags"]
    aoi = flags != 255
    zmin = np.where(np.isnan(model["z_min"]), -np.inf, model["z_min"]).astype("float64")
    zmax = np.where(np.isnan(model["z_max"]), np.inf, model["z_max"]).astype("float64")
    core = aoi & np.isneginf(zmin) & np.isfinite(zmax)
    z = np.asarray(model["z"], dtype="float64")
    zmid = np.where(np.isfinite(z), z, np.where(core, -np.inf, np.inf))
    nan = np.full(flags.shape, np.nan)
    return {"low": np.where(aoi, zmin, nan), "mid": np.where(aoi, zmid, nan), "high": np.where(aoi, zmax, nan),
            "core": core, "aoi": aoi}


def layer_volume(zb: np.ndarray, h1: float, h2: float, cell_m2: float = CELL_M2) -> float:
    """Objętość wody między poziomami h1 < h2 [mln m³] dla rzędnych dna `zb` (±inf dozwolone, NaN pomijane).

    Piksel dokłada clip(h2 − z, 0, h2 − h1): pełną warstwę, gdy dno jest poniżej h1, nic, gdy powyżej h2.
    Niższe dno daje więcej, więc `low` daje górną, a `high` dolną granicę przyrostu.
    """
    d = np.clip(h2 - zb, 0.0, h2 - h1)
    return float(np.nansum(d) * cell_m2 / 1e6)


def volume_above(zb: np.ndarray, h: float, mask: np.ndarray, cell_m2: float = CELL_M2) -> float:
    """Objętość wody nad dnem `zb` przy poziomie h [mln m³] tylko w pikselach `mask` (zb musi być skończone w masce)."""
    return float(np.clip(h - zb[mask], 0.0, None).sum() * cell_m2 / 1e6)


def layer_table(bounds: dict, table_volume, edges) -> list[dict]:
    """ΔV warstw [edges[i], edges[i+1]] z modelu (mid i przedział low/high) vs ΔV z tabeli; `table_volume(h)` → mln m³."""
    rows = []
    for h1, h2 in zip(edges[:-1], edges[1:]):
        vt = float(table_volume(h2) - table_volume(h1))
        mid = layer_volume(bounds["mid"], h1, h2)
        rows.append({"h1": float(h1), "h2": float(h2), "dv_table": vt, "dv_model": mid,
                     "dv_model_min": layer_volume(bounds["high"], h1, h2),
                     "dv_model_max": layer_volume(bounds["low"], h1, h2),
                     "ratio": mid / vt if vt > 0 else None,
                     "area_table_km2": vt / (h2 - h1), "area_model_km2": mid / (h2 - h1)})
    return rows


def core_bottom(bounds: dict, h: float, v_table: float, cell_m2: float = CELL_M2) -> dict:
    """Średnia rzędna dna rdzenia wynikająca z tabeli: h − (V_tabela − V_reszta) / A_rdzenia.

    V_reszta liczymy po pikselach ze skończonym `mid` (dno znane); piksele zawsze suche (+inf) nic nie dokładają.
    """
    core = bounds["core"]
    known = bounds["aoi"] & np.isfinite(bounds["mid"])
    a_core = core.sum() * cell_m2 / 1e6
    v_rest = volume_above(bounds["mid"], h, known, cell_m2)
    v_core = v_table - v_rest
    return {"h": float(h), "v_table": float(v_table), "v_rest": v_rest, "v_core": float(v_core),
            "area_core_km2": float(a_core), "mean_depth_core": float(v_core / a_core),
            "z_core_mean": float(h - v_core / a_core)}
