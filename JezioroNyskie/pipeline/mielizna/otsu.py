"""Próg Otsu na MNDWI: automatyczny podział woda/ląd dla jednej sceny."""
import numpy as np


def otsu_threshold(mndwi: np.ndarray, aoi: np.ndarray) -> float:
    """Próg Otsu MNDWI liczony na pikselach `aoi` (skończonych).

    Co robi: zwraca wartość MNDWI rozdzielającą dwa mody histogramu (woda / ląd).
    Dlaczego tak: próg dopasowuje się do sceny (zamglenie, sezon), zamiast sztywnego 0; liczony
      tylko w AOI, żeby tło spoza zlewni nie przesuwało progu.
    Wejście → wyjście: MNDWI (H, W) i maska bool (H, W) → float. Wywołujący przekazuje
      `aoi & valid & ~cloud`, więc chmury i brak danych nie wchodzą do histogramu.
    Jak to obronić: Otsu maksymalizuje wariancję międzyklasową (= minimalizuje wewnątrzklasową)
      i nie ma parametrów do strojenia; wynik trafia do modelu jako `mndwi_minus_otsu`. Gdy między
      modami jest pusty przedział (wiele progów daje to samo maksimum), `skimage.threshold_otsu`
      bierze pierwszy z nich, tuż za dolnym modem; tu bierzemy środek plateau, co jest
      stabilniejsze i naturalne dla dwóch rozłącznych skupisk.
    """
    vals = mndwi[aoi & np.isfinite(mndwi)]
    counts, edges = np.histogram(vals, bins=256)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(counts)
    w1 = w0[-1] - w0
    s0 = np.cumsum(counts * centers)
    with np.errstate(divide="ignore", invalid="ignore"):
        m0, m1 = s0 / w0, (s0[-1] - s0) / w1
        var_between = w0 * w1 * (m0 - m1) ** 2
    var_between = np.nan_to_num(var_between)
    best = np.flatnonzero(var_between >= var_between.max() * (1 - 1e-9))
    return float(centers[best].mean() + (edges[1] - edges[0]) / 2)


def otsu_mask(mndwi: np.ndarray, threshold: float) -> np.ndarray:
    """Maska wody: 1 woda (MNDWI > próg), 0 ląd, 255 brak danych (NaN).

    Dlaczego tak: uint8 z jawnym nodata nie myli braku danych z lądem.
    Wejście → wyjście: MNDWI (H, W), próg → uint8 (H, W).
    Jak to obronić: to prosta reguła bazowa, z którą porównujemy model Random Forest.
    """
    out = (mndwi > threshold).astype(np.uint8)
    out[np.isnan(mndwi)] = 255
    return out
