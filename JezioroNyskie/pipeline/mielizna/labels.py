"""Kandydaci do etykiet woda/ląd: losowanie punktów, zapis GeoPackage i maski ważności scen."""
import logging
from pathlib import Path
from typing import Callable

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import distance_transform_edt
from shapely.geometry import Point

from mielizna.config import data_path, load_config
from mielizna.grid import Grid
from mielizna.s2 import BANDS, cloud_mask, is_usable, valid_mask

log = logging.getLogger(__name__)
LABELS_CRS = "EPSG:2180"
LAYER = "labels"
MIN_SPACING_M = 30.0
SHORE_FREQ = (0.05, 0.95)
AUTO_WATER_MIN_FREQ = 0.98
AUTO_WATER_EROSION_M = 200.0
AUTO_LAND_MIN_DIST_M = 300.0
COLUMNS = ["id", "date", "row", "col", "x", "y", "stratum", "label", "source", "geometry"]


def usable_dates(cfg: dict | None = None) -> list[str]:
    """Daty scen użytecznych: wiersze scenes_candidates.csv przechodzące `is_usable` (wraz z
    exclude_dates z configu) i mające gotowy COG; posortowane, bez powtórzeń.

    Dlaczego tak: źródłem prawdy jest CSV + config, nie zawartość katalogu s2/ (reguła R11);
      kolumna `usable` w CSV nie zna późniejszych wykluczeń zimowych, więc liczymy ją od nowa.
    Wejście → wyjście: config → lista dat 'YYYY-MM-DD'. Data bez pliku COG jest pomijana z ostrzeżeniem.
    Jak to obronić: ta sama funkcja `is_usable` filtruje sceny w całym pipeline.
    """
    cfg = cfg or load_config()
    df = pd.read_csv(data_path("processed", "scenes_candidates.csv"), dtype={"date": str})
    dates = sorted({r["date"] for r in df.to_dict("records") if is_usable(r, cfg)})
    present = [d for d in dates if data_path("processed", "s2", f"{d}.tif").exists()]
    if len(present) < len(dates):
        log.warning("Brak COG dla %d użytecznych dat: %s", len(dates) - len(present),
                    sorted(set(dates) - set(present)))
    return present


def load_scene(date: str, s2_dir: Path | None = None) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Wczytuje COG sceny: ({pasmo: odbicie float32}, SCL uint8)."""
    path = (s2_dir or data_path("processed", "s2")) / f"{date}.tif"
    with rasterio.open(path) as ds:
        arr = ds.read()
    return {b: arr[i] for i, b in enumerate(BANDS)}, np.nan_to_num(arr[len(BANDS)]).astype(np.uint8)


def load_ok_mask(date: str) -> np.ndarray:
    """Piksele ważne i bez chmur (ważność SCL/pasm minus maska chmur z 2-px buforem i cieni)."""
    bands, scl = load_scene(date)
    return valid_mask(bands, scl) & ~cloud_mask(scl)


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
    return g[COLUMNS]


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
    return g
