"""Tabela pojemność ↔ rzędna zwierciadła wody z mapki KŻ Nysa."""
from pathlib import Path

import numpy as np
import pandas as pd

from mielizna.config import data_path


def load_table(path: Path | None = None) -> pd.DataFrame:
    """Wczytuje tabelę (kolumny pojemnosc_mln_m3, rzedna_m_npm)."""
    return pd.read_csv(path or data_path("reference", "kz_pojemnosc_rzedna.csv"))


def capacity_to_level(v_mln_m3, *, table: pd.DataFrame | None = None):
    """Pojemność [mln m³] -> rzędna [m n.p.m.]; interpolacja liniowa, poza tabelą NaN.

    `table` (opcjonalnie) to gotowa tabela z `load_table`; domyślnie czytana z pliku.
    """
    t = load_table() if table is None else table
    return np.interp(v_mln_m3, t.pojemnosc_mln_m3, t.rzedna_m_npm, left=np.nan, right=np.nan)


def level_to_capacity(h, *, table: pd.DataFrame | None = None):
    """Rzędna [m n.p.m.] -> pojemność [mln m³]; odwrotność capacity_to_level, poza tabelą NaN.

    `table` (opcjonalnie) to gotowa tabela z `load_table`; domyślnie czytana z pliku.
    """
    t = load_table() if table is None else table
    return np.interp(h, t.rzedna_m_npm, t.pojemnosc_mln_m3, left=np.nan, right=np.nan)
