"""Ścieżka głębokości w jednym miejscu: granice dna → przedział głębokości → strefa → rodzaj punktu.

Co robi: zbiera w kolejności czytania cztery kroki, po których z rastrów satelitarnych dostajemy strefę
  bezpieczną / ryzykowną / zbyt płytką: (1) `satellite_bounds` - granice dna z semantyką ±∞,
  (2) `depth_range` - przedział głębokości dla poziomu h, (3) `classify` - strefa piksela,
  (4) `point_kind` - rodzaj punktu (ląd / zawsze woda / model).
Dlaczego tak: dotąd ta logika była rozrzucona po `data.py`, `zones.py` i `point.py`. Tu czyta się ją od
  góry do dołu jak opis procesu; pozostałe moduły tylko wywołują te funkcje (jedno źródło prawdy).
  `Bounds.source` i `Bounds.kz_conflict` przygotowują miejsce na granice łączone z tabelą KŻ; dla samego
  satelity `source` jest wszędzie 0, a `kz_conflict` wszędzie False.
Wejście → wyjście: z_min, z_max, obs_count, flags → `Bounds`; h + `Bounds` → przedział głębokości i klasy
  (uint8: 0 poza modelem, 1 safe, 2 risk, 3 danger).
Jak to obronić: NaN w z_min = zawsze woda (−∞), NaN w z_max = zawsze ląd (+∞), poza modelem NaN; reguła
  stref to brief §6.4, a przy sprzeczności wygrywa „zbyt płytka".
"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

NONE, SAFE, RISK, DANGER = 0, 1, 2, 3
EPS = 1e-6              # tolerancja porównania D_lo z d + m
SOURCE_SATELLITE, SOURCE_KZ = 0, 1


@dataclass
class Bounds:
    """Granice rzędnej dna piksela [m n.p.m.] razem z pochodzeniem; wszystkie tablice mają ten sam kształt."""
    z_lo: np.ndarray        # float64, −∞ = zawsze woda, NaN poza modelem
    z_hi: np.ndarray        # float64, +∞ = zawsze ląd, NaN poza modelem
    in_model: np.ndarray    # bool
    source: np.ndarray      # uint8: 0 = satelita, 1 = KŻ
    kz_conflict: np.ndarray  # bool: KŻ przeczy satelicie

    @classmethod
    def from_arrays(cls, z_lo, z_hi, in_model) -> "Bounds":
        """Granice samego satelity z gotowych tablic (dowolny kształt, np. 1×1): źródło 0, brak sprzeczności."""
        z_lo = np.asarray(z_lo, np.float64)
        return cls(z_lo=z_lo, z_hi=np.asarray(z_hi, np.float64), in_model=np.asarray(in_model, bool),
                   source=np.zeros(z_lo.shape, np.uint8), kz_conflict=np.zeros(z_lo.shape, bool))


def satellite_bounds(z_min: np.ndarray, z_max: np.ndarray, obs_count: np.ndarray, flags: np.ndarray) -> Bounds:
    """Granice dna z rastrów satelitarnych z semantyką ±∞.

    Co: piksel jest w modelu, gdy obs_count ∉ {0, 65535} i flags ≠ 255; NaN w z_min → −∞, NaN w z_max → +∞,
      poza modelem obie granice to NaN.
    Dlaczego: ±∞ pozwala klasyfikować bez przypadków szczególnych (zawsze woda / zawsze ląd).
    Przykład: z_min = NaN, z_max = 195 → z_lo = −∞, z_hi = 195; obs_count = 0 → z_lo = z_hi = NaN, in_model False.
    """
    in_model = ~((obs_count == 0) | (obs_count == 65535) | (flags == 255))
    z_min = np.asarray(z_min).astype(np.float64)
    z_max = np.asarray(z_max).astype(np.float64)
    z_lo = np.where(in_model, np.where(np.isnan(z_min), -np.inf, z_min), np.nan)
    z_hi = np.where(in_model, np.where(np.isnan(z_max), np.inf, z_max), np.nan)
    return Bounds(z_lo=z_lo, z_hi=z_hi, in_model=in_model,
                  source=np.full(z_lo.shape, SOURCE_SATELLITE, dtype=np.uint8),
                  kz_conflict=np.zeros(z_lo.shape, dtype=bool))


def depth_range(h: float, z_lo: np.ndarray, z_hi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Przedział głębokości (D_lo, D_hi) przy poziomie wody h.

    Co: D_lo = h − z_hi (najpłycej), D_hi = h − z_lo (najgłębiej).
    Dlaczego: dno znamy tylko jako przedział [z_lo, z_hi], więc głębokość też jest przedziałem.
    Przykład: h = 195, z_lo = 193, z_hi = 194 → D_lo = 1, D_hi = 2.
    """
    with np.errstate(invalid="ignore"):          # NaN poza modelem, ∞ − ∞ nie występuje (h skończone)
        return h - z_hi, h - z_lo


def classify(h: float, draft: float, margin: float, b: Bounds) -> np.ndarray:
    """Klasa strefy każdego piksela wg reguły §6.4; poza modelem NONE.

    Co: zbyt płytka (DANGER) gdy D_hi < zanurzenie; bezpieczna (SAFE) gdy D_lo ≥ zanurzenie + zapas − EPS;
      reszta ryzykowna (RISK); przy sprzeczności wygrywa DANGER.
    Dlaczego: nawet w najgłębszym wariancie dna zbyt płytko = na pewno niebezpiecznie; bezpiecznie tylko
      wtedy, gdy nawet najpłytszy wariant daje zapas.
    Przykład: h = 195, d = 1, m = 0,3, dno [193; 194] → D_lo = 1, D_hi = 2 → RISK.
    """
    D_lo, D_hi = depth_range(h, b.z_lo, b.z_hi)
    with np.errstate(invalid="ignore"):
        too_shallow = D_hi < draft
        safe = D_lo >= draft + margin - EPS
    classes = np.full(np.shape(b.z_lo), RISK, dtype=np.uint8)
    classes[safe] = SAFE
    classes[too_shallow] = DANGER
    classes[~np.asarray(b.in_model, bool)] = NONE
    return classes


def point_kind(h: float, z_lo: float) -> str:
    """Rodzaj punktu w modelu: `land`, `always_water` albo `model`.

    Co: h ≤ z_lo → ląd (dno nad wodą); z_lo = −∞ → zawsze woda; inaczej zwykły piksel modelu.
    Dlaczego: popup pokazuje inne pola dla lądu i dla piksela bez dolnej granicy dna.
    Przykład: h = 195, z_lo = 196 → `land`; z_lo = −∞ → `always_water`; z_lo = 193 → `model`.
    """
    return "land" if h <= z_lo else "always_water" if z_lo == -np.inf else "model"


def combined_bounds(sat: Bounds, kz_dir: Path) -> Bounds:
    """Granice łączone (kalibracja satelity + mapa KŻ) z `model/<okres>_kz/`; bez katalogu zwraca `sat`.

    Co: czyta `bottom_zlo.tif`, `bottom_zhi.tif` (float32, ±∞ zachowane) i `bottom_source.tif` (uint8: bit 0 =
      KŻ, bit 1 = sprzeczność). Maska modelu zostaje satelitarna.
    Dlaczego: łączenie robi pipeline (`14_kz_deep.py`); backend tylko wczytuje, więc strefy i punkt liczą
      się tą samą funkcją `classify` na innych granicach.
    Przykład: piksel z bitem 0 → `source` 1 (KŻ), z bitem 1 → `kz_conflict` True.
    """
    kz_dir = Path(kz_dir)
    if not (kz_dir / "bottom_zlo.tif").exists():
        return sat
    import rasterio
    out = []
    for name in ("bottom_zlo", "bottom_zhi", "bottom_source"):
        with rasterio.open(kz_dir / f"{name}.tif") as ds:
            out.append(ds.read(1))
    z_lo, z_hi, src = out
    if z_lo.shape != sat.z_lo.shape:
        raise ValueError(f"raster łączony {z_lo.shape} nie pasuje do siatki satelitarnej {sat.z_lo.shape}")
    return Bounds(z_lo=z_lo.astype(np.float64), z_hi=z_hi.astype(np.float64), in_model=sat.in_model,
                  source=(src & 1).astype(np.uint8), kz_conflict=(src & 2) > 0)
