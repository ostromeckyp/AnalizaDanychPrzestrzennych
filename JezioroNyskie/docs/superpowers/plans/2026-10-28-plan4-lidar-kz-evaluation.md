# Plan 4: LiDAR (wariant A), mapa KŻ, wariant D, ocena dokładności, raport i docker compose — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Domknąć projekt „Mielizna”: poziom wody z LiDAR (wariant A), digitalizacja mapy KŻ (K1–K3), wariant D, pełna ocena dokładności (§7 briefu) i porównanie z KŻ (K5), warstwa żwirowni w aplikacji, `docs/raport.md` i uruchomienie jednym poleceniem (`docker compose up`).

**Architecture:** Pipeline zostaje liniowym ciągiem ponumerowanych skryptów (`pipeline/NN_*.py`) z logiką w `pipeline/mielizna/*.py` pokrytą testami na małych fiksturach (bez sieci). Nowe kroki: `02_fetch_nmt.py` (skorowidze WFS, arkusze NMT i LAZ) → `06b_lidar_levels.py` (epoki LiDAR, wariant A) → istniejące `06_water_levels.py` i `07_bottom_model.py` (A wchodzi przez mechanizm `overrides`, pierwszeństwo A > R > B > C już istnieje w `levels.PRECEDENCE`) → `09_kz_digitize.py` (K1–K3, żwirownia) → `08_evaluate.py` (§7) i `10_kz_compare.py` (K5, wariant D). Wyniki oceny trafiają do `data/processed/eval/*.json`, które backend czyta w `/api/meta`; raport `docs/raport.md` składa liczby z tych plików.

**Tech Stack:** Python 3.12 przez `uv` (pipeline i backend), `laspy[lazrs]` (LAZ), `pyproj` z siatkami GUGiK (PROJ network), `rasterio`, `geopandas`, `shapely`, `scipy`, `scikit-image`, `pypdf`; OCR przez CLI `tesseract` (jest w `/opt/homebrew/bin`, wywołanie `subprocess`, bez nowej zależności Pythona); backend FastAPI (plan 2); frontend React (plan 3); Docker Compose v2 (nginx dla frontu).

**Spec:** `docs/superpowers/specs/2026-10-26-mielizna-design.md` (§2 pkt 2, 3, 5, 8; §5 kroki 7–9; §6a) + `docs/BRIEF.md` (§4, §5 D2/D8, §6.3 A/D, §6.6 K1–K5, §7, §9, §10 M1b/M4/M4b/M7, §11, §12). Notatki stanu: `docs/nauka/M1–M6`, `docs/nauka/decyzje.md`.

## Global Constraints

- Katalog roboczy `JezioroNyskie/`; repo git to katalog nadrzędny. Gałąź `feat/plan4` od `main`.
- Komendy: pipeline `cd pipeline && uv run pytest -q` oraz cele `make`; backend `cd backend && uv run pytest -q`; frontend `cd frontend && npm test && npm run lint && npm run build`. Wszystkie muszą przechodzić na końcu każdego zadania, które dotyka danej części.
- **Testy bez sieci:** odpowiedzi WFS, nagłówki LAZ, wycinki NMT i mapy KŻ jako małe fikstury w `pipeline/tests/fixtures/`. Pobieranie i ciężkie liczenie tylko w skryptach `NN_*.py`, nigdy w testach.
- **Konwencja skryptów (spec §4):** każdy nowy skrypt i moduł zaczyna się docstringiem po polsku w czterech częściach: „Co robi”, „Dlaczego tak”, „Wejście → wyjście”, „Jak to obronić”. Jawne kroki numpy, nazwy jak w briefie (`h_t`, `z_min`, `z_max`, `h_sigma`). Komentarze po polsku, identyfikatory po angielsku.
- **CRS i siatka:** obliczenia w EPSG:2180, siatka modelu z `mielizna.grid.reference_grid()` (10 m, E 372 000–381 000, N 285 500–292 500). Wysokości docelowo w **PL-EVRF2007-NH**; każda wartość z innego układu niesie jawne pole `h_datum`.
- **Dane:** surowe do `data/raw/{nmt,lidar,kz}/` (poza gitem, każdy katalog z krótkim `README.md` opisującym źródło i sposób pobrania), pośrednie do `data/processed/{lidar,kz,eval}/`. Do gita trafiają tylko małe pliki w `data/reference/` (GCP, punkty QC, obrys żwirowni) oraz rysunki raportu w `docs/img/`.
- **Mapa KŻ — licencja (BRIEF §6.6):** każdy plik pochodny z mapy KŻ (`kz_*.gpkg`, `kz_gcp.csv`, `kz_spot_qc.csv`, `zwirownia.gpkg`, nakładki PNG) ma obok siebie (albo w metadanych GPKG) odwołanie do `data/reference/KZ_ZRODLO_I_WARUNKI.md`; w aplikacji przy warstwie żwirowni atrybucja „Obrys wg mapy KŻ Nysa (W. Wróblewski, 2023)”.
- **Unikanie przecieku:** (1) wariant A próbkuje NMT wyłącznie w blokach 500 m „kalibracyjnych”, a walidacja dna vs NMT liczy się wyłącznie w blokach „walidacyjnych” (szachownica bloków 500 m wyrównana do siatki modelu, `(i + j) % 2`); (2) walidacja dna vs punkty KŻ używa modelu z `h_t` A/B/R/C, a wariant D jest tylko kontrolą zgodności `h_t` (BRIEF §6.6 „Unikanie przecieku”, druga opcja).
- **KŻ — granice porównań (BRIEF §6.6):** model `pre_flood` (sceny do 31.08.2024), rzędne ≥ 192,5 m w metrykach głównych (niższe osobno), bez wnętrza obrysu żwirowni, agregacja w komórkach 50 m, zawsze raportowany bias.
- **Progi robocze (BRIEF):** georeferencja RMSE ≤ 5 m dobry, ≤ 10 m akceptowalny, > 10 m → tylko porównania zagregowane; błąd OCR ≤ 10 % na próbie ≥ 200 punktów; wariant D zgodny z A/B w ±0,2 m dla większości scen; |bias| > 0,5 m → najpierw przyczyna; M3: `h_sigma` wariantu A < 0,3 m.
- **A vs B (spec §6a):** gdy obie wartości istnieją i |A − B| > 0,2 m, `h_t` = A, a `scenes.json` przechowuje też `h_t_b` i `h_diff_ab`; nic nie jest uzgadniane na siłę.
- **Model w aplikacji (spec §6a):** domyślnie `all`; aplikacja przechodzi na `post_flood` tylko gdy ocena zmian (Task 8) pokaże istotną zmianę dna (udział pikseli z |Δz| > suma niepewności ≥ 5 % akwenu wspólnego). Decyzja zapisana w `data/processed/eval/model_choice.json` i czytana przez backend.
- Liczby w UI tylko z API (BRIEF §16.11); teksty UI po polsku; zasady warstw frontu z planu 3 (komponenty bez `src/api` i TanStack Query).
- Commity kończą się linią `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Skorowidze WFS ucinają i zaśmiecają wyniki:** odpowiedź obcięta przez `COUNT`, arkusze spoza jeziora z BBOX — lista arkuszy ma być kompletna (stronicowanie `STARTINDEX` aż do pustej strony) i odfiltrowana po geometrii. → test w Task 1.
2. **Czas GPS w LAZ:** „adjusted standard GPS time” (bit 0 `global_encoding` = 1, sekundy − 10⁹) vs „GPS week time” (bit = 0, brak daty) — zła interpretacja daje datę nalotu przesuniętą o lata albo udaje datę, której nie da się odczytać. → test w Task 2.
3. **Układy wysokości:** KRON86 (2011, 2017) vs EVRF2007 (2022, 2024) vs nieznany układ RZGW — każda rzędna przed porównaniem w EVRF2007, różnica A − B raportowana jako możliwy przesunięty układ, a nie „korygowana” po cichu. → testy w Task 2 i Task 3.
4. **Wariant A na brzegu z zaporą, pomostami i trzcinami:** próbki NMT z korony zapory, budowli albo roślinności zawyżają `h_t` — mediana, odrzucenie bufora zapory, minimalna liczba próbek i ich rozłożenie po obwodzie, `h_sigma` z rozrzutu. → test w Task 3.
5. **OCR mapy KŻ myli cyfry (193,0 ↔ 195,0 ↔ 198,0) i gubi przecinek:** kontrola koloru (niebieski < 195,0 ≤ czarny), zakres wiarygodny 185–200 m, odrzucenie wartości bez kropki-punktu; błędne odczyty nie mogą trafić do metryk K5 bez QC. → testy w Task 5 i Task 9.

---

### Task 1: Skorowidze GUGiK i pobranie NMT/LAZ (`02_fetch_nmt.py`)

**Files:**
- Create: `pipeline/mielizna/gugik.py`, `pipeline/02_fetch_nmt.py`, `data/raw/nmt/README.md`, `data/raw/lidar/README.md`
- Modify: `pipeline/pyproject.toml` (`laspy[lazrs]`, `pyproj`), `pipeline/Makefile` (cel `nmt`), `pipeline/config.yaml` (sekcja `lidar`)
- Test: `pipeline/tests/test_gugik.py`, fikstury `pipeline/tests/fixtures/wfs_page{1,2,3}.xml` (GML 3 obiekty, 2 obiekty, 0 obiektów; jeden obiekt poza jeziorem)

**Interfaces:**
- Produces:
  - `config.yaml`: `lidar: {epochs: [2011, 2017, 2022, 2024], wfs: {laz_evrf, laz_kron, nmt_evrf, nmt_kron}: <URL z BRIEF §5.1>, page_size: 100, shore_band_m: 300, laz_sheets_per_epoch: 4}`.
  - `gugik.fetch_index(url: str, bbox_2180: tuple, page_size: int, get=requests.get) -> gpd.GeoDataFrame` (kolumny z WFS: `godlo, akt_rok, char_przestrz, blad_sr_wys, uklad_h, format, url_do_pobrania`, geometria w EPSG:2180; stronicuje `STARTINDEX` do pustej strony).
  - `gugik.select_sheets(index: gpd.GeoDataFrame, area: shapely.Geometry, years: list[int]) -> gpd.GeoDataFrame` (przecięcie geometrii, `akt_rok ∈ years`, tylko arkusze z LiDAR — błąd śr. wys. ≤ 0,2 m; odrzuca NMT ze zdjęć lotniczych).
  - `gugik.pick_laz_sheets(sheets, lake: Polygon, n: int) -> gpd.GeoDataFrame` (n arkuszy z największym udziałem otwartej wody jeziora, rozłożonych — co najwyżej jeden arkusz na ćwiartkę obrysu, dopóki starcza).
  - Pliki: `data/raw/nmt/<rok>/<godlo>.<ext>`, `data/raw/lidar/<rok>/<godlo>.laz`, `data/processed/lidar/inventory.csv` (`kind, year, godlo, uklad_h, blad_sr_wys, path, bytes`).
  - Obszar NMT = pierścień `lake.boundary.buffer(shore_band_m)` (brzeg, gdzie wariant A próbkuje i gdzie jest strefa odsłonięta do walidacji).

- [ ] **Step 1: Write the failing tests**
```python
def test_fetch_index_pages_until_empty(fake_get):          # fikstury page1..3
    gdf = gugik.fetch_index("http://x/wfs", BBOX, page_size=3, get=fake_get)
    assert len(gdf) == 5 and fake_get.startindices == [0, 3, 6]
def test_select_sheets_drops_outside_and_photogrammetric():
    s = gugik.select_sheets(index, lake.buffer(300), years=[2011, 2024])
    assert set(s.godlo) == {"M-33-35-C-c-1-1", "M-33-35-C-c-1-2"}   # z fikstury
def test_pick_laz_sheets_spreads_over_quadrants():
    p = gugik.pick_laz_sheets(sheets, lake, n=4); assert len(p) == 4 and quadrants(p) == 4
```
- [ ] **Step 2:** Run `uv run pytest tests/test_gugik.py -q` → FAIL.
- [ ] **Step 3:** Implement `gugik.py` i `02_fetch_nmt.py` (pobieranie strumieniowe z wznowieniem — pomija istniejące pliki o tym samym rozmiarze; grzecznie 1 zapytanie/s; formaty ASC/XYZ NMT konwertuje do GeoTIFF EPSG:2180 przez `rasterio` i zapisuje z `uklad_h` w tagach).
- [ ] **Step 4:** Run testy → PASS. Uruchom `make nmt`; wypisz liczbę arkuszy i GB na epokę. Jeśli epoka nie ma arkuszy LiDAR nad jeziorem, zapisz to w `data/raw/lidar/README.md` (nie zgaduj innego źródła).
- [ ] **Step 5:** Commit `feat(pipeline): GUGiK index paging, NMT/LAZ fetch (02)`

---

### Task 2: Epoki LiDAR — data nalotu, poziom wody, układ wysokości

**Files:**
- Create: `pipeline/mielizna/lidar.py`, `pipeline/mielizna/datum.py`, `pipeline/06b_lidar_levels.py` (część „epoki”)
- Test: `pipeline/tests/test_lidar.py`, `pipeline/tests/test_datum.py`, fikstury `tiny_adjusted.laz` i `tiny_week.laz` (≤ 2000 punktów, tworzone w teście przez `laspy`)

**Interfaces:**
- Produces:
  - `lidar.flight_dates(path: Path) -> list[date]` — daty UTC z czasu GPS (adjusted standard: `t + 1e9` s od 1980-01-06, minus 18 s przestępnych); dla GPS week time zwraca `[]` i loguje ostrzeżenie (daty nie da się wiarygodnie odczytać).
  - `lidar.water_class(path: Path, lake_core: Polygon) -> int` — klasa o największej liczbie punktów wewnątrz rdzenia jeziora (obrys − 200 m) z wyłączeniem klasy 2; BRIEF mówi „klasa 8”, ASPRS ma wodę = 9 — wartość ustala dane, a wynik trafia do `epochs.csv`.
  - `lidar.water_level(path, lake_core, cls) -> tuple[float, float, int]` = (mediana z, IQR, n) punktów tej klasy w rdzeniu.
  - `datum.kron86_to_evrf2007(x: float, y: float) -> float` — przesunięcie [m] do dodania do wysokości KRON86, z różnicy quasi-geoid `pl_gugik_geoid2011-PL-KRON86-NH` i `pl_gugik_geoid2021-PL-EVRF2007-NH` przez `pyproj` (siatki PROJ CDN, `pyproj.network.set_network_enabled(True)` tylko w skrypcie; w teście siatki z cache albo wartość wstrzyknięta).
  - `data/processed/lidar/epochs.csv`: `epoch, date, date_span_days, h_water, h_water_evrf, h_iqr, n_points, water_class, uklad_h, datum_offset`.

- [ ] **Step 1: Write the failing tests**
```python
def test_flight_date_from_adjusted_gps(tmp_path):     # 1980-01-06 + (2.0e8 + 1e9 − 18) s
    assert lidar.flight_dates(make_laz(tmp_path, gps=[2.0e8], adjusted=True)) == [date(2018, 1, 14)]
def test_week_time_gives_no_date(tmp_path):
    assert lidar.flight_dates(make_laz(tmp_path, gps=[3600.0], adjusted=False)) == []
def test_water_class_and_level(tmp_path):
    p = make_laz(tmp_path, classes={9: 194.31, 2: 200.0}, inside=lake_core)
    assert lidar.water_class(p, lake_core) == 9
    h, iqr, n = lidar.water_level(p, lake_core, 9); assert h == pytest.approx(194.31, abs=0.01) and n > 100
def test_kron_to_evrf_offset_magnitude():
    off = datum.kron86_to_evrf2007(376000, 289000)
    assert 0.05 <= abs(off) <= 0.30          # BRIEF: „rzędu kilkunastu cm”
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (czytanie LAZ fragmentami `laspy.open(...).chunk_iterator`, bez wczytywania całej chmury). Jeśli siatek geoidy nie da się pobrać, skrypt kończy się błędem z instrukcją (nie przyjmuje stałej z głowy).
- [ ] **Step 4:** Run → PASS. Uruchom część epok `06b_lidar_levels.py --epochs-only`; wpisz do `docs/nauka/M7-lidar-kz.md` (szkic) tabelę epok. Kontrola: każda epoka ma jedną datę lub zakres ≤ 14 dni; poziomy w zakresie 192–199 m.
- [ ] **Step 5:** Commit `feat(pipeline): LiDAR epochs — flight date, water level, KRON86→EVRF2007`

---

### Task 3: Wariant A per scena i włączenie do `scenes.json`

**Files:**
- Create: `pipeline/mielizna/variant_a.py`, `pipeline/mielizna/blocks.py`
- Modify: `pipeline/06b_lidar_levels.py` (część „sceny”), `pipeline/06_water_levels.py` (overrides = `known_levels.csv` + `levels_a.csv`; kolumny `h_t_b`, `h_diff_ab`), `pipeline/mielizna/levels.py` (`write_scenes_json` zapisuje nowe kolumny), `pipeline/Makefile` (cel `levels-a`; `levels` zależy od `levels_a.csv`)
- Test: `pipeline/tests/test_variant_a.py`, `pipeline/tests/test_blocks.py`, rozszerzenie `pipeline/tests/test_levels.py`

**Interfaces:**
- Consumes: `epochs.csv` (Task 2), NMT z Task 1, linie brzegowe `shorelines.gpkg` (plan 1), `levels.assign_levels(... overrides ...)`.
- Produces:
  - `blocks.block_role(x: np.ndarray, y: np.ndarray, grid: Grid, size_m: float = 500) -> np.ndarray[str]` → `"calib"` gdy `(i + j) % 2 == 0`, inaczej `"valid"` (i, j = indeksy bloku od narożnika siatki).
  - `variant_a.sample_shoreline(line: LineString, step_m: float = 5) -> np.ndarray` (punkty co 5 m).
  - `variant_a.level_from_dem(xy: np.ndarray, dem_z: np.ndarray, h_lidar: float, *, min_above: float = 0.10, min_n: int = 50, min_sectors: int = 3) -> tuple[float, float, int] | None` → (`h_t` = mediana z punktów z `dem_z > h_lidar + min_above`, `h_sigma` = 1,4826·MAD, n); `None`, gdy n < `min_n` albo punkty zajmują < `min_sectors` z 8 sektorów kątowych wokół środka jeziora.
  - `variant_a.choose_epoch(epochs: pd.DataFrame, scene_date: date, h_guess: float) -> pd.Series | None` — epoki z `h_water_evrf < h_guess − 0,2`, z nich najbliższa w czasie (`h_guess` = h_t sceny z B/R/C sprzed tego kroku; brak → `None`).
  - Wykluczenia z próbkowania: bufor 150 m wokół zapory (linia `man_made=dam` z OSM albo obrys z `lake.gpkg`, warstwa `dam` — jeśli brak, dopisać pobranie do `03_fetch_osm.py`), bloki `"valid"`, piksele NMT bez danych.
  - `data/processed/levels_a.csv` w formacie `known_levels.csv` (`start=end=data sceny, h, sigma, method=A, source="LiDAR <epoka> NMT, n=<n>"`) + `levels_a_detail.csv` (`date, epoch, n, sectors, h_sigma, rejected_reason`).
  - `scenes.json`: dla scen z A i B: `h_t_b`, `h_diff_ab = h_t − h_t_b`.
  - `h_datum` sceny A = `"PL-EVRF2007-NH"`.

- [ ] **Step 1: Write the failing tests**
```python
def test_checkerboard_blocks():
    r = blocks.block_role(np.array([372100, 372600]), np.array([285600, 285600]), GRID)
    assert list(r) == ["calib", "valid"]
def test_level_from_dem_median_and_sigma():
    xy, z = ring_points(n=400, z=195.40, noise=0.05, sectors=8)
    h, s, n = variant_a.level_from_dem(xy, z, h_lidar=194.0); assert h == pytest.approx(195.40, abs=0.02) and s < 0.1
def test_level_from_dem_ignores_dam_crest_outliers():      # 10% punktów na 199,0
    h, _, _ = variant_a.level_from_dem(*with_outliers(), h_lidar=194.0); assert h == pytest.approx(195.40, abs=0.05)
def test_level_from_dem_rejects_one_sided_coverage():
    assert variant_a.level_from_dem(*one_sector(), h_lidar=194.0) is None
def test_choose_epoch_needs_lower_lidar_level():
    assert variant_a.choose_epoch(EPOCHS, date(2023, 6, 1), h_guess=194.1) is None   # wszystkie epoki ≥ 193,9
def test_assign_levels_keeps_b_when_a_wins():          # test_levels.py
    df = assign_levels(..., overrides=overrides_with_A_on_bulletin_day)
    row = df[df.date == D].iloc[0]; assert row.h_method == "A" and row.h_t_b == pytest.approx(195.10) and abs(row.h_diff_ab) > 0.2
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS; `make levels-a levels bottom`. Zapisz w notatce: liczba scen A, rozkład `h_sigma` (kryterium M3 < 0,3 m), mediana i rozrzut `h_diff_ab` (podejrzenie przesunięcia układu RZGW — tylko raport).
- [ ] **Step 5:** Commit `feat(pipeline): variant A water levels from LiDAR DEM (calib blocks only)`

---

### Task 4: Mapa KŻ — georeferencja (K1)

**Files:**
- Create: `pipeline/mielizna/kz.py` (część georeferencji), `pipeline/09_kz_digitize.py` (podkomenda `georef`), `data/reference/kz_gcp.csv`
- Modify: `pipeline/Makefile` (cel `kz-georef`)
- Test: `pipeline/tests/test_kz_georef.py`

**Interfaces:**
- Produces:
  - `kz.extract_image(pdf: Path, out: Path) -> tuple[int, int]` — największy obraz strony przez `pypdf` → PNG (oczekiwane 9867 × 4791).
  - `data/reference/kz_gcp.csv`: `id, px, py, lon, lat, role` (`role ∈ {fit, check}`; ≥ 12 `fit` rozłożonych po całej mapie, ≥ 4 `check`; współrzędne z przecięć siatki stopni/minut opisanych na krawędziach mapy). Punkty wskazuje implementer: wycina fragmenty obrazu wokół przecięć, ogląda je i zapisuje piksele; nagłówek pliku odsyła do `KZ_ZRODLO_I_WARUNKI.md`.
  - `kz.fit_transform(gcp: pd.DataFrame, kind: Literal["affine", "poly2"]) -> KzTransform` z `px_to_2180(px, py) -> (x, y)` i `rmse_check: float`, `rmse_fit: float`.
  - `09_kz_digitize.py georef` → wybiera `kind` z mniejszym `rmse_check`, zapisuje `data/processed/kz/kz_map_2180.tif` (2 m, EPSG:2180, przez odwrotne mapowanie `scipy.ndimage.map_coordinates`), `data/processed/kz/kz_meta.json` (`kind, rmse_fit, rmse_check, n_fit, n_check, dam_offset_m, verdict ∈ {good, acceptable, aggregated_only}`).
  - Dodatkowa kontrola: odległość korony zapory na mapie od linii zapory z OSM (`dam_offset_m`).

- [ ] **Step 1: Write the failing tests**
```python
def test_affine_recovers_known_transform():
    gcp = synthetic_gcp(affine=A_TRUE, noise_px=0.5, n_fit=12, n_check=4)
    t = kz.fit_transform(gcp, "affine"); assert t.rmse_check < 2.0
def test_poly2_beats_affine_on_curved_distortion():
    gcp = synthetic_gcp(poly2=P_TRUE, n_fit=16, n_check=6)
    assert kz.fit_transform(gcp, "poly2").rmse_check < kz.fit_transform(gcp, "affine").rmse_check
def test_verdict_thresholds():
    assert kz.verdict(4.9) == "good" and kz.verdict(9.9) == "acceptable" and kz.verdict(10.1) == "aggregated_only"
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; zebrać GCP z obrazu. **Step 4:** Run → PASS; `make kz-georef`; obejrzeć nakładkę `data/processed/kz/qc_georef.png` (mapa KŻ półprzezroczysta na obrysie OSM). Wynik RMSE i werdykt do notatki.
- [ ] **Step 5:** Commit `feat(pipeline): KŻ map georeferencing with holdout GCPs (K1)`

---

### Task 5: Punkty rzędnych z OCR i narzędzie kontroli (K2)

**Files:**
- Modify: `pipeline/mielizna/kz.py` (OCR), `pipeline/09_kz_digitize.py` (podkomenda `spots`), `pipeline/tools/label_server.py` + `pipeline/tools/label.html` (tryb `/kz`), `pipeline/Makefile` (cele `kz-spots`, `kz-qc-ui`)
- Test: `pipeline/tests/test_kz_ocr.py` (fikstura: wycinek 600 × 400 px z mapy z 5 znanymi rzędnymi, `pipeline/tests/fixtures/kz_crop.png`)

**Interfaces:**
- Produces:
  - `kz.ocr_tiles(img: np.ndarray, tile: int = 1200, overlap: int = 100) -> pd.DataFrame` — `tesseract <png> - --psm 11 tsv` po kaflach; kolumny `text, conf, left, top, width, height` w pikselach całego obrazu, bez duplikatów z zakładek.
  - `kz.parse_spot(text: str) -> float | None` — wzorzec `\.?\d{3},\d` (BRIEF §6.6), akceptuje 185,0–200,0, inaczej `None`.
  - `kz.spot_anchor(img, box) -> tuple[float, float] | None` — środek kropki (ciemny blob 2–12 px) po lewej stronie liczby; brak kropki → `None` (wartość odrzucona).
  - `kz.text_color(img, box) -> Literal["blue", "black", "other"]`; `kz.color_consistent(z, color) -> bool` (niebieski ⇔ z < 195,0).
  - `data/processed/kz/kz_spot_ocr.gpkg`: `id, z, color, conf, color_ok, px, py`, geometria EPSG:2180 (z `KzTransform`).
  - Narzędzie `make kz-qc-ui` (`http://localhost:8765/kz`): losowa próba warstwowa (połowa z `color_ok == False` lub `conf < 80`, połowa reszty), jeden punkt naraz — wycinek mapy 200 × 200 px z krzyżykiem i odczytana liczba; klawisze: `Enter` = poprawne, wpisanie liczby = korekta, `X` = to nie jest rzędna, `?` = pomiń. Wynik `data/reference/kz_spot_qc.csv` (`id, ocr_z, qc ∈ {ok, corrected, rejected, skip}, z_qc`).
  - `kz.ocr_error_rate(qc: pd.DataFrame) -> tuple[float, int]` = (udział `corrected + rejected` wśród ocenionych, liczba ocenionych), z wagami warstw (żeby nadreprezentacja podejrzanych nie zawyżała błędu).

- [ ] **Step 1: Write the failing tests**
```python
@pytest.mark.parametrize("s,z", [("194,3", 194.3), (".193,5", 193.5), ("1943", None), ("201,0", None), ("abc", None)])
def test_parse_spot(s, z): assert kz.parse_spot(s) == z
def test_color_rule(): assert kz.color_consistent(194.9, "blue") and not kz.color_consistent(195.2, "blue")
def test_ocr_on_crop_finds_known_spots():                    # pomijany, gdy brak tesseract w PATH
    df = kz.ocr_tiles(load("kz_crop.png")); zs = {kz.parse_spot(t) for t in df.text} - {None}
    assert {193.8, 194.6, 195.3} <= zs
def test_error_rate_is_stratum_weighted(): assert kz.ocr_error_rate(QC)[0] == pytest.approx(0.06, abs=0.01)
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS; `make kz-spots`; podać liczbę punktów, udział `color_ok`.
- [ ] **Step 5:** Commit `feat(pipeline): KŻ spot heights OCR and QC tool (K2)`
- [ ] **Krok ręczny autora (blokuje Task 9, nie blokuje Task 6–8):** `make kz-qc-ui`, ocenić ≥ 200 punktów (ok. 20 min). Kontroler pyta autora w tym miejscu i kontynuuje Task 6–8; Task 9 zaczyna się dopiero, gdy `kz_spot_qc.csv` ma ≥ 200 ocen.

---

### Task 6: Poziomice KŻ (K3) i obrys żwirowni

**Files:**
- Modify: `pipeline/mielizna/kz.py` (poziomice), `pipeline/09_kz_digitize.py` (podkomendy `contours`, `gravel`)
- Create: `data/reference/zwirownia_vertices.csv`, wynik `data/reference/zwirownia.gpkg`
- Test: `pipeline/tests/test_kz_contours.py`

**Interfaces:**
- Produces:
  - `kz.color_mask(img, rgb: tuple[int, int, int], tol: int) -> np.ndarray[bool]`; kolory linii 192,5 m i 195,0 m ustala implementer z obrazu i zapisuje w `config.yaml: kz.contour_colors` (z komentarzem, skąd).
  - `kz.mask_to_lines(mask, min_len_px: int = 80) -> list[LineString]` — szkielet (`skimage.morphology.skeletonize`), łączenie w linie, odrzucenie krótkich fragmentów (linie przerywane „orientacyjne” rozpadają się na krótkie odcinki i wypadają — tak ma być, BRIEF K3).
  - `data/processed/kz/kz_contours.gpkg`: `level ∈ {192.5, 195.0}`, LineString w EPSG:2180; obrazek kontrolny `qc_contours.png` (linie na mapie KŻ) oglądany przez implementera; fragmenty ewidentnie błędne (napisy, ramki) usuwa lista `kz.contour_drop_ids` w `config.yaml`.
  - `data/reference/zwirownia_vertices.csv` (`px, py` wierzchołki obrysu rejonu eksploatacji kruszywa wskazane na mapie KŻ) → `zwirownia.gpkg` (Polygon EPSG:2180, atrybuty `source`, `licence_ref`).

- [ ] **Step 1: Write the failing tests**
```python
def test_mask_to_lines_drops_dashed_segments():
    m = draw_solid_and_dashed()                    # linia ciągła 400 px + przerywana 10×30 px
    lines = kz.mask_to_lines(m, min_len_px=80); assert len(lines) == 1 and lines[0].length > 350
def test_gravel_polygon_valid_and_inside_lake():
    g = kz.vertices_to_polygon(VERTS, T_AFFINE); assert g.is_valid and g.within(LAKE_FIXTURE.buffer(50))
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; ustalić kolory i obrys żwirowni. **Step 4:** Run → PASS; `09_kz_digitize.py contours gravel`; obejrzeć `qc_contours.png`.
- [ ] **Step 5:** Commit `feat(pipeline): KŻ contours 192.5/195.0 and gravel-pit outline (K3)`

---

### Task 7: Wariant D — dopasowanie powierzchni KŻ do linii brzegowych

**Files:**
- Create: `pipeline/mielizna/variant_d.py`
- Modify: `pipeline/10_kz_compare.py` (nowy; podkomenda `variant-d`), `pipeline/mielizna/levels.py` (`write_scenes_json`: `h_t_d`, `h_diff_d`)
- Test: `pipeline/tests/test_variant_d.py`

**Interfaces:**
- Consumes: `kz_spot_ocr.gpkg` (lub po QC: punkty z `qc ∈ {ok, corrected}`), `kz_contours.gpkg`, `zwirownia.gpkg`, `shorelines.gpkg`, `scenes.json`.
- Produces:
  - `variant_d.kz_surface(spots: gpd.GeoDataFrame, contours: gpd.GeoDataFrame, grid: Grid) -> np.ndarray` — TIN (`scipy.interpolate.griddata`, linear) z punktów i wierzchołków poziomic, NaN poza otoczką i w żwirowni.
  - `variant_d.fit_level(shore: LineString, surface: np.ndarray, grid: Grid, levels: np.ndarray) -> tuple[float, float]` → (h, średnia odległość [m]) minimalizujące średnią odległość punktów linii brzegowej (co 10 m, poza żwirownią) od poziomicy powierzchni na rzędnej h (`skimage.measure.find_contours`); siatka `levels = arange(192.5, 198.0 + 1e-9, 0.05)`.
  - `scenes.json`: `h_t_d`, `h_diff_d = h_t_d − h_t` (kontrola, nigdy źródło `h_t`).
  - `data/processed/eval/variant_d.json`: `n_scenes, share_within_0_2, median_abs_diff, by_method {A, B, R, C}`.

- [ ] **Step 1: Write the failing tests**
```python
def test_fit_level_on_cone_surface():
    surf = cone(grid, z_center=190.0, slope=0.002); shore = circle_at_level(surf, 195.0)
    h, d = variant_d.fit_level(shore, surf, GRID, np.arange(192.5, 198.0, 0.05)); assert h == pytest.approx(195.0, abs=0.05) and d < 10
def test_surface_nan_in_gravel(): assert np.isnan(variant_d.kz_surface(SPOTS, CONT, GRID)[gravel_rc]).all()
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS; uruchom `10_kz_compare.py variant-d`; liczby do notatki.
- [ ] **Step 5:** Commit `feat(pipeline): variant D water level check from KŻ surface`

---

### Task 8: Ocena dokładności (§7) i decyzja o modelu w aplikacji (`08_evaluate.py`)

**Files:**
- Create: `pipeline/mielizna/evaluate.py`, `pipeline/08_evaluate.py`
- Modify: `pipeline/Makefile` (cel `evaluate`)
- Test: `pipeline/tests/test_evaluate.py`

**Interfaces:**
- Consumes: model dna `data/processed/model/{all,pre_flood,post_flood}/` (`bottom.read_model`), NMT i `epochs.csv` (Task 1–2), `blocks.block_role` (Task 3), `scenes.json`, `known_levels.csv`, `rf_metrics.json`.
- Produces (`data/processed/eval/`):
  - `bottom_vs_nmt.json` — dla każdej epoki: piksele modelu (10 m, NMT uśredniony do 10 m) w blokach `"valid"`, gdzie NMT > `h_water_evrf` epoki + 0,1 m i model ma `z`: `n, mae, rmse, bias, share_in_bounds` (NMT ∈ [z_min, z_max]); osobno `all` dla modelu `all`.
  - `levels.json` — A vs B (`n, mae, rmse, bias`), A/B/C vs punkt kontrolny R 2025 (sceny 28.04–12.05.2025), punkt 12.09.2024 (194,70 m), rozkład `h_sigma` per metoda.
  - `bottom_change.json` — `pre_flood` vs `post_flood`: Δz tam, gdzie oba mają `z`; `share_significant` = udział pikseli z |Δz| > `unc_pre + unc_post`; histogram.
  - `model_choice.json` — `{"period": "all" | "post_flood", "reason": "...", "share_significant": x}` wg progu 5 % z Global Constraints.
  - `mask.json` — przepisane z `rf_metrics.json` metryki RF/Otsu/SCL (OA, Kappa, F1 wody, BA) dla raportu.
  - Rysunki do `docs/img/eval-*.png`: histogram błędów dna vs NMT, wykres poziom–powierzchnia z metodami A/B/C/R, mapa niepewności, mapa Δz.
  - `evaluate.metrics(pred: np.ndarray, ref: np.ndarray) -> dict` (`n, mae, rmse, bias`), `evaluate.share_in_bounds(ref, zmin, zmax) -> float` (NaN w `z_min` = brak dolnej granicy, wtedy liczy tylko `ref ≤ z_max`).

- [ ] **Step 1: Write the failing tests**
```python
def test_metrics_basic(): assert evaluate.metrics(np.array([1., 2.]), np.array([1.5, 1.5])) == {"n": 2, "mae": 0.5, "rmse": 0.5, "bias": 0.0}
def test_share_in_bounds_open_lower(): assert evaluate.share_in_bounds(np.array([1., 5.]), np.array([np.nan, 0.]), np.array([2., 2.])) == 0.5
def test_only_valid_blocks_are_scored():
    r = evaluate.bottom_vs_dem(MODEL, DEM, h_water=194.0, roles=ROLES_ALL_CALIB); assert r["n"] == 0
def test_model_choice_threshold():
    assert evaluate.choose_model(0.049)["period"] == "all" and evaluate.choose_model(0.05)["period"] == "post_flood"
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS; `make evaluate`; kluczowe liczby do notatki.
- [ ] **Step 5:** Commit `feat(pipeline): accuracy evaluation (§7) and app model choice`

---

### Task 9: Porównanie z mapą KŻ (K5)

**Files:**
- Modify: `pipeline/10_kz_compare.py` (podkomendy `points`, `contours`, `overlay`), `pipeline/mielizna/kz.py` (`load_qc_spots`)
- Test: `pipeline/tests/test_kz_compare.py`

**Interfaces:**
- Consumes: `kz_spot_ocr.gpkg` + `data/reference/kz_spot_qc.csv` (krok ręczny po Task 5), `kz_contours.gpkg`, `zwirownia.gpkg`, model `pre_flood`, `kz_meta.json.verdict`, `evaluate.metrics`.
- Produces:
  - `kz.load_qc_spots(ocr, qc) -> gpd.GeoDataFrame` — tylko punkty sprawdzone (`ok`, `corrected` z `z_qc`) oraz niesprawdzone z `color_ok` i `conf ≥ 80`; kolumna `checked: bool`; `rejected` nigdy.
  - `data/processed/eval/kz_points.json` — metryki (`n, mae, rmse, bias, share_in_bounds`) dla pasm `[192.5, 195.0)`, `[195.0, NPP)`, `≥ NPP` (NPP z `kz_pojemnosc_rzedna.csv` jak w backendzie) i osobno `< 192.5` (orientacyjne); bez żwirowni; przy werdykcie `aggregated_only` — porównanie w komórkach 50 m (mediana punktów vs mediana `z` modelu), przy `good/acceptable` — komórka 10 m modelu pod punktem.
  - `data/processed/eval/kz_contours.json` — dla 192,5 i 195,0: poziomica modelu (`find_contours` na `z` pre_flood) vs KŻ: średnia odległość (symetryczna) i Hausdorff [m].
  - `go_no_go`: `|bias| > 0.5` → `"investigate"` z listą sprawdzonych przyczyn (układ wysokości: bias vs `datum_offset`; dno z 2023; sposób pomiaru) w polu `notes`.
  - `docs/img/kz-overlay.png` — mapa KŻ półprzezroczysta pod strefami modelu i poziomicami, z podpisem źródła i warunków.

- [ ] **Step 1: Write the failing tests**
```python
def test_rejected_spots_never_scored(): assert "r1" not in set(kz.load_qc_spots(OCR, QC).id)
def test_points_banded_and_gravel_excluded():
    r = compare_points(SPOTS, MODEL, GRAVEL, npp=195.9); assert set(r) >= {"192.5-195.0", "195.0-npp", "npp+", "below_192.5"} and r["192.5-195.0"]["n"] == 3
def test_symmetric_mean_distance_of_parallel_lines(): assert mean_distance(line_y0, line_y10) == pytest.approx(10.0)
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS; `10_kz_compare.py points contours overlay`; wnioski do notatki.
- [ ] **Step 5:** Commit `feat(pipeline): KŻ comparison — points, contours, overlay (K5)`

---

### Task 10: Backend i frontend — wyniki oceny, żwirownia, wybór modelu

**Files:**
- Modify: `backend/app/data.py` (wczytanie `eval/*.json`, `zwirownia.gpkg`, `model_choice.json`), `backend/app/settings.py` (`MIELIZNA_PERIOD` domyślnie z `model_choice.json`, zmienna środowiskowa nadal wygrywa), `backend/app/schemas.py`, `backend/app/main.py`, `backend/app/point.py`, `backend/openapi.json`
- Modify: `frontend/src/api/schema.ts` (`npm run gen:api`), `frontend/src/test/fixtures.ts`, `src/vm/useMethodVm.ts`, `src/vm/usePointVm.ts`, `src/vm/useMapPageVm.ts` (nowa warstwa), `src/components/map/{MapView.tsx,layers.ts,types.ts}`, `src/components/panel/LayersControl.tsx`, `src/components/popup/PointPopup.tsx`
- Test: `backend/tests/test_api_meta.py`, `backend/tests/test_api_gravel.py`, `backend/tests/test_api_point.py`; frontend testy odpowiednich plików

**Interfaces:**
- Produces:
  - `/api/meta.accuracy` rozszerzone o `bottom_rmse_nmt: float | null`, `bottom_bias_nmt: float | null`, `bottom_in_bounds_nmt: float | null`, `kz_rmse: float | null`, `kz_bias: float | null`, `levels_mae_ab: float | null`, `variant_d_within_0_2: float | null` (null, gdy plik oceny nie istnieje — backend startuje bez plików oceny).
  - `/api/meta.model_period` (`"all" | "pre_flood" | "post_flood"`) i `model_period_reason: str`.
  - `GET /api/gravel` → GeoJSON FeatureCollection (EPSG:4326, 1 obiekt, `properties: {source, attribution}`), `404` gdy brak pliku.
  - `/api/point`: pole `gravel: bool`.
  - Front: warstwa „Dno zmienne (eksploatacja kruszywa)” (obrys przerywany, `--danger`), przełącznik w `LayersControl` (lista i chipy), atrybucja „Obrys wg mapy KŻ Nysa (W. Wróblewski, 2023)” w kontrolce atrybucji; popup z `gravel: true` dopisuje wiersz ostrzeżenia „Dno zmienne (eksploatacja kruszywa) — model może być nieaktualny.” (`role="note"`); strona `/metoda`: kafel „RMSE dna” = `fmtM(bottom_rmse_nmt)` z dopiskiem „vs NMT LiDAR, bloki walidacyjne”, gdy liczba jest, inaczej dotychczasowe „w przygotowaniu”; krok 03 opisuje wariant A jako działający (z liczbą scen A z `n_scenes_by_method`), nowy kafel „Zgodność z mapą KŻ” (`kz_bias`, `kz_rmse`) z dopiskiem o warunkach mapy.

- [ ] **Step 1: Write the failing tests**
```python
def test_meta_accuracy_nulls_without_eval_files(client_no_eval):
    a = client_no_eval.get("/api/meta").json()["accuracy"]; assert a["bottom_rmse_nmt"] is None and a["rf_oa"] > 0
def test_gravel_geojson_and_point_flag(client):
    assert client.get("/api/gravel").json()["features"][0]["geometry"]["type"] == "Polygon"
    assert client.get("/api/point", params={**INSIDE_GRAVEL, "h": 195.0}).json()["gravel"] is True
def test_period_from_model_choice(tmp_data): assert create_app(...).state.settings.period == "post_flood"
```
```ts
it('popup adds gravel warning row', () => { expect(toPopupModel({ ...pointModel, gravel: true }, meta).rows.at(-1)?.term).toMatch(/Dno zmienne/); });
it('RMSE tile shows value when present, pending otherwise', () => { /* dwa przypadki */ });
it('gravel layer toggled via layout visibility', () => { /* MapView, visible.gravel=false → setLayoutProperty('gravel','visibility','none') */ });
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (backend: eksport `openapi.json`; front: `npm run gen:api`, test architektury pozostaje zielony). **Step 4:** Run backend + frontend suites → PASS.
- [ ] **Step 5:** Commit `feat: evaluation results, gravel layer and model choice in API and UI`

---

### Task 11: `docker compose` — uruchomienie jednym poleceniem

**Files:**
- Create: `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `docker-compose.yml` (w `JezioroNyskie/`), `.dockerignore` (backend, frontend)
- Modify: `README.md` (sekcja „Uruchomienie”: `docker compose up --build`, adres `http://localhost:8080`)
- Test: `scripts/compose_smoke.sh`

**Interfaces:**
- Produces:
  - `backend`: obraz `python:3.12-slim` + `uv sync --frozen --no-dev`, `uvicorn app.main:app --host 0.0.0.0 --port 8000`; wolumin `./data/processed:/data/processed:ro` i `./data/reference:/data/reference:ro`, `MIELIZNA_DATA_DIR=/data`, `MIELIZNA_LIVE` przekazywane z `.env` (domyślnie `1`); `healthcheck` na `/api/meta`.
  - `frontend`: etap `node:22` (`npm ci && npm run build`) → `nginx:1.27-alpine` serwujący `dist/` z fallbackiem SPA (`try_files $uri /index.html`) i `location /api/ { proxy_pass http://backend:8000; }`; port `8080:80`; `depends_on: backend: condition: service_healthy`.
  - `scripts/compose_smoke.sh`: `docker compose up -d --build`, czeka na zdrowy backend (≤ 120 s), sprawdza `curl -fs localhost:8080/` (HTML z `lang="pl"`), `localhost:8080/api/meta` (JSON z `n_scenes`), `localhost:8080/historia` (SPA fallback 200), potem `docker compose down`; kod wyjścia ≠ 0 przy każdym błędzie.

- [ ] **Step 1: Write the failing smoke script** (najpierw sam skrypt) i uruchom → FAIL (brak plików compose).
- [ ] **Step 2:** Implement Dockerfile'e i compose. Wersje obrazów przypięte jak wyżej.
- [ ] **Step 3:** Run `bash scripts/compose_smoke.sh` → PASS; zmierz czas `/api/zones` przez nginx (kryterium BRIEF §10 M5 < 1 s, §11 ≤ 2 s) i zapisz w notatce.
- [ ] **Step 4:** Commit `feat: docker compose (backend + nginx frontend), smoke script`

---

### Task 12: Raport, notatka M7 i porządki repo

**Files:**
- Create: `docs/raport.md`, `docs/nauka/M7-lidar-kz.md` (rozwinięcie szkicu z Task 2–9), `LICENSE` (MIT, w `JezioroNyskie/`)
- Modify: `docs/nauka/decyzje.md` (sekcja „1d. Decyzje planu 4”, wpisy P4-Rx z ledgera), `README.md` (link do raportu, zrzut ekranu z `docs/img/m6-desktop-light.png`, licencje danych), `docs/BRIEF.md` §13 (odhaczyć rozstrzygnięte: data nalotu LiDAR, KRON86 → EVRF2007; dopisać wynik przy pozostałych tylko jako odnośnik do raportu)

**Interfaces:**
- Consumes: wszystkie `data/processed/eval/*.json`, `kz_meta.json`, `epochs.csv`, `rf_report.md`, `model_meta.json`, rysunki z `docs/img/`.
- Produces: `docs/raport.md` po polsku z sekcjami wymaganymi przez BRIEF §11 pkt 3: 1. Dane i CRS (tabela źródeł z licencjami: Copernicus, GUGiK, OSM ODbL, RZGW/Wody Polskie, KŻ z warunkami; liczba scen użytecznych i lista scen odrzuconych za lód/uszkodzenie z `config.yaml: exclude_dates` z powodami), 2. Klasyfikacja woda/ląd (wskaźnik, próg Otsu, RF, metryki maski), 3. Poziom wody `h_t` (warianty A/B/C/R/D, epoki LiDAR, układy wysokości, A vs B), 4. Model dna (przedziały zalania, sprzeczności, okresy, zmiany po powodzi i decyzja o modelu w aplikacji), 5. Ocena dokładności (tabela §7 wypełniona liczbami z `eval/*.json` — każda liczba z odnośnikiem do pliku), 6. Porównanie z mapą KŻ (K1–K5, go/no-go), 7. Aplikacja (zrzuty), 8. Ograniczenia (lista z notatek M1–M7 i ledgerów), 9. Odtwarzalność (`make` od zera, jedyne kroki ręczne: etykiety RF i QC punktów KŻ — oba w repo).
  - Test spójności: `pipeline/tests/test_report_numbers.py` — każda liczba w `raport.md` oznaczona `<!-- eval:plik.json:ścieżka.klucza -->` musi zgadzać się z wartością w pliku (zaokrąglenie do wyświetlonej liczby miejsc). Test pomijany, gdy brak `data/processed/eval/`.

- [ ] **Step 1: Write the failing test** `test_report_numbers.py` (parsuje znaczniki, porównuje) → FAIL (brak raportu).
- [ ] **Step 2:** Napisać raport, notatkę M7 (co powstało, liczby, pytania prowadzącego z odpowiedziami — m.in. „skąd data nalotu”, „dlaczego szachownica bloków”, „dlaczego D nie jest źródłem h_t”, „co znaczy bias względem KŻ”), decyzje, README, LICENSE.
- [ ] **Step 3:** Run `uv run pytest tests/test_report_numbers.py -q` → PASS; pełne suity pipeline, backend, frontend → PASS.
- [ ] **Step 4:** Commit `docs: accuracy report, M7 notes, licence and README`
