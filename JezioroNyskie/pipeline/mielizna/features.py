"""Cechy spektralne i kontekstowe piksela dla modelu Random Forest (bez wejść „przeciekających")."""
import datetime as dt

import numpy as np
from scipy.ndimage import uniform_filter

from mielizna.s2 import BANDS

FEATURES = ["blue", "green", "red", "nir", "swir16", "swir22", "ndwi", "mndwi", "awei_sh", "awei_nsh",
            "ndvi", "mndwi_minus_otsu", "mndwi_mean3", "mndwi_std3", "doy_sin", "doy_cos"]


def _nd(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b); mianownik 0 -> NaN."""
    a, b = a.astype(np.float32), b.astype(np.float32)
    den = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / den
    out[den == 0] = np.nan
    return out


def indices(b: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Indeksy wodne i roślinne z pasm odbicia.

    Co robi: NDWI=(G−NIR)/(G+NIR), MNDWI=(G−SWIR1)/(G+SWIR1), NDVI=(NIR−R)/(NIR+R),
      AWEI_nsh=4(G−SWIR1)−(0,25·NIR+2,75·SWIR2), AWEI_sh=B+2,5·G−1,5·(NIR+SWIR1)−0,25·SWIR2.
    Dlaczego tak: MNDWI/AWEI w SWIR dobrze oddzielają wodę od zabudowy i cienia; NDVI wyłapuje
      roślinność przybrzeżną (szuwary), która maskuje płytką wodę.
    Wejście → wyjście: {pasmo: (H, W)} z kluczami BANDS → {indeks: (H, W)}; mianownik 0 → NaN,
      NaN na wejściu daje NaN na wyjściu.
    Jak to obronić: wzory standardowe z literatury (McFeeters, Xu, Feyisa); AWEI nie ma
      mianownika, więc NaN pochodzi tylko z braku danych.
    """
    g, bl, r, nir, s1, s2 = (b[k].astype(np.float32) for k in ("green", "blue", "red", "nir", "swir16", "swir22"))
    return {
        "ndwi": _nd(g, nir),
        "mndwi": _nd(g, s1),
        "ndvi": _nd(nir, r),
        "awei_nsh": 4 * (g - s1) - (0.25 * nir + 2.75 * s2),
        "awei_sh": bl + 2.5 * g - 1.5 * (nir + s1) - 0.25 * s2,
    }


def _window_stats(x: np.ndarray, size: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Średnia i odchylenie w oknie size×size z pominięciem NaN; NaN tam, gdzie sam piksel to NaN."""
    ok = np.isfinite(x)
    x0 = np.where(ok, x, 0.0).astype(np.float64)
    n = uniform_filter(ok.astype(np.float64), size, mode="constant")
    s1 = uniform_filter(x0, size, mode="constant")
    s2 = uniform_filter(x0 * x0, size, mode="constant")
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = s1 / n
        var = np.maximum(s2 / n - mean ** 2, 0.0)
    std = np.sqrt(var)
    mean[~ok], std[~ok] = np.nan, np.nan
    return mean.astype(np.float32), std.astype(np.float32)


def compute_features(b: dict[str, np.ndarray], otsu_threshold: float,
                     date: dt.date) -> dict[str, np.ndarray]:
    """Wszystkie cechy z `FEATURES` dla jednej sceny.

    Co robi: pasma + indeksy + MNDWI−próg Otsu + średnia/odchylenie MNDWI w oknie 3×3 + sezon.
    Dlaczego tak: okno 3×3 daje kontekst przestrzenny (brzeg vs wnętrze wody), a doy_sin/cos
      kodują porę roku cyklicznie (31 XII sąsiaduje z 1 I). Okno liczone dwoma `uniform_filter`
      (wartości z NaN→0 oraz maska ważności), więc średnia dotyczy tylko ważnych sąsiadów
      i jest szybka (bez `generic_filter`).
    Wejście → wyjście: pasma (H, W), próg Otsu sceny, data → {cecha: (H, W)}; NaN w pasmach
      propaguje się do cech piksela.
    Jak to obronić: żadnej cechy z NMT, częstości zalewania ani poziomu (h_t), więc model nie
      przecieka odpowiedzi; sezon i próg Otsu to jedyne informacje o scenie.
    """
    f = {k: b[k].astype(np.float32) for k in BANDS}
    f.update(indices(b))
    f["mndwi_minus_otsu"] = f["mndwi"] - np.float32(otsu_threshold)
    f["mndwi_mean3"], f["mndwi_std3"] = _window_stats(f["mndwi"])
    doy = date.timetuple().tm_yday
    shape = f["mndwi"].shape
    f["doy_sin"] = np.full(shape, np.sin(2 * np.pi * doy / 365.25), dtype=np.float32)
    f["doy_cos"] = np.full(shape, np.cos(2 * np.pi * doy / 365.25), dtype=np.float32)
    return {k: f[k] for k in FEATURES}


def stack(feats: dict[str, np.ndarray]) -> np.ndarray:
    """Cechy → tablica (H, W, len(FEATURES)) w kolejności `FEATURES`.

    Dlaczego tak: model uczy się i przewiduje na stałej kolejności kolumn; ta funkcja jest
      jedynym miejscem, które ją ustala.
    Wejście → wyjście: {cecha: (H, W)} → float32 (H, W, n_cech).
    Jak to obronić: kolejność jest sprawdzona testem, a brakująca cecha to KeyError, nie cicha zmiana.
    """
    return np.stack([feats[k] for k in FEATURES], axis=-1).astype(np.float32)
