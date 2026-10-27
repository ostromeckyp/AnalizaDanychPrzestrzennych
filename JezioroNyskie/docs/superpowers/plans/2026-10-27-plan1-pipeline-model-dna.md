# Plan 1: szkielet + pipeline do modelu dna — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Z surowych danych (Sentinel-2, komunikaty RZGW / Wody Polskie, tabela V↔h z mapy KŻ, OSM) wyprodukować rastry modelu dna `bottom_z/zmin/zmax/obs_count.tif`, `scenes.json`, `shorelines.gpkg`, `marinas.gpkg` i wytrenowany `rf_model.joblib` — kontrakt dla backendu (plan 2).

**Architecture:** Logika w importowalnym pakiecie `pipeline/mielizna/` (testowana pytestem), a ponumerowane skrypty `pipeline/NN_*.py` to cienkie, liniowe „opowieści” wywołujące pakiet (czytelne do nauki, §4 spec). Wszystkie rastry na jednej siatce wzorcowej EPSG:2180, 10 m, 900×700. Klasyfikator woda/ląd: Random Forest (Otsu jako odniesienie i cecha). `h_t` w tym planie z wariantu B (pojemność → rzędna) i C (powierzchnia → poziom); wariant A (LiDAR) i D (KŻ) dochodzą w planie 4.

**Tech Stack:** Python 3.12 (uv), pystac-client, odc-stac, rasterio, rioxarray, xarray, geopandas, shapely, numpy, scipy, scikit-image, scikit-learn, joblib, pypdf, requests, pyyaml, pytest.

**Spec:** `docs/superpowers/specs/2026-10-26-mielizna-design.md` + `docs/BRIEF.md` (v1.5; po Task 1 tam leży). Executor czyta oba.

**Kolejne plany (nie w tym dokumencie):** plan 2 backend FastAPI (w tym `/api/current-level`), plan 3 frontend React, plan 4 LiDAR (wariant A) + mapa KŻ K1–K3/K5 + wariant D + ocena + raport + docker compose.

## Global Constraints

- Katalog roboczy: `/Users/pablo/Projects/AnalizaDanychPrzestrzennych/JezioroNyskie` (repo git to katalog nadrzędny `AnalizaDanychPrzestrzennych`). Pracować na gałęzi `feat/pipeline`, nie na `main`.
- Python **3.12** przypięty w `pipeline/.python-version`, zależności przez `uv` (`uv sync`, `uv run`).
- CRS obliczeń **EPSG:2180**. Siatka wzorcowa: **E 372 000–381 000, N 285 500–292 500, piksel 10 m → 700 wierszy × 900 kolumn**, transform `Affine(10, 0, 372000, 0, -10, 292500)`.
- BBOX wyszukiwania S2 (WGS84): **lon 17.20–17.32, lat 50.425–50.485**. Earth Search `https://earth-search.aws.element84.com/v1`, kolekcja `sentinel-2-l2a`, assety `blue, green, red, nir, swir16, swir22, scl`.
- **Zawsze maskować DN = 0** jako nodata (niezależnie od tagu w pliku).
- Pasma 20 m → 10 m `bilinear`; SCL i maski `nearest`.
- Cechy RF **nie mogą** zawierać: wysokości NMT, częstości zalewania piksela, `h_t`.
- Docstringi, komentarze i notatki po **polsku**; identyfikatory po angielsku lub jak w briefie (`h_t`, `z_min`, `z_max`, `D_lo`, `D_hi`). Każdy skrypt `NN_*.py` zaczyna się docstringiem: *Co robi · Dlaczego tak · Wejście → wyjście · Jak to obronić*.
- `data/raw/` i `data/processed/` poza gitem; w gicie `data/reference/` (małe pliki) i `data/raw/check/` (już istnieje, małe).
- Wayback Machine: max **1 zapytanie/s**, cache w `data/raw/rzgw/`; nie pobierać ponownie pliku z cache.
- Tabela KŻ i każdy plik z niej pochodny: obok plik z warunkami autora (Wiktor Wróblewski, KŻ Nysa, aktualizacja 23.05.2023; użycie niekomercyjne).
- **Wartości masek woda/ląd (wszędzie):** 1 woda, 0 ląd, **255 nieznane** (chmura, cień, nodata, poza AOI, odcięta woda). 255 nigdy nie jest lądem.
- Pakiet `pipeline/` jest instalowalny (`[project] name = "mielizna"`), bo backend (plan 2) importuje z niego `s2.load_day`, `classify.classify_scene`, `levels.load_area_level_curve`.
- Rastry wyjściowe: COG, `float32`, nodata `NaN` (dla `obs_count` `uint16`, nodata 0 nie dotyczy — 0 to „brak obserwacji”).
- Commity kończą się linią `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Zmiana offsetu odbicia od baseline 04.00 (25.01.2022):** sceny sprzed i po muszą dawać porównywalne odbicie; zła konwersja DN przesuwa MNDWI i psuje RF między latami. → test w Task 4.
2. **Chmura / nodata traktowane jako ląd:** piksel zasłonięty chmurą nie może zostać „lądem” w masce, bo zawyży `z_min`. → testy w Task 8 i Task 11.
3. **Scena na granicy kafli 33UXS/33UXR z ucięciem jeziora:** brakująca część nie może być klasyfikowana. Scena z < 95% ważnych pikseli w buforze jeziora jest odrzucana. → test w Task 4.
4. **Lód zimą wygląda jak ląd:** scena z SCL = 11 (snow/ice) > 1% pikseli w obrysie jeziora jest odrzucana. → test w Task 4.
5. **Odcięta zatoka przy niskim stanie:** woda niepołączona z głównym akwenem to 255, nie ląd (inaczej zawyżony `z_min` na płyciznach). → test w Task 8.
6. **Interpolacja bilinear rozmywa nodata = 0** na krawędzi kafla w „ciemne, ważne” piksele. → test w Task 4.
7. **Polskie liczby w PDF („32,668”, „122,1”) i dopasowanie dnia komunikatu:** przecinek dziesiętny; ten sam dzień ma pierwszeństwo przed ±1 dzień. → testy w Task 9.

---

### Task 1: Szkielet, konfiguracja i siatka wzorcowa

**Files:**
- Move: `BRIEF.md` → `docs/BRIEF.md` (dopisać na górze notkę: „Zmiany stacku po 26.10.2026: frontend React + TanStack Query, patrz `docs/superpowers/specs/2026-10-26-mielizna-design.md` §3”)
- Move: `docs/JN_2023_05_23__KZ (1).pdf` → `docs/JN_2023_05_23__KZ.pdf`
- Create: `.gitignore` (`data/raw/*`, `!data/raw/check/`, `data/processed/`, `.venv/`, `__pycache__/`, `.DS_Store`)
- Create: `README.md` (cel, szybki start pipeline'u, link do briefu i spec)
- Create: `pipeline/pyproject.toml`, `pipeline/.python-version` (`3.12`), `pipeline/config.yaml`
- Create: `pipeline/mielizna/__init__.py`, `pipeline/mielizna/config.py`, `pipeline/mielizna/grid.py`
- Test: `pipeline/tests/test_grid.py`

**Interfaces:**
- Produces:
  - `config.load_config(path: Path | None = None) -> dict` — domyślnie `pipeline/config.yaml`; klucze: `bbox_wgs84 [lon_min, lat_min, lon_max, lat_max]`, `grid {crs, xmin, ymin, xmax, ymax, res}`, `period {start, end}`, `scene_filter {max_tile_cloud: 30, max_local_cloud_pct: 5, min_valid_pct: 95, max_ice_pct: 1, buffer_m: 500, exclude_dates: []}`, `periods {all: [2017-01-01, 2026-12-31], pre_flood: [.., 2024-08-31], post_flood: [2024-09-30, ..]}`, `paths {raw, processed, reference}` (względem `JezioroNyskie/data`).
  - `grid.Grid` (dataclass frozen): `crs: str`, `transform: Affine`, `width: int`, `height: int`; metody `bounds() -> tuple[float,float,float,float]`, `xy(row, col) -> (x, y)` (środek piksela), `rowcol(x, y) -> (row, col)`.
  - `grid.reference_grid(cfg: dict | None = None) -> Grid`.
  - `config.data_path(kind: str, *parts) -> Path` (`kind ∈ {raw, processed, reference}`).

- [ ] **Step 1:** Zainstalować `uv`, jeśli brak (`brew install uv`), sprawdzić `uv --version`.
- [ ] **Step 2: Write the failing test** `test_grid.py`:
```python
def test_reference_grid_shape_and_origin():
    g = reference_grid()
    assert (g.height, g.width) == (700, 900)
    assert g.transform == Affine(10, 0, 372000, 0, -10, 292500)
    assert g.crs == "EPSG:2180"
    assert g.bounds() == (372000, 285500, 381000, 292500)

def test_xy_rowcol_roundtrip():
    g = reference_grid()
    assert g.xy(0, 0) == (372005.0, 292495.0)
    assert g.rowcol(*g.xy(350, 420)) == (350, 420)
```
- [ ] **Step 3:** Run `cd pipeline && uv run pytest tests/test_grid.py -v` → FAIL (import).
- [ ] **Step 4:** Napisać `pyproject.toml` (`[project] name="mielizna"`, `[build-system]` hatchling, pakiet `mielizna`; zależności z Tech Stack + `pytest` w dev), `config.yaml` z wartościami z Global Constraints, `config.py`, `grid.py`. `uv sync`.
- [ ] **Step 5:** Run test → PASS.
- [ ] **Step 6:** Przenieść pliki, dodać `.gitignore`, `README.md`. Commit: `chore: scaffold pipeline, config and reference grid`.

---

### Task 2: Tabela pojemność ↔ rzędna z mapy KŻ (K4)

**Files:**
- Create: `data/reference/kz_pojemnosc_rzedna.csv` (kolumny `pojemnosc_mln_m3,rzedna_m_npm`, 66 wierszy)
- Create: `data/reference/KZ_ZRODLO_I_WARUNKI.md` (źródło + pełna treść warunków autora przepisana z PDF)
- Create: `pipeline/mielizna/capacity.py`
- Test: `pipeline/tests/test_capacity.py`

**Interfaces:**
- Produces: `capacity.load_table(path: Path | None = None) -> pd.DataFrame`; `capacity.capacity_to_level(v_mln_m3: float | np.ndarray) -> float | np.ndarray` — interpolacja liniowa; poza zakresem tabeli zwraca `NaN`; `capacity.level_to_capacity(h)` — odwrotność.

- [ ] **Step 1:** Wyciągnąć obraz z `docs/JN_2023_05_23__KZ.pdf` (pypdf `page.images` albo PyMuPDF), wyciąć fragment z tabelą i warunkami, przepisać 66 wierszy do CSV (od 18,0 mln m³ ↔ 192,4 m do 122,0 ↔ 198,9, krok 0,1 m rzędnej). Kropka dziesiętna w CSV. Przepisać warunki autora do `KZ_ZRODLO_I_WARUNKI.md`.
- [ ] **Step 2: Write the failing test**:
```python
def test_table_shape_and_ends():
    t = load_table()
    assert len(t) == 66
    assert t.iloc[0].tolist() == [18.0, 192.4]
    assert t.iloc[-1].tolist() == [122.0, 198.9]
    assert t.pojemnosc_mln_m3.is_monotonic_increasing
    assert np.allclose(np.diff(t.rzedna_m_npm), 0.1, atol=1e-6)

def test_known_points():
    assert abs(capacity_to_level(65.69) - 195.9) <= 0.05   # NPP wg KŻ
    assert abs(capacity_to_level(121.70) - 198.9) <= 0.05  # Max PP wg KŻ
    assert 194.5 <= capacity_to_level(45.62) <= 194.7      # interpelacja 12.09.2024
    assert np.isnan(capacity_to_level(10.0))
    assert abs(level_to_capacity(capacity_to_level(50.0)) - 50.0) < 1e-6
```
- [ ] **Step 3:** Run `uv run pytest tests/test_capacity.py -v` → FAIL.
- [ ] **Step 4:** Implementować `capacity.py` (`np.interp` z `left/right=np.nan`).
- [ ] **Step 5:** Run → PASS. Jeśli `test_known_points` nie przechodzi, najpierw sprawdzić przepisanie tabeli (nie poluzowywać tolerancji).
- [ ] **Step 6:** Commit: `feat: KZ capacity-level table with source and terms`.

---

### Task 3: OSM — obrys jeziora, bufor, przystanie (skrypt 03)

**Files:**
- Create: `pipeline/mielizna/osm.py`, `pipeline/03_fetch_osm.py`
- Test: `pipeline/tests/test_osm.py`

**Interfaces:**
- Produces:
  - `osm.fetch_overpass(query: str) -> dict` (POST na `https://overpass-api.de/api/interpreter`, cache JSON w `data/raw/osm/`).
  - `osm.lake_polygon(overpass_json: dict) -> shapely Polygon | MultiPolygon` w EPSG:2180 (relation 2908769, `out geom`, składanie outer/inner przez `shapely.ops.polygonize`).
  - `osm.points_gdf(overpass_json: dict) -> gpd.GeoDataFrame` z kolumnami `osm_id, kind ∈ {marina, slipway, pier}, name, geometry` w EPSG:2180 (dla `way` — centroid).
  - Pliki: `data/processed/lake.gpkg` (warstwy `lake`, `aoi` = lake.buffer(500)), `data/processed/marinas.gpkg`.
  - `osm.aoi_mask(grid: Grid) -> np.ndarray[bool]` — `rasterize` warstwy `aoi` na siatkę; `osm.lake_mask(grid)` analogicznie dla `lake`.

- [ ] **Step 1: Write the failing test** na małym ręcznie zbudowanym JSON Overpass (2 node’y: `leisure=marina`, `leisure=slipway`; 1 relation z jedną zamkniętą ścieżką outer — kwadrat ~1 km wokół 50.455 N, 17.26 E):
```python
def test_points_gdf_kinds_and_crs(sample_json):
    g = points_gdf(sample_json)
    assert set(g.kind) == {"marina", "slipway"}
    assert g.crs.to_epsg() == 2180

def test_lake_polygon_area(sample_json):
    p = lake_polygon(sample_json)
    assert 0.8e6 < p.area < 1.2e6  # ~1 km²
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implementować. **Step 4:** Run → PASS.
- [ ] **Step 5:** Napisać `03_fetch_osm.py` (zapytanie: relation 2908769 + `leisure=marina|slipway`, `man_made=pier` w BBOX), uruchomić `uv run python 03_fetch_osm.py`. Oczekiwane: obrys ~ 6,6 × 4,2 km mieszczący się w siatce; co najmniej 1 przystań (node 2638165798) i 2 slipy.
- [ ] **Step 6:** Commit: `feat: OSM lake outline, AOI buffer and marinas`.

---

### Task 4: Sentinel-2 — wyszukanie, odbicie, filtr scen, zapis na siatkę (skrypt 01)

**Files:**
- Create: `pipeline/mielizna/s2.py`, `pipeline/01_fetch_s2.py`
- Test: `pipeline/tests/test_s2.py`

**Interfaces:**
- Consumes: `reference_grid()`, `osm.aoi_mask`, `osm.lake_mask`, `load_config()`.
- Produces:
  - `s2.BANDS = ["blue", "green", "red", "nir", "swir16", "swir22"]`.
  - `s2.search_items(cfg) -> list[pystac.Item]` (BBOX, okres, `eo:cloud_cover < 60` na kafel — **ostateczny filtr jest lokalny**; deduplikacja `_0`/`_1` dla tej samej pary (kafel, data): zostaje najnowszy `updated`/wyższy numer).
  - `s2.reflectance_offset(item) -> float` — **0.0, jeśli `earthsearch:boa_offset_applied` jest prawdą; −0.1, jeśli `s2:processing_baseline ≥ "04.00"`; w pozostałych 0.0.** Nigdy nie brać samego `raster:bands.offset`. Skala zawsze 1e-4.
  - `s2.dn_to_reflectance(dn: np.ndarray, offset: float) -> np.ndarray[float32]` — `DN == 0 → NaN`, potem `dn*1e-4 + offset`.
  - `s2.valid_mask(bands: dict, scl) -> bool array` — SCL ∉ {0, 1} **i** wszystkie 6 pasm skończone.
  - `s2.cloud_mask(scl) -> bool array` — SCL ∈ {8, 9, 10} dylatowane o 2 px (`scipy.ndimage.binary_dilation`) ∪ SCL == 3.
  - `s2.scene_quality(date, scl, valid, aoi, lake) -> dict`: `date`, `valid_pct` = ważne / wszystkie piksele AOI, `local_cloud_pct` = chmura / **ważne** piksele AOI, `ice_pct` = SCL 11 / piksele jeziora, `lake_nodata_pct` = (nieważne ∪ chmura) / piksele jeziora, `scl_pct` = słownik % każdej klasy SCL w AOI (do logu).
  - `s2.is_usable(q: dict, cfg) -> bool` (`valid_pct ≥ 95`, `local_cloud_pct < 5`, `ice_pct ≤ 1`, `q["date"] not in cfg.scene_filter.exclude_dates`).
  - `s2.load_day(items: list[pystac.Item], grid: Grid, cfg, bands=BANDS) -> tuple[dict[str, np.ndarray], np.ndarray]` — **funkcja pakietu (backend jej używa)**: `odc.stac.load(..., nodata=0, dtype="uint16", resampling={"*": "bilinear", "scl": "nearest"})` (nodata **przed** interpolacją), mozaika kafli, konwersja przez `reflectance_offset` danego itemu; zwraca pasma (odbicie, NaN) i SCL.
  - Plik na scenę: `data/processed/s2/{YYYY-MM-DD}.tif` — 7 pasm w kolejności `BANDS + ["scl"]`, float32 odbicie (scl jako float), nodata NaN, siatka wzorcowa. Gdy tego dnia są oba kafle: mozaika (pierwszy ważny piksel, kafel z większym `valid_pct` pierwszy).
  - `data/processed/scenes_candidates.csv` (dopisywany przyrostowo): `date, tiles, items, tile_cloud, processing_baseline, boa_offset_applied, offset_used, valid_pct, local_cloud_pct, ice_pct, lake_nodata_pct, usable`.

- [ ] **Step 1: Write the failing tests:**
```python
def test_reflectance_masks_zero_and_applies_offset():
    r = dn_to_reflectance(np.array([0, 1000, 3000], dtype=np.uint16), -0.1)
    assert np.isnan(r[0]) and np.allclose(r[1:], [0.0, 0.2])

def test_offset_rule():
    assert reflectance_offset(item(baseline="05.10", applied=True, raster_offset=-0.1)) == 0.0
    assert reflectance_offset(item(baseline="05.10", applied=False)) == -0.1
    assert reflectance_offset(item(baseline="02.14", applied=False)) == 0.0

def test_bilinear_does_not_leak_nodata():       # Review Focus 6
    # blok DN [[0,2000],[2000,2000]] przeskalowany 2× przez tę samą ścieżkę co load_day (nodata=0)
    out = resample_like_load_day(np.array([[0, 2000], [2000, 2000]], np.uint16))
    v = out[np.isfinite(out)]
    assert not ((v > 0) & (v < 0.2 - 1e-6)).any()

def test_quality_rejects_partial_tile():      # Review Focus 3
    aoi = np.ones((10, 10), bool); valid = aoi.copy(); valid[:, 6:] = False
    q = scene_quality("2021-06-01", np.full((10, 10), 4), valid, aoi, aoi)
    assert q["valid_pct"] == 60 and not is_usable(q, CFG)

def test_quality_rejects_ice():               # Review Focus 4
    scl = np.full((10, 10), 6); scl[0, :5] = 11
    q = scene_quality("2021-01-10", scl, np.ones((10, 10), bool), np.ones((10, 10), bool), np.ones((10, 10), bool))
    assert q["ice_pct"] == 5 and not is_usable(q, CFG)

def test_quality_accepts_clear():
    q = scene_quality("2021-06-01", np.full((10, 10), 6), *(np.ones((10, 10), bool),) * 3)
    assert is_usable(q, CFG)
```
Plus test baseline (Review Focus 1): ten sam „prawdziwy” piksel odbicia 0,2 zapisany jako DN 2000 (baseline 02.14) i DN 3000 (baseline 04.00, offset niezastosowany) daje to samo odbicie. Plus `test_excluded_date_not_usable`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implementować funkcje czyste. **Step 4:** Run → PASS.
- [ ] **Step 5:** Napisać `01_fetch_s2.py` w **dwóch przebiegach**: (1) tylko SCL (nearest) dla każdego dnia → `scene_quality` → wiersz w `scenes_candidates.csv`; (2) `load_day` z 6 pasmami **tylko dla dni `usable`** → zapis COG. Ustawić `GDAL_HTTP_MAX_RETRY=5`, `GDAL_HTTP_RETRY_DELAY=2`, `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`. Wznawialny (pomija dni już w CSV / pliki już zapisane). Uruchomić na całym okresie; log streszcza Haiku.
- [ ] **Step 6:** Weryfikacja: wykres `qc/lake_core_reflectance.png` — mediana NIR i SWIR16 pikseli rdzenia jeziora per scena w czasie **nie ma skoku przy 25.01.2022** (kontrola offsetu na prawdziwych danych); odsetek DN = 0 w SWIR w rdzeniu jeziora po 2022 < 1% (inaczej offset zjada ciemną wodę — zgłosić). `scenes_candidates.csv` istnieje; liczba `usable` **≥ 30** i obejmuje różne pory roku (wypisać rozkład po miesiącach); 2 losowe sceny otworzyć w QGIS i sprawdzić, że jezioro leży na tych samych pikselach (siatka zgodna); dla scen usable z miesięcy XII–III wygenerować miniatury `data/processed/qc/winter/{date}.png`, Claude je przegląda i sceny z widocznym lodem dopisuje do `pipeline/config.yaml` → `scene_filter.exclude_dates` (lista z powodem; `is_usable` ją respektuje).
- [ ] **Step 7:** Commit: `feat: Sentinel-2 search, reflectance, scene filter and gridded stacks`.

---

### Task 5: Cechy i próg Otsu

**Files:**
- Create: `pipeline/mielizna/features.py`, `pipeline/mielizna/otsu.py`
- Test: `pipeline/tests/test_features.py`, `pipeline/tests/test_otsu.py`

**Interfaces:**
- Consumes: plik sceny z Task 4 (słownik pasm `dict[str, np.ndarray]`).
- Produces:
  - `features.FEATURES = ["blue","green","red","nir","swir16","swir22","ndwi","mndwi","awei_sh","awei_nsh","ndvi","mndwi_minus_otsu","mndwi_mean3","mndwi_std3","doy_sin","doy_cos"]`.
  - `features.indices(b: dict[str, np.ndarray]) -> dict[str, np.ndarray]` — NDWI=(G−NIR)/(G+NIR), MNDWI=(G−SWIR1)/(G+SWIR1), NDVI=(NIR−R)/(NIR+R), AWEI_nsh=4(G−SWIR1)−(0,25·NIR+2,75·SWIR2), AWEI_sh=B+2,5·G−1,5·(NIR+SWIR1)−0,25·SWIR2; mianownik 0 → NaN.
  - `features.compute_features(b, otsu_threshold: float, date: datetime.date) -> dict[str, np.ndarray]` — wszystkie `FEATURES`; okno 3×3: `uniform_filter` na wartościach z NaN→0 i osobno na masce ważności, iloraz = średnia z ważnych sąsiadów (tak samo dla kwadratów → odchylenie); bez `generic_filter`; `doy_sin = sin(2π·doy/365,25)`.
  - `features.stack(feats: dict) -> np.ndarray` o kształcie `(H, W, len(FEATURES))` w kolejności `FEATURES`.
  - `otsu.otsu_threshold(mndwi: np.ndarray, aoi: np.ndarray) -> float` — `skimage.filters.threshold_otsu` na pikselach AOI, które są ważne **i nie są chmurą** (wywołujący przekazuje `aoi & valid & ~cloud`).
  - `otsu.otsu_mask(mndwi, threshold) -> np.ndarray[uint8]` — 1 woda, 0 ląd, 255 nodata (NaN).

- [ ] **Step 1: Write the failing tests:**
```python
def test_indices_known_values():
    b = {k: np.array([v]) for k, v in dict(blue=.05, green=.06, red=.04, nir=.02, swir16=.01, swir22=.005).items()}
    i = indices(b)
    assert np.isclose(i["mndwi"][0], (0.06-0.01)/(0.06+0.01))
    assert np.isclose(i["awei_nsh"][0], 4*(0.06-0.01) - (0.25*0.02 + 2.75*0.005))

def test_zero_denominator_is_nan():
    b = {k: np.array([0.0]) for k in BANDS}
    assert np.isnan(indices(b)["ndwi"][0])

def test_feature_list_has_no_leaky_inputs():
    assert set(FEATURES).isdisjoint({"nmt", "dem", "water_freq", "h_t"})

def test_otsu_bimodal():
    rng = np.random.default_rng(0)
    m = np.concatenate([rng.normal(-0.4, .05, 5000), rng.normal(0.4, .05, 5000)])
    t = otsu_threshold(m, np.ones_like(m, bool))
    assert -0.15 < t < 0.15

def test_otsu_mask_nan_is_nodata():
    assert otsu_mask(np.array([np.nan, .5, -.5]), 0.0).tolist() == [255, 1, 0]
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implementować. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `feat: spectral indices, RF features and Otsu threshold`.

---

### Task 6: Narzędzie do etykiet + kandydaci

**Files:**
- Create: `pipeline/mielizna/labels.py`, `pipeline/tools/label_server.py`, `pipeline/tools/label.html`, `pipeline/04a_label_candidates.py`
- Test: `pipeline/tests/test_labels.py`

**Interfaces:**
- Consumes: sceny z Task 4, `otsu_*` z Task 5, `osm.lake_mask`, `reference_grid()`.
- Produces:
  - `labels.sample_candidates(scene_dates: list[str], water_freq: np.ndarray, lake: np.ndarray, grid: Grid, n_shore: int = 220, n_auto: int = 300, seed: int = 42) -> gpd.GeoDataFrame` — kolumny `id, date, row, col, x, y, stratum ∈ {shore, auto_water, auto_land}, label ∈ {water, land, None}, source ∈ {auto, human}`.
    - `water_freq` = odsetek scen, w których Otsu daje wodę (tylko do losowania, nie jest cechą).
    - `shore`: piksele z `0.05 < water_freq < 0.95`, losowa scena, w której piksel jest ważny; etykieta `None`.
    - `auto_water` (n_auto/2 = 150): piksele w `lake` zerodowanym o 200 m z `water_freq ≥ 0.98` → `water`, `source=auto`.
    - `auto_land` (150): piksele ≥ 300 m od `lake` z `water_freq == 0` → `land`, `source=auto`.
    - Dla każdego punktu (wszystkie warstwy) data = losowa scena `usable`, w której piksel jest ważny i nie jest chmurą.
    - Punkty w odległości < 30 m od siebie w tej samej scenie odrzucać.
  - `labels.save(gdf, path)` / `labels.load(path)` — **GeoPackage** EPSG:2180 `data/reference/labels.gpkg` (GeoJSON w 2180 jest niestandardowy).
  - `label_server.serve(port: int = 8765, labels_path: Path = ...) -> HTTPServer`.
  - `label_server.py` (stdlib `http.server`, port 8765): `GET /` → `label.html`; `GET /api/next` → następny punkt `shore` bez etykiety (JSON: id, date, x, y, lon, lat); `GET /api/crop/{id}.png` → wycinek 64×64 px sceny (RGB i false-color SWIR16/NIR/G obok, 4× powiększenie, krzyżyk na środku); `POST /api/label` `{id, label ∈ water|land|skip}` → zapis natychmiast do pliku.
  - `label.html`: wycinek S2 + obok ortofotomapa dla tego samego bbox ze `<img>` WMS GetMap `https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution` (warstwa `Raster`, EPSG:2180, 512×512); klawisze **W** woda, **L** ląd, **?** pomiń; licznik „oznaczono X / Y”; data sceny widoczna (orto ma inną datę — ostrzeżenie w nagłówku).

- [ ] **Step 1: Write the failing tests:**
```python
def test_strata_and_auto_labels(synthetic):
    g = sample_candidates(**synthetic)
    assert set(g.stratum) == {"shore", "auto_water", "auto_land"}
    assert (g[g.stratum == "shore"].label.isna()).all()
    assert (g[g.stratum == "auto_water"].label == "water").all()

def test_min_spacing_same_scene(synthetic):
    g = sample_candidates(**synthetic)
    for _, s in g.groupby("date"):
        d = s.geometry.apply(lambda p: s.geometry.distance(p).nsmallest(2).iloc[-1])
        assert (d[len(s) > 1] >= 30).all()

def test_save_load_roundtrip(tmp_path, synthetic):
    g = sample_candidates(**synthetic); save(g, tmp_path / "l.gpkg")
    assert_geodataframe_equal(load(tmp_path / "l.gpkg"), g, check_dtype=False, check_like=True)
```
Plus test serwera (uruchomiony w wątku na losowym porcie): `POST /api/label` zmienia etykietę w pliku, a `GET /api/next` po tym zwraca inny punkt.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implementować. **Step 4:** Run → PASS.
- [ ] **Step 5:** **Najpierw** przegląd miniatur zimowych z Task 4 musi być skończony (`exclude_dates` uzupełnione), dopiero potem `04a_label_candidates.py`: Otsu dla wszystkich scen `usable`, `water_freq`, losowanie, zapis `labels.gpkg`. Uruchomić serwer, ręcznie oznaczyć 3 punkty, sprawdzić zapis.
- [ ] **Step 6:** Commit: `feat: label candidates and browser labeling tool`.
- [ ] **Step 7: CHECKPOINT AUTORA** (w tym czasie koordynator może wykonać Task 9 — nie zależy od etykiet). Poprosić autora: `cd pipeline && uv run python tools/label_server.py`, otworzyć `http://localhost:8765`, oznaczyć wszystkie punkty `shore` (~150–200 po odjęciu „?”; ok. 20–30 min, można w kilku podejściach). Nie przechodzić do Task 7, dopóki nie ma ≥ 150 etykiet `human`. Commit pliku etykiet: `data: human water/land labels`.

---

### Task 7: Random Forest — tabela uczenia, walidacja, model

**Files:**
- Create: `pipeline/mielizna/rf.py`, `pipeline/04b_train_rf.py`
- Test: `pipeline/tests/test_rf.py`

**Interfaces:**
- Consumes: `labels.load`, `features.compute_features/FEATURES`, `otsu.*`, sceny Task 4.
- Produces:
  - `rf.build_table(labels: gpd.GeoDataFrame, scenes_dir: Path) -> pd.DataFrame` — kolumny `FEATURES + ["y", "date", "block", "otsu_pred", "scl_pred", "source"]`; `y` 1/0; `block` = id bloku 500 m (`(x // 500, y // 500)` jako str); `scl_pred` = `scl == 6`; wiersze z NaN w cechach odrzucone (liczba w logu); etykiety `skip` pominięte.
  - `rf.make_model(seed=42) -> RandomForestClassifier(n_estimators=100, min_samples_leaf=2, class_weight="balanced", n_jobs=-1, random_state=seed)`.
  - `rf.grouped_cv(df, group_col: str, n_splits=5) -> dict` — `GroupKFold`; zwraca też `folds: list[(train_idx, test_idx)]`; dla każdej metody `{rf, otsu, scl}` metryki na tych samych foldach: `oa, kappa, f1_water, confusion [[tn, fp],[fn, tp]]`; oddzielnie wynik tylko na wierszach `source == human` (trudne, brzegowe).
  - `rf.train_final(df) -> RandomForestClassifier` (na wszystkich wierszach) + `rf.permutation_importance_table(model, df) -> pd.DataFrame`.
  - `rf.save_model(model, path: Path)` / `rf.load_model(path) -> dict` (bundle opisany niżej).
  - Pliki: `data/processed/model/rf_model.joblib` (słownik `{"model", "features": FEATURES, "bands": BANDS, "cloud_scl_classes": [3, 8, 9, 10], "cloud_dilate_px": 2, "grid": {...}, "sklearn_version", "config_sha", "trained_at", "n_rows"}`), `data/processed/model/rf_metrics.json` (`by_scene`, `by_block`, `importance`).

- [ ] **Step 1: Write the failing tests:**
```python
def test_cv_metrics_on_separable_data(toy_df):     # toy: woda mndwi>0, ląd <0
    m = grouped_cv(toy_df, "date")
    assert m["rf"]["oa"] > 0.95 and {"oa", "kappa", "f1_water", "confusion"} <= m["otsu"].keys()

def test_no_group_leakage(toy_df):
    for tr, te in grouped_cv(toy_df, "block")["folds"]:
        assert set(toy_df.block.iloc[tr]).isdisjoint(toy_df.block.iloc[te])

def test_saved_model_carries_feature_order(tmp_path, toy_df):
    save_model(train_final(toy_df), tmp_path / "m.joblib")
    assert joblib.load(tmp_path / "m.joblib")["features"] == FEATURES
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implementować. **Step 4:** Run → PASS.
- [ ] **Step 5:** Uruchomić `04b_train_rf.py` na prawdziwych etykietach. Wypisać tabelę: metoda × (OA, Kappa, F1) dla `by_scene`, `by_block`, `human-only`.
- [ ] **Step 6:** Weryfikacja: **kryterium główne = podzbiór `human` (punkty brzegowe), `by_block`**: OA RF ≥ 95% (M2 z briefu). Wynik „wszystkie wiersze” raportować pomocniczo i w notatce M2 wprost napisać, że punkty `auto` wybrano przez `water_freq` z Otsu, więc Otsu jest na nich poprawny z konstrukcji (porównanie RF vs Otsu ma sens tylko na `human`). Jeśli kryterium nie jest spełnione: raportować liczby, nie stroić na zbiorze testowym.
- `rf.build_table` przy braku pliku sceny (scena wykluczona później) pomija wiersz z ostrzeżeniem.
- [ ] **Step 7:** Commit: `feat: random forest water classifier with grouped CV`.

---

### Task 8: Klasyfikacja wszystkich scen + linie brzegowe (skrypty 04, 05)

**Files:**
- Create: `pipeline/mielizna/classify.py`, `pipeline/mielizna/shoreline.py`, `pipeline/04_classify.py`, `pipeline/05_shorelines.py`
- Test: `pipeline/tests/test_classify.py`, `pipeline/tests/test_shoreline.py`

**Interfaces:**
- Consumes: `rf_model.joblib`, `features.*`, `otsu.*`, `osm.lake_mask`, sceny.
- Produces:
  - `classify.predict_scene(bands: dict, model_bundle: dict, date, otsu_t: float) -> np.ndarray[uint8]` — 1/0, **255 dla pikseli z NaN w cechach lub SCL ∈ {3,8,9,10}** (chmura/cień ≠ ląd).
  - `classify.keep_lake_component(mask: np.ndarray[uint8], lake_core: np.ndarray[bool], aoi: np.ndarray[bool], min_px: int = 5) -> np.ndarray[uint8]` — `scipy.ndimage.label` (8-sąsiedztwo) na wodzie; zostają komponenty przecinające `lake_core` (lake zerodowany o 200 m) i dotykające ich bufora 1 px; **komponenty < `min_px` → 0 (szum); pozostałe odcięte komponenty ≥ `min_px` → 255 (nieznane, np. odcięta zatoka)**; poza AOI → 255; 255 bez zmian.
  - `classify.classify_scene(bands: dict, scl, date, bundle: dict, aoi, lake_core) -> tuple[np.ndarray[uint8], float, float]` — **funkcja pakietu (backend jej używa)**: valid/cloud z `s2`, Otsu na `aoi & valid & ~cloud`, cechy, `predict_scene`, `keep_lake_component`; zwraca (maska, otsu_t, area_km2).
  - `shoreline.mask_to_shoreline(mask, transform) -> tuple[BaseGeometry, float]` — `rasterio.features.shapes` na `mask == 1`, największy poligon jeziora, granica jako (Multi)LineString, `simplify(5)`; drugi element: powierzchnia wody w km² = liczba pikseli == 1 po filtrze komponentów × 100 m² (255 pominięte; nie z geometrii po uproszczeniu). Maski zostają na dysku — plan 4 (wariant A) potrzebuje pikseli brzegu, nie uproszczonej linii.
  - Pliki: `data/processed/masks/{date}.tif` (uint8, nodata 255) dla RF i `data/processed/masks_otsu/{date}.tif`; `data/processed/shorelines.gpkg` warstwa `shorelines`: `date, area_km2, lake_nodata_pct, otsu_threshold, local_cloud_pct, h_t (NaN), h_method (None), geometry` (Task 10 przepisuje całą warstwę).

- [ ] **Step 1: Write the failing tests:**
```python
def test_cloud_is_nodata_not_land():           # Review Focus 2
    m = predict_scene(bands_with_cloud_scl, bundle, date(2021, 6, 1), 0.0)
    assert (m[cloud_px] == 255).all()

def test_keep_lake_component_drops_isolated_pond():
    m = np.zeros((20, 20), np.uint8); m[5:15, 5:15] = 1; m[0:2, 18:20] = 1
    core = np.zeros_like(m, bool); core[8:12, 8:12] = True
    out = keep_lake_component(m, core, np.ones_like(core), min_px=5)
    assert out[10, 10] == 1 and out[0, 19] == 0      # 4 px < 5 → szum → 0

def test_cut_off_bay_is_unknown_not_land():      # Review Focus 5
    m = np.zeros((20, 20), np.uint8); m[5:15, 5:10] = 1; m[5:15, 12:18] = 1   # zatoka 60 px odcięta
    core = np.zeros_like(m, bool); core[8:12, 6:9] = True
    out = keep_lake_component(m, core, np.ones_like(core), min_px=5)
    assert (out[5:15, 12:18] == 255).all()

def test_shoreline_area_of_square():
    m = np.zeros((30, 30), np.uint8); m[10:20, 10:20] = 1
    geom, area = mask_to_shoreline(m, Affine(10, 0, 0, 0, -10, 300))
    assert area == pytest.approx(0.01) and geom.length == pytest.approx(400, rel=0.05)
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implementować. **Step 4:** Run → PASS.
- [ ] **Step 5:** Uruchomić 04 i 05. Weryfikacja wizualna: 5 scen o różnym poziomie (najmniejsza, największa i 3 pośrednie powierzchnie) — PNG `data/processed/qc/{date}.png` (RGB + kontur RF + kontur Otsu); Claude ogląda i opisuje w notatce, co widać przy brzegu.
- [ ] **Step 6:** Commit: `feat: classify scenes with RF, keep lake component, shorelines`.

---

### Task 9: Komunikaty RZGW / Wody Polskie → `h_t` wariant B (skrypt 06, część 1)

**Files:**
- Create: `pipeline/mielizna/bulletins.py`, `pipeline/06a_fetch_bulletins.py`
- Create: `pipeline/tests/fixtures/rzgw_row.txt` (wycinek tekstu z `data/raw/check/rzgw_wayback_sample.pdf`), `pipeline/tests/fixtures/govpl_*.txt`, `pipeline/tests/fixtures/govpl_list.html`
- Test: `pipeline/tests/test_bulletins.py`

**Interfaces:**
- Consumes: `data/raw/check/rzgw_wayback_index.csv`, lista scen (`shorelines.gpkg` / `scenes_candidates.csv`), `capacity.capacity_to_level`.
- Produces:
  - `bulletins.parse_pl_number(s: str) -> float` (`"32,668" → 32.668`, `"1 234,5" → 1234.5`).
  - `bulletins.parse_rzgw_text(text: str) -> dict | None` — wiersz zbiornika Nysa: linia `Nysa` (sama, nie „Nysa Kłodzka”/„Nysa Szalona”), następna zaczyna się od `Nysa Kłodzka`, po niej liczby; zwraca `{"v_current": 3. liczba, "v_npp": 4., "v_maxpp": 5.}`.
  - `bulletins.parse_govpl_text(text: str) -> dict | None` — ten sam słownik z tabeli „Informacja o zbiornikach”, wiersz „Nysa” (format ustalić na pobranej próbce, zapisać próbkę jako fixture).
  - `bulletins.list_govpl(html: str) -> list[tuple[date, str]]` — naprawiony parser listy (poprzedni zwracał 0; fixture z aktualnego HTML).
  - `bulletins.fetch_for_dates(dates: list[date]) -> pd.DataFrame` — dla każdej daty sceny: komunikat z tego dnia, a gdy brak — z ±1 dnia (bliższy; przy remisie wcześniejszy). Kolumny `scene_date, bulletin_date, source ∈ {wayback, govpl}, v_current, v_npp, v_maxpp, url` (`v_npp` zachowane per scena — zmiana 66,3 → 65,7 mln m³ między 2021 a 2024, §4 briefu). Cache PDF w `data/raw/rzgw/`, 1 zapytanie/s do Wayback.
  - `bulletins.choose_bulletin(scene_date: date, available: dict[date, Any]) -> date | None` — reguła ten sam dzień → ±1 dzień (bliższy, remis → wcześniejszy) → `None`.
  - Plik `data/processed/bulletins.csv`.

- [ ] **Step 1: Write the failing tests:**
```python
def test_parse_pl_number():
    assert parse_pl_number("32,668") == 32.668 and parse_pl_number("1 234,5") == 1234.5

def test_parse_rzgw_row(): # fixture z prawdziwego PDF
    r = parse_rzgw_text(FIXTURE_RZGW)
    assert r == {"v_current": 32.668, "v_npp": 66.3, "v_maxpp": 122.1}

def test_rzgw_does_not_match_otmuchow_or_slup():
    assert parse_rzgw_text("Otmuchów \nNysa Kłodzka  7,00 11,87 26,037 59,0 129,5") is None

def test_same_day_preferred_over_neighbour():  # Review Focus 5
    pick = choose_bulletin(date(2021, 5, 10), {date(2021, 5, 9): "a", date(2021, 5, 10): "b"})
    assert pick == date(2021, 5, 10)
```
Plus `test_parse_govpl_row` i `test_list_govpl_nonempty` na fixture’ach pobranych w Step 3.
- [ ] **Step 2:** Run → FAIL (dla testów RZGW).
- [ ] **Step 3:** Pobrać jedną stronę listy gov.pl i jeden komunikat krajowy, zapisać jako fixture’y, dopisać ich testy z wartościami odczytanymi ręcznie z PDF.
- [ ] **Step 4:** Implementować. **Step 5:** Run → PASS.
- [ ] **Step 6:** Uruchomić `06a_fetch_bulletins.py` dla wszystkich scen `usable`. Wypisać: ile scen ma komunikat (spodziewane rzędu 128/324 dla dni z chmurami < 20%) z podziałem na lata; zbadać, jak daleko wstecz sięga lista gov.pl (otwarta kwestia z §13 briefu) i zapisać wynik.
- [ ] **Step 7:** Commit: `feat: reservoir bulletins scraping and parsing (variant B input)`.

---

### Task 10: `scenes.json` — warianty B i C

**Files:**
- Create: `pipeline/mielizna/levels.py`, `pipeline/06_water_levels.py`
- Test: `pipeline/tests/test_levels.py`

**Interfaces:**
- Consumes: `bulletins.csv`, `capacity.capacity_to_level`, `shorelines.gpkg` (powierzchnie), `scenes_candidates.csv`.
- Produces:
  - `data/reference/known_levels.csv` (kolumny `start,end,h,sigma,method,source`), pierwszy wiersz: `2025-04-28,2025-05-12,197.92,0.08,R,RZGW piętrzenie 2025`; `levels.load_overrides(path) -> pd.DataFrame`. Plan 4 dopisze tu wiersze wariantu A (`method=A`). Kolejność pierwszeństwa: `A > R > B > C`.
  - `levels.variant_b(bulletins: pd.DataFrame) -> pd.DataFrame` — `h_t = capacity_to_level(v_current)`, `h_sigma = 0.15` (stała robocza: rozbieżność interpelacja–tabela ≈ 0,13 m, zmiana krzywej 2021→2024 ≈ 0,04 m, dzień ±1; zapisać w docstringu jako założenie), `h_method="B"`, kolumna `capacity_curve_note` (np. „v_npp=66,3 (instrukcja do 2021)”).
  - `levels.fit_area_level(area_km2: np.ndarray, h: np.ndarray) -> AreaLevelCurve` — na scenach B/R z `lake_nodata_pct ≤ 1`: mediany `h` w przedziałach powierzchni → **`IsotonicRegression(increasing=True)`** → `PchipInterpolator` (PCHIP zachowuje monotoniczność dopiero na monotonicznych danych); `AreaLevelCurve.__call__(a) -> tuple[float, bool]` (zwykły Python `bool`); poza zakresem — ekstrapolacja liniowa z ostatnich 3 punktów, `extrapolated=True`; `rmse` = **leave-one-out**.
  - `levels.save_area_level_curve(curve, path)` / `levels.load_area_level_curve(path) -> AreaLevelCurve` — **funkcja pakietu (backend `/api/current-level`)**; JSON: `area_km2[], h[], area_min, area_max, method: "isotonic+pchip", extrapolation: "linear_last3", n_points, rmse_loo`.
  - `levels.variant_c(scenes, curve) -> pd.DataFrame` — dla scen bez A/R/B: `h_method="C"`, `h_sigma` = `rmse_loo` (+0,1 m, gdy ekstrapolacja; scena z `lake_nodata_pct > 1` dostaje dodatkowo flagę `area_biased`).
  - `levels.assign_levels(scene_dates: list[date], bulletins: pd.DataFrame, overrides: pd.DataFrame, areas: dict[date, float] | None = None) -> pd.DataFrame` — kolejność: `overrides` (A > R) → wariant B → wariant C; kolumny jak w `scenes.json`.
  - `levels.write_scenes_json(df, path)` → `data/processed/scenes.json`: lista obiektów `{date, tiles, h_t, h_method, h_source, h_sigma, h_datum, area_km2, lake_nodata_pct, otsu_threshold, local_cloud_pct, capacity_mln_m3 | null}` (`h_datum` = `"unknown (RZGW, prawdopodobnie KRON86)"` dla B/R/C — plan 4 uzgodni z EVRF2007), posortowana po dacie, liczby zaokrąglone do 0,01 m / 0,001 km². Zapis krzywej przez `save_area_level_curve` do `data/processed/model/area_level_curve.json`.
  - Uzupełnienie `h_t`, `h_method` w `shorelines.gpkg`.

- [ ] **Step 1: Write the failing tests:**
```python
def test_curve_is_monotonic_and_flags_extrapolation():
    c = fit_area_level(np.array([10, 12, 14, 16, 18.]), np.array([192, 193, 194, 195, 196.]))
    hs = [c(a)[0] for a in np.linspace(10, 18, 50)]
    assert np.all(np.diff(hs) >= 0)
    assert c(20.0)[1] is True and c(15.0)[1] is False

def test_curve_monotonic_on_noisy_input():
    c = fit_area_level(np.array([10, 11, 12, 13, 14, 15.]), np.array([192, 192.6, 192.4, 193.5, 193.3, 194.]))
    hs = [c(a)[0] for a in np.linspace(10, 15, 50)]
    assert np.all(np.diff(hs) >= -1e-9)

def test_known_level_overrides_bulletin():
    df = assign_levels([date(2025, 4, 28)], one_bulletin_for_2025_04_28, load_overrides(KNOWN_CSV))
    assert df.iloc[0].h_t == 197.92 and df.iloc[0].h_method == "R"

def test_scenes_json_schema(tmp_path):
    write_scenes_json(sample_df, tmp_path / "s.json")
    s = json.loads((tmp_path / "s.json").read_text())[0]
    assert set(s) == {"date","tiles","h_t","h_method","h_source","h_sigma","h_datum","area_km2",
                      "lake_nodata_pct","otsu_threshold","local_cloud_pct","capacity_mln_m3"}
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implementować. **Step 4:** Run → PASS.
- [ ] **Step 5:** Uruchomić `06_water_levels.py`. Weryfikacja: wykres `data/processed/qc/area_vs_level.png` (B kropki, C krzyżyki, krzywa); **sceny z 05–12.09.2024 (przed zrzutem powodziowym) mają `h_t` w 194,70 ± 0,3 m** (spójność z interpelacją, kryterium M3) — wypisać, którą metodą (to okres bez komunikatów, więc najpewniej C: sprawdzamy krzywą, nie B); jeśli brak takich scen, zapisać to; wypisać zakres `h_t` (min/max) i liczbę scen na metodę.
- [ ] **Step 6:** Commit: `feat: water level per scene (variants B and C) and scenes.json`.

---

### Task 11: Model dna — przedziały zalania (skrypt 07)

**Files:**
- Create: `pipeline/mielizna/bottom.py`, `pipeline/07_bottom_model.py`
- Test: `pipeline/tests/test_bottom.py`

**Interfaces:**
- Consumes: `masks/{date}.tif`, `scenes.json`, `osm.aoi_mask`, `config.period`.
- Produces:
  - `bottom.compute_bounds(masks: np.ndarray[uint8] (T,H,W), h: np.ndarray (T,), h_sigma: np.ndarray (T,)) -> dict[str, np.ndarray]` z kluczami `z_min, z_max, z, unc, obs_count, n_conflict` (H, W). Kolejność scen na wejściu dowolna (funkcja sortuje sama).
  - **`bottom_zmin` / `bottom_zmax` są już poszerzone o σ:** `z_min −= h_sigma` sceny lądu, która wyznaczyła `z_min`; `z_max += h_sigma` sceny wody, która wyznaczyła `z_max`. Dzięki temu backend stosuje regułę §6.4 (`D_lo = h − z_max`, `D_hi = h − z_min`) wprost na rastrach. Zapisać to w `model_meta.json` (`"bounds_include_h_sigma": true`).
  - `bottom.write_model(result, grid, out_dir: Path)` → `bottom_z.tif`, `bottom_zmin.tif`, `bottom_zmax.tif`, `bottom_unc.tif` (float32 COG, NaN), `obs_count.tif`, `conflict_count.tif` (uint16 COG) + `model_meta.json` (`period, n_scenes, n_scenes_by_method, share_c_extrapolated, h_min_obs, h_max_obs, n_conflict_px, bounds_include_h_sigma, created_at, version` = sha256 skrótu z `scenes.json` i list plików masek, pierwsze 12 znaków).
  - Katalog `data/processed/model/{period_name}/` (`period_name` z configu, domyślnie `all`; dodatkowo `--period pre_flood` = do 2024-08-31 (porównanie z KŻ) i `--period post_flood` = od 2024-09-30 (sprawdzenie zmian dna po powodzi; okresy w `config.yaml` → `periods`).

**Algorytm `compute_bounds` (dla jednego piksela; implementacja wektorowa po T):**
```
obserwacje: pary (h_t, w_t), w_t ∈ {1 woda, 0 ląd}; 255 pomijamy
posortuj po h; progi kandydujące θ_k = punkty środkowe między kolejnymi **różnymi** h (oraz −∞, +∞) — dwie sceny o tym samym h nie dają progu między sobą
błędy(θ) = #(woda z h < θ) + #(ląd z h > θ)          # dno na wysokości θ tłumaczy wszystko poza błędami
θ* = zbiór progów o minimalnej liczbie błędów; n_conflict = ten minimum
z_min = max h lądu spójnego z θ* (h < min θ*) ; z_max = min h wody spójnej z θ* (h > max θ*)
tylko woda  → z_max = min h wody, z_min = NaN      (zawsze zalany: dolne ograniczenie głębokości)
tylko ląd   → z_min = max h lądu, z_max = NaN
brak obs.   → oba NaN; poza AOI → oba NaN
z = (z_min + z_max)/2 tam, gdzie oba są (z granic przed poszerzeniem o σ); unc = (z_max_σ − z_min_σ)/2 (z granic poszerzonych)
```
Wektorowo: posortować sceny po `h` raz; `cumsum` wody i lądu wzdłuż T daje błędy dla wszystkich progów jednocześnie (`argmin` po osi T). Pamięć: (T≈150)×700×900 uint8 ≈ 95 MB — w porządku; obliczenia w paskach wierszy, jeśli > 1 GB.

- [ ] **Step 1: Write the failing tests:**
```python
H = np.array([193.8, 194.2, 194.6, 195.4]); S0 = np.zeros(4)
def px(*w): return np.array(w, np.uint8).reshape(-1, 1, 1)

def test_clean_pixel_interval():
    r = compute_bounds(px(0, 0, 1, 1), H, S0)
    assert r["z_min"][0,0] == 194.2 and r["z_max"][0,0] == 194.6 and r["n_conflict"][0,0] == 0

def test_one_conflict_exact():
    r = compute_bounds(px(0, 1, 0, 1, 1), np.array([193.8, 194.0, 194.2, 194.6, 195.4]), np.zeros(5))
    assert (r["z_min"][0,0], r["z_max"][0,0], r["n_conflict"][0,0]) == (193.8, 194.6, 1)

def test_unsorted_input_same_result():
    perm = [2, 0, 3, 1]
    r = compute_bounds(px(0, 0, 1, 1)[perm], H[perm], S0)
    assert (r["z_min"][0,0], r["z_max"][0,0]) == (194.2, 194.6)

def test_equal_levels_give_no_separator():
    r = compute_bounds(px(0, 1), np.array([195.0, 195.0]), np.zeros(2))
    assert r["n_conflict"][0,0] == 1

def test_bounds_widened_by_sigma():
    r = compute_bounds(px(0, 0, 1, 1), H, np.array([0, 0.1, 0.2, 0]))
    assert np.isclose(r["z_min"][0,0], 194.1) and np.isclose(r["z_max"][0,0], 194.8)

def test_always_water_has_upper_bound_only():
    r = compute_bounds(px(1, 1, 1, 1), H, S0)
    assert np.isnan(r["z_min"][0,0]) and r["z_max"][0,0] == 193.8

def test_nodata_is_ignored_not_land():          # Review Focus 2
    r = compute_bounds(px(255, 0, 1, 1), H, S0)
    assert r["obs_count"][0,0] == 3 and r["z_min"][0,0] == 194.2

def test_never_observed_is_nan():
    r = compute_bounds(px(255, 255, 255, 255), H, S0)
    assert np.isnan(r["z_min"][0,0]) and np.isnan(r["z_max"][0,0])
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implementować. **Step 4:** Run → PASS.
- [ ] **Step 5:** Uruchomić `07_bottom_model.py` dla `all`, `pre_flood`, `post_flood`; wypisać medianę i odsetek |Δz| > suma niepewności między `pre_flood` a `post_flood` (wejście do decyzji z spec §6a, która wersja trafia do aplikacji). Weryfikacja: w QGIS `bottom_z.tif` nakłada się na ortofotomapę; wypisać liczbę i odsetek pikseli z konfliktami (raport sprzeczności, kryterium M4), `h_min_obs`, `h_max_obs`; PNG `qc/bottom_z.png` i `qc/bottom_unc.png`.
- [ ] **Step 6:** Commit: `feat: bottom model from inundation intervals`.

---

### Task 12: Odtwarzalność i notatki do nauki

**Files:**
- Create: `pipeline/Makefile` (cele `osm s2 labels rf classify shorelines bulletins levels bottom all`, każdy = `uv run python NN_*.py`)
- Create: `docs/nauka/M1-dane.md`, `docs/nauka/M2-klasyfikacja.md`, `docs/nauka/M3-poziomy.md`, `docs/nauka/M4-model-dna.md`
- Modify: `README.md` (sekcja „Pipeline krok po kroku”)

- [ ] **Step 1:** `uv run pytest -q` w `pipeline/` → wszystkie testy PASS.
- [ ] **Step 2:** `make bottom` na istniejącym cache przechodzi bez błędów (sprawdza, że skrypty są wznawialne).
- [ ] **Step 3:** Napisać notatki: każda zawiera *co powstało (pliki)*, *liczby z tego przebiegu* (sceny usable, OA/Kappa/F1 RF vs Otsu vs SCL, liczba scen B/C, zakres `h_t`, odsetek konfliktów), *dlaczego tak* oraz **5–8 pytań, które może zadać prowadzący, z odpowiedziami** (np. „Dlaczego MNDWI, a nie NDWI?”, „Skąd wiesz, że RF nie uczy się na danych testowych?”, „Co się dzieje z pikselem zawsze zalanym?”).
- [ ] **Step 4:** Commit: `docs: pipeline learning notes M1–M4 and Makefile`.
