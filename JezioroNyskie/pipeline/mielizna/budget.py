"""Pasma rzędnych budżetu błędu pionowego modelu dna.

Co robi: definiuje trzy pasma rzędnej dna i przypisuje do nich wartości.
Dlaczego tak: błąd modelu zależy od tego, jak głęboko leży dno, a źródła kontrolne (hold-out, LiDAR, KŻ) pokrywają różne
  zakresy, więc budżet liczymy osobno dla każdego pasma. Dolna granica pasma jest włączna: [192,9; 194,8) to jedno pasmo.
  Moduł łączy też źródła w zakres błędu pasma (`combine_band`) i liczy kontekst objętości (`volume_context`).
Wejście → wyjście: rzędne [m] → etykiety pasm; statystyki źródeł {n, mae, bias} → zakres MAE [m] i źródło dominujące.
Jak to obronić: granice są stałymi w jednym miejscu, a test sprawdza wartości na krawędziach. Zakres to min-max MAE
  źródeł z n >= MIN_N, bez uśredniania i bez odejmowania biasu; źródło z n < MIN_N zostaje w `sources` z flagą.
"""
from __future__ import annotations

import numpy as np

BANDS: dict[str, tuple[float, float]] = {
    "<192.9": (-np.inf, 192.9),
    "192.9-194.8": (192.9, 194.8),
    "194.8+": (194.8, np.inf),
}

# etykiety pasm dla użytkownika (przecinek dziesiętny, półpauza); jedno miejsce dla skryptów 12 i 13
BAND_LABELS: dict[str, str] = {
    "<192.9": "< 192,9 m",
    "192.9-194.8": "192,9–194,8 m",
    "194.8+": "≥ 194,8 m",
}


def band_of(z: np.ndarray) -> np.ndarray:
    """Etykieta pasma dla każdej rzędnej `z` [m]; pasmo = [dół, góra), więc 192,9 należy do „192.9-194.8”."""
    z = np.asarray(z, dtype="float64")
    out = np.empty(z.shape, dtype=object)
    for name, (lo, hi) in BANDS.items():
        out[(z >= lo) & (z < hi)] = name
    return out.astype(str)


MIN_N = 5  # poniżej tylu punktów MAE źródła jest anegdotą: źródło zostaje w `sources`, ale nie wchodzi do zakresu


def _usable(st: dict) -> bool:
    """Źródło ma statystykę: n > 0 i skończone MAE."""
    mae = st.get("mae")
    return bool(st.get("n", 0) > 0 and mae is not None and np.isfinite(mae))


def combine_band(sources: dict[str, dict]) -> dict:
    """Łączy źródła kontrolne jednego pasma w zakres błędu [min MAE, max MAE].

    Co robi: pomija źródła bez danych (n = 0 albo brak MAE), źródła z n < MIN_N zostawia w `sources` z
      `"excluded": "n<5"` i nie liczy ich do zakresu; z reszty bierze min i max MAE oraz nazwę źródła z max MAE.
    Dlaczego tak: pasmo widzą różne źródła (hold-out, LiDAR, KŻ); uczciwy budżet to rozrzut ich MAE, nie średnia,
      a garstka punktów nie może wyznaczać granicy zakresu.
    Wejście → wyjście: {nazwa: {n, mae, bias, ...}} → {range_m: [lo, hi] | None, dominant: nazwa | None, sources}.
    Jak to obronić: test na pustym źródle, na samych pustych i na n < 5; MAE bez odejmowania biasu.
    """
    kept = {k: dict(v) for k, v in sources.items() if _usable(v)}
    for v in kept.values():
        if v["n"] < MIN_N:
            v["excluded"] = f"n<{MIN_N}"
    ranked = {k: v for k, v in kept.items() if "excluded" not in v}
    if not ranked:
        return {"range_m": None, "dominant": None, "sources": kept}
    maes = {k: float(v["mae"]) for k, v in ranked.items()}
    return {"range_m": [min(maes.values()), max(maes.values())], "dominant": max(maes, key=maes.get), "sources": kept}


def volume_context(layers: list[dict], lo: float, hi: float) -> dict | None:
    """Stosunek objętości modelu do tabeli KŻ dla warstw leżących w całości w [lo, hi).

    Co robi: sumuje `dv_model` i `dv_table` warstw o h1 >= lo i h2 <= hi; zwraca iloraz i pokryty zakres rzędnych.
    Dlaczego tak: objętość jest kontekstem (nie źródłem zakresu w metrach); częściowo pokryte warstwy pomijamy.
    Wejście → wyjście: warstwy z volume.json, granice pasma → {ratio, covered: [h1_min, h2_max]} albo None.
    Jak to obronić: test częściowego pokrycia; brak warstw → None, nie 0 ani NaN.
    """
    sel = [la for la in layers if la["h1"] >= lo and la["h2"] <= hi]
    if not sel:
        return None
    tab = sum(la["dv_table"] for la in sel)
    if not tab:
        return None
    return {"ratio": float(sum(la["dv_model"] for la in sel) / tab),
            "covered": [min(la["h1"] for la in sel), max(la["h2"] for la in sel)]}
