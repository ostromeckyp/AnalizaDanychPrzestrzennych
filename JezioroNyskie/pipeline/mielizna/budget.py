"""Pasma rzędnych budżetu błędu pionowego modelu dna.

Co robi: definiuje trzy pasma rzędnej dna i przypisuje do nich wartości.
Dlaczego tak: błąd modelu zależy od tego, jak głęboko leży dno, a źródła kontrolne (hold-out, LiDAR, KŻ) pokrywają różne
  zakresy, więc budżet liczymy osobno dla każdego pasma. Dolna granica pasma jest włączna: [192,9; 194,8) to jedno pasmo.
Wejście → wyjście: rzędne [m] → etykiety pasm.
Jak to obronić: granice są stałymi w jednym miejscu, a test sprawdza wartości na krawędziach.
"""
from __future__ import annotations

import numpy as np

BANDS: dict[str, tuple[float, float]] = {
    "<192.9": (-np.inf, 192.9),
    "192.9-194.8": (192.9, 194.8),
    "194.8+": (194.8, np.inf),
}


def band_of(z: np.ndarray) -> np.ndarray:
    """Etykieta pasma dla każdej rzędnej `z` [m]; pasmo = [dół, góra), więc 192,9 należy do „192.9-194.8”."""
    z = np.asarray(z, dtype="float64")
    out = np.empty(z.shape, dtype=object)
    for name, (lo, hi) in BANDS.items():
        out[(z >= lo) & (z < hi)] = name
    return out.astype(str)
