"""Kandydaci do etykiet woda/ląd: losowanie punktów, zapis GeoPackage i maski ważności scen.

Co robi: wczytuje sceny COG, losuje punkty w trzech warstwach (`shore` do ręcznej oceny oraz
  `auto_water` / `auto_land` z etykietą automatyczną), zapisuje i wczytuje etykiety w GeoPackage
  (EPSG:2180) i wskazuje, które wiersze są ręcznymi etykietami klasowymi.
Dlaczego tak: ręczna praca idzie tylko tam, gdzie brzeg się zmienia; łatwe piksele dostają etykiety
  automatyczne. GPKG zamiast GeoJSON, bo trzyma układ EPSG:2180 i typy kolumn (ruling R2).
Wejście → wyjście: data/processed/s2/{data}.tif, częstość wody, maska jeziora, siatka →
  data/reference/labels.gpkg (kolumny `COLUMNS`); `human_class_labels` → podzbiór treningowy.
Jak to obronić: stały seed, odstęp 30 m w scenie, etykiety auto z wielu scen, a zbiór scen
  pochodzi z `s2.usable_dates` (CSV + config), nie z zawartości katalogu.
"""
import logging
from pathlib import Path
from typing import Callable

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import distance_transform_edt
from shapely.geometry import Point

from mielizna.config import data_path
from mielizna.grid import Grid
from mielizna.s2 import BANDS, cloud_mask, valid_mask

log = logging.getLogger(__name__)
LABELS_CRS = "EPSG:2180"
LAYER = "labels"
MIN_SPACING_M = 30.0
SHORE_FREQ = (0.05, 0.95)
AUTO_WATER_MIN_FREQ = 0.98
AUTO_WATER_EROSION_M = 200.0
AUTO_LAND_MIN_DIST_M = 300.0
CLASS_LABELS = ("water", "land")  # etykiety klasowe; "skip" (niepewne) nie jest klasą
HUMAN_STRATA = ("shore", "shore_low")  # warstwy ręcznie oceniane przez autora
LOW_FREQ = (0.05, 0.30)                # shore_low: rzadko mokre piksele (częstość wody)
SUSPECT_MARGIN = -0.3                  # MNDWI − Otsu poniżej tej wartości = „woda” wygląda jak ląd
COLUMNS = ["id", "date", "row", "col", "x", "y", "stratum", "label", "source", "label_v1", "review",
           "geometry"]


def load_scene(date: str, s2_dir: Path | None = None) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Wczytuje COG sceny z dnia `date`: odbicia pasm i klasyfikację SCL.

    Co robi: otwiera data/processed/s2/{date}.tif (7 pasm: 6 odbić z `BANDS` + SCL), dzieli je na
      słownik pasm i osobną macierz SCL (NaN → 0).
    Dlaczego tak: pipeline trzyma scenę jako jeden COG na datę (kolejność pasm = `BANDS`, SCL
      ostatnie), a SCL jako uint8 jest potrzebny do masek chmur i ważności.
    Wejście → wyjście: data 'YYYY-MM-DD' (opcjonalnie inny katalog) → ({pasmo: float32 (H, W)},
      SCL uint8 (H, W)).
    Jak to obronić: kolejność pasm jest ta sama co przy zapisie w 01_fetch_s2.py (`BANDS` + scl).
    """
    path = (s2_dir or data_path("processed", "s2")) / f"{date}.tif"
    with rasterio.open(path) as ds:
        arr = ds.read()
    return {b: arr[i] for i, b in enumerate(BANDS)}, np.nan_to_num(arr[len(BANDS)]).astype(np.uint8)


def load_ok_mask(date: str) -> np.ndarray:
    """Maska pikseli ważnych i bez chmur w scenie `date`.

    Co robi: wczytuje scenę i zwraca `valid_mask & ~cloud_mask` (chmury SCL z 2-px buforem
      i cieniami).
    Dlaczego tak: punkt do etykietowania ma sens tylko tam, gdzie scena naprawdę widzi
      powierzchnię; ta sama maska służy do liczenia częstości wody.
    Wejście → wyjście: data 'YYYY-MM-DD' → bool (H, W), True = piksel ważny i bez chmury.
    Jak to obronić: maski pochodzą z `s2.valid_mask` / `s2.cloud_mask`, przetestowanych osobno.
    """
    bands, scl = load_scene(date)
    return valid_mask(bands, scl) & ~cloud_mask(scl)


def human_class_labels(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Wiersze z ręczną etykietą klasową (source == "human", label ∈ `CLASS_LABELS`).

    Co robi: odfiltrowuje etykiety auto, `skip` i brak etykiety.
    Dlaczego tak: tylko decyzje człowieka o wodzie/lądzie są danymi treningowymi i liczą się do
      celu ≥150 etykiet (reguła R15); „skip” oznacza niepewność, nie klasę.
    Wejście → wyjście: GeoDataFrame etykiet → jego podzbiór wierszy (indeks zachowany).
    Jak to obronić: jedna definicja używana przez serwer, trening i walidację.
    """
    return gdf[(gdf["source"] == "human") & gdf["label"].isin(CLASS_LABELS)]


def sample_candidates(scene_dates: list[str], water_freq: np.ndarray, lake: np.ndarray, grid: Grid,
                      n_shore: int = 220, n_auto: int = 300, seed: int = 42,
                      ok_fn: Callable[[str], np.ndarray] = load_ok_mask) -> gpd.GeoDataFrame:
    """Losuje punkty do etykietowania w trzech warstwach: brzeg (do ręcznej oceny) i dwie automatyczne.

    Co robi: `shore` – piksele o częstości wody 0,05–0,95 (strefa zmienna), bez etykiety;
      `auto_water` – wnętrze jeziora ≥ 200 m od brzegu z częstością ≥ 0,98 (etykieta woda);
      `auto_land` – ≥ 300 m od jeziora z częstością 0 (etykieta ląd). Każdy punkt dostaje losową
      scenę, w której piksel jest ważny i bez chmury; punkty bliżej niż 30 m w tej samej scenie
      są odrzucane (próbujemy innej sceny, a gdy żadna nie pasuje, innego piksela).
    Dlaczego tak: ręczna praca dotyczy tylko brzegu, gdzie model się myli; łatwe piksele
      (głęboka woda, daleki ląd) dostają etykiety automatycznie, żeby RF widział też „oczywiste”
      przypadki. Losowa scena rozkłada punkty po sezonach i poziomach wody, a odstęp 30 m
      ogranicza autokorelację przestrzenną etykiet w jednej scenie.
    Wejście → wyjście: daty scen, `water_freq` (H, W; NaN poza AOI/bez obserwacji; używana
      WYŁĄCZNIE do losowania, nie jest cechą modelu), maska jeziora, siatka → GeoDataFrame EPSG:2180
      z kolumnami id, date, row, col, x, y, stratum, label (water/land/None), source (auto/human).
    Jak to obronić: stały `seed` daje powtarzalne losowanie; etykiety auto pochodzą z wielu scen
      (częstość), a nie z jednej sceny Otsu, więc nie powielają jej błędów.
    """
    rng = np.random.default_rng(seed)
    res = abs(grid.transform.a)
    masks: dict[str, np.ndarray] = {}

    def ok(date: str) -> np.ndarray:
        if date not in masks:
            masks[date] = ok_fn(date)
        return masks[date]

    finite = np.isfinite(water_freq)
    wf = np.where(finite, water_freq, -1.0)
    inside = distance_transform_edt(lake) * res      # odległość wnętrza jeziora od brzegu
    outside = distance_transform_edt(~lake) * res    # odległość lądu od jeziora
    pools = {
        "shore": (finite & (wf > SHORE_FREQ[0]) & (wf < SHORE_FREQ[1]), None, n_shore),
        "auto_water": (lake & (inside >= AUTO_WATER_EROSION_M) & (wf >= AUTO_WATER_MIN_FREQ),
                       "water", n_auto // 2),
        "auto_land": (finite & (outside >= AUTO_LAND_MIN_DIST_M) & (wf == 0), "land",
                      n_auto - n_auto // 2),
    }
    taken: dict[str, list[tuple[float, float]]] = {}
    used: set[int] = set()
    rows = []
    for stratum, (pool, label, n) in pools.items():
        idx = rng.permutation(np.flatnonzero(pool))
        got = 0
        for flat in idx:
            if got >= n:
                break
            r, c = divmod(int(flat), grid.width)
            x, y = grid.xy(r, c)
            for date in rng.permutation(scene_dates):
                if not ok(date)[r, c]:
                    continue
                prev = taken.get(date, [])
                if prev and np.min(np.hypot(np.array(prev)[:, 0] - x, np.array(prev)[:, 1] - y)) < MIN_SPACING_M:
                    continue
                taken.setdefault(date, []).append((x, y))
                rows.append(dict(date=str(date), row=r, col=c, x=x, y=y, stratum=stratum, label=label,
                                 source="auto", geometry=Point(x, y)))
                got += 1
                break
        if got < n:
            log.warning("Warstwa %s: %d z %d żądanych punktów (za mała pula)", stratum, got, n)
    g = gpd.GeoDataFrame(rows, geometry="geometry", crs=LABELS_CRS)
    g = g.sample(frac=1, random_state=seed).reset_index(drop=True)
    g.insert(0, "id", np.arange(len(g)))
    g["label"] = g["label"].astype(object).where(g["label"].notna(), None)
    g["label_v1"] = pd.Series([None] * len(g), dtype=object)
    g["review"] = False
    return g[COLUMNS]


def sample_extra(existing: gpd.GeoDataFrame, scene_dates: list[str], water_freq: np.ndarray,
                 lake: np.ndarray, grid: Grid, n: int = 100, stratum: str = "shore_low",
                 freq_range: tuple[float, float] = LOW_FREQ, seed: int = 43,
                 ok_fn: Callable[[str], np.ndarray] = load_ok_mask) -> gpd.GeoDataFrame:
    """Dolosowuje `n` nowych punktów warstwy `stratum` (domyślnie `shore_low`) bez ruszania istniejących.

    Co robi: pula = piksele z `water_freq` ∈ (lo, hi] (NaN = brak obserwacji/poza AOI odpada),
      których (row, col) nie ma jeszcze w `existing`. Każdy piksel dostaje losową scenę, w której
      jest ważny i bez chmury, z odstępem 30 m od WSZYSTKICH punktów tej sceny (starych i nowych).
      Nowe id zaczynają się od `existing.id.max() + 1`; etykieta None, source „auto”.
    Dlaczego tak: w warstwie `shore` jest za mało lądu (21 punktów); piksele rzadko mokre (5–30%)
      to pula, gdzie ląd jest częsty, a wybór NIE zależy od wyniku Otsu, więc porównanie RF–Otsu nie
      jest obciążone. Dopisywanie zamiast losowania od nowa zostawia etykiety autora nietknięte.
    Wejście → wyjście: istniejące etykiety, daty scen, `water_freq` (H, W), maska jeziora (nieużywana
      poza spójnością z `sample_candidates`), siatka → GeoDataFrame TYLKO z nowymi wierszami (`COLUMNS`).
    Jak to obronić: stały `seed` 43 (inny niż 42, by nie powielać losowania `shore`), ta sama
      procedura odstępu co w `sample_candidates`.
    """
    rng = np.random.default_rng(seed)
    masks: dict[str, np.ndarray] = {}

    def ok(date: str) -> np.ndarray:
        if date not in masks:
            masks[date] = ok_fn(date)
        return masks[date]

    lo, hi = freq_range
    finite = np.isfinite(water_freq)
    wf = np.where(finite, water_freq, -1.0)
    pool = finite & (wf > lo) & (wf <= hi)
    pool[existing.row.to_numpy(), existing.col.to_numpy()] = False
    taken: dict[str, list[tuple[float, float]]] = {}
    for d, s in existing.groupby("date"):
        taken[str(d)] = list(zip(s.x.astype(float), s.y.astype(float)))
    first_id = int(existing.id.max()) + 1
    rows = []
    for flat in rng.permutation(np.flatnonzero(pool)):
        if len(rows) >= n:
            break
        r, c = divmod(int(flat), grid.width)
        x, y = grid.xy(r, c)
        for date in rng.permutation(scene_dates):
            if not ok(date)[r, c]:
                continue
            prev = taken.get(date, [])
            if prev and np.min(np.hypot(np.array(prev)[:, 0] - x, np.array(prev)[:, 1] - y)) < MIN_SPACING_M:
                continue
            taken.setdefault(date, []).append((x, y))
            rows.append(dict(id=first_id + len(rows), date=str(date), row=r, col=c, x=x, y=y,
                             stratum=stratum, label=None, source="auto", label_v1=None, review=False,
                             geometry=Point(x, y)))
            break
    if len(rows) < n:
        log.warning("Warstwa %s: %d z %d żądanych punktów (za mała pula)", stratum, len(rows), n)
    g = gpd.GeoDataFrame(rows, columns=COLUMNS, geometry="geometry", crs=LABELS_CRS)
    g["label"] = g["label"].astype(object)
    g["label_v1"] = g["label_v1"].astype(object)
    return g


def mark_suspect(gdf: gpd.GeoDataFrame, margin: pd.Series,
                 threshold: float = SUSPECT_MARGIN) -> tuple[gpd.GeoDataFrame, list[int]]:
    """Oddaje do ślepej ponownej oceny ręczne „water” o MNDWI − Otsu < `threshold`.

    Co robi: dla wszystkich wierszy ręcznych kopiuje etykietę do `label_v1`; dla ręcznych „water”
      z `margin` < `threshold` zeruje etykietę (None, source „auto”) i ustawia `review=True`.
      Pozostałe wiersze dostają `review=False`. Zwraca (kopię tabeli, posortowane id podejrzanych).
    Dlaczego tak: 24 etykiety „woda” wyglądają spektralnie jak ląd (mokry muł, zalana roślinność?);
      autor ocenia je ponownie bez podglądu starej etykiety, a `label_v1` zostaje, by policzyć odsetek
      zmian (szum etykiet) i niczego nie tracić.
    Wejście → wyjście: etykiety, Series MNDWI − Otsu indeksowana jak `gdf` → (etykiety, lista id).
    Jak to obronić: reguła jest mechaniczna (próg −0,3), niezależna od modelu; stare etykiety zostają.
    """
    out = gdf.copy()
    human = out["source"] == "human"
    out["label_v1"] = pd.Series(np.where(human, out["label"], None), index=out.index, dtype=object)
    out["review"] = False
    bad = human & (out["label"] == "water") & (margin.reindex(out.index) < threshold)
    out.loc[bad, "label"] = None
    out.loc[bad, "source"] = "auto"
    out.loc[bad, "review"] = True
    out["label"] = out["label"].astype(object).where(out["label"].notna(), None)
    return out, sorted(int(i) for i in out.loc[bad, "id"])


def save(gdf: gpd.GeoDataFrame, path: Path) -> None:
    """Zapisuje etykiety do GeoPackage (EPSG:2180) – atomowo, przez plik tymczasowy.

    Dlaczego tak: GeoJSON w EPSG:2180 jest niestandardowy (RFC 7946 zna tylko WGS84); GPKG trzyma
      układ i typy kolumn. Zapis przez plik tymczasowy + `replace` nie zostawia pliku w połowie
      zapisanego, gdy serwer padnie w trakcie.
    Wejście → wyjście: GeoDataFrame, ścieżka → plik .gpkg z warstwą `labels`.
    Jak to obronić: test odczytuje to, co zapisano, i porównuje tabelę kolumna po kolumnie.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp" + path.suffix)
    tmp.unlink(missing_ok=True)
    gdf.to_file(tmp, layer=LAYER, driver="GPKG")
    tmp.replace(path)


def load(path: Path) -> gpd.GeoDataFrame:
    """Wczytuje etykiety zapisane przez `save` (brak etykiety = None)."""
    g = gpd.read_file(path, layer=LAYER)
    g["label"] = g["label"].astype(object).where(g["label"].notna(), None)
    if "label_v1" not in g:                      # pliki z rundy 1 nie mają nowych kolumn
        g["label_v1"] = None
    g["label_v1"] = g["label_v1"].astype(object).where(g["label_v1"].notna(), None)
    g["review"] = g["review"].fillna(False).astype(bool) if "review" in g else False
    return g
