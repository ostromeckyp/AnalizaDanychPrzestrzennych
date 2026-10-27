"""Próg Otsu na MNDWI: automatyczny podział woda/ląd dla jednej sceny."""
import numpy as np
from skimage.filters import threshold_otsu

from mielizna.features import indices
from mielizna.s2 import cloud_mask, valid_mask


def otsu_threshold(mndwi: np.ndarray, aoi: np.ndarray) -> float:
    """Próg Otsu MNDWI liczony na pikselach `aoi` (skończonych).

    Co robi: zwraca wartość MNDWI rozdzielającą dwa mody histogramu (woda / ląd).
    Dlaczego tak: próg dopasowuje się do sceny (zamglenie, sezon), zamiast sztywnego 0; liczony
      tylko w AOI, żeby tło spoza zlewni nie przesuwało progu.
    Wejście → wyjście: MNDWI (H, W) i maska bool (H, W) → float. Wywołujący przekazuje
      `aoi & valid & ~cloud`, więc chmury i brak danych nie wchodzą do histogramu.
    Jak to obronić: Otsu maksymalizuje wariancję międzyklasową (= minimalizuje wewnątrzklasową)
      i nie ma parametrów do strojenia; wynik trafia do modelu jako `mndwi_minus_otsu`. To
      standardowa implementacja `skimage.filters.threshold_otsu` (256 przedziałów histogramu).
    """
    vals = mndwi[aoi & np.isfinite(mndwi)]
    if vals.size == 0:
        raise ValueError("otsu_threshold: brak ważnych pikseli w AOI")
    return float(threshold_otsu(vals))


def otsu_mask(mndwi: np.ndarray, threshold: float) -> np.ndarray:
    """Maska wody: 1 woda (MNDWI > próg), 0 ląd, 255 brak danych (NaN).

    Co robi: binaryzuje MNDWI progiem i zaznacza piksele bez wartości jako brak danych.
    Dlaczego tak: uint8 z jawnym nodata nie myli braku danych z lądem.
    Wejście → wyjście: MNDWI (H, W), próg (float) → uint8 (H, W) o wartościach {0, 1, 255}.
    Jak to obronić: to prosta reguła bazowa, z którą porównujemy model Random Forest.
    """
    out = (mndwi > threshold).astype(np.uint8)
    out[np.isnan(mndwi)] = 255
    return out


def scene_threshold(bands: dict[str, np.ndarray], scl: np.ndarray, aoi: np.ndarray) -> float:
    """Próg Otsu MNDWI sceny: `aoi & valid & ~cloud` (ta sama reguła co w 04a).

    Co robi: liczy MNDWI z pasm i zwraca próg Otsu z pikseli AOI, które są ważne i bez chmur.
    Dlaczego tak: jedna definicja dla etykiet (04a), treningu i predykcji, żeby cecha
      `mndwi_minus_otsu` nie rozjechała się między nimi.
    Wejście → wyjście: pasma {nazwa: (H, W)}, SCL (H, W), maska AOI → float.
    Jak to obronić: tylko składa przetestowane części (`indices`, `valid_mask`, `cloud_mask`).
    """
    return otsu_threshold(indices(bands)["mndwi"], aoi & valid_mask(bands, scl) & ~cloud_mask(scl))
