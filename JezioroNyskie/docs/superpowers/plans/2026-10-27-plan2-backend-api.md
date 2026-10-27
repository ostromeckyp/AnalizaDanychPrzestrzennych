# Plan 2: backend FastAPI (M5) z `/api/current-level` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend, który z produktów planu 1 (model dna, `scenes.json`, linie brzegowe, przystanie, krzywa powierzchnia↔poziom, RF) serwuje API z §8.2 briefu, obrazy warstw dna i niepewności oraz `/api/current-level` (najnowsza scena S2 → RF/Otsu → poziom), z kontraktem `openapi.json` dla frontendu (plan 3).

**Architecture:** Osobny projekt `uv` w `backend/` z zależnością ścieżkową (editable) na pakiet `mielizna` z `pipeline/`; cała logika domenowa w czystych funkcjach (`zones.py`, `point.py`, `layers.py`, `current.py`) testowanych na małym syntetycznym zbiorze danych, a `main.py` tylko spina endpointy. Bez bazy danych: przy starcie `data.py` wczytuje produkty do pamięci (siatka 900×700, ~0,6 mln pikseli). Reguła stref z §6.4 briefu jest w **jednej** funkcji, używanej przez `/api/zones`, `/api/point` i podsumowanie.

**Tech Stack:** Python 3.12 (uv), FastAPI, uvicorn, pydantic v2, cachetools, Pillow, rasterio, geopandas, shapely, pyproj, numpy, `mielizna` (plan 1); pytest + httpx (TestClient).

**Spec:** `docs/superpowers/specs/2026-10-26-mielizna-design.md` (§2 pkt 6, §3 „Backend”, §4) + `docs/BRIEF.md` (§6.4, §8.1–8.2, §16.4–16.11). Ustalenia z planu 1, które ten plan wykonuje: `.superpowers/sdd/2026-10-27-plan1-pipeline-model-dna/progress.md` wiersze 127, 132, 139–140 („PLAN 2 NOTE / PLAN 2 API”).

**Kolejne plany:** plan 3 frontend React (konsumuje `backend/openapi.json`), plan 4 LiDAR (wariant A) + mapa KŻ + ocena + raport + docker compose.

## Global Constraints

- Katalog roboczy `JezioroNyskie/`; repo git to katalog nadrzędny. Pracować na gałęzi `feat/backend` (od `main` po planie 1), nie na `main`.
- Backend: `backend/pyproject.toml`, `backend/.python-version` = `3.12`; `mielizna` przez `[tool.uv.sources] mielizna = { path = "../pipeline", editable = true }`. Uruchomienie: `cd backend && uv run uvicorn app.main:app`.
- Obliczenia w **EPSG:2180**; do frontu **EPSG:4326** (GeoJSON), obrazy warstw w **EPSG:3857** z narożnikami w lon/lat. `pyproj.Transformer.from_crs(..., always_xy=True)` wszędzie.
- Siatka modelu czytana z rastra (`transform`, `crs`), nie zaszyta; musi się równać `mielizna.grid.reference_grid()` (assert przy starcie).
- Model z pliku `data/processed/model/{period}/`; domyślny okres **`all`** (spec §6a).
- Poza modelem = `obs_count == 0 | obs_count == 65535 | flags == 255`. W modelu: NaN w `z_min` → −∞, NaN w `z_max` → +∞ (`bottom.read_model`, `meta["nan_semantics"]`). Bity flag 1/2/4/8/16 są opisowe; **bit 8 nie jest ostrzeżeniem** i nie wpływa na nic w API.
- Reguła stref (brief §6.4): `D_lo = h − z_max`, `D_hi = h − z_min`; **zbyt płytka** `D_hi < d` (w tym ląd przy h); **bezpieczna** `D_lo ≥ d + m − 1e-6`; **ryzykowna** reszta. Przy sprzeczności (bezpieczna i zbyt płytka naraz) wygrywa zbyt płytka.
- Parametry zaokrąglane do **0,05 m** przed liczeniem i przed kluczem cache: `round(x / 0.05) * 0.05`, potem `round(·, 2)`. Zakresy: `draft` 0,10–3,00, `margin` 0,00–1,00 (domyślnie 0,30), `h` w `[slider.min, slider.max]` z `/api/meta`; poza zakresem → 422.
- NPP i Max PP **nie są zaszyte jako rzędne**: `capacity_to_level(65.69)` (≈195,91) i `capacity_to_level(121.70)` (≈198,89) z tabeli KŻ; pojemności 65,69 / 121,70 mln m³ to stałe z briefu §4 z komentarzem źródła.
- Krzywa powierzchnia↔poziom dostaje **powierzchnię Otsu**, nigdy RF (`levels.load_area_level_curve`, R23). Scena z `qc_ok == False` nie publikuje poziomu, powierzchni ani linii brzegowej.
- JSON nigdy nie zawiera `NaN`/`Infinity`: nieskończone i NaN → `null`.
- Docstringi, komentarze, `docs/nauka/` po **polsku**, w formacie *Co robi · Dlaczego tak · Wejście → wyjście · Jak to obronić* dla każdego modułu `app/*.py`; identyfikatory po angielsku lub jak w briefie (`h_t`, `z_min`, `D_lo`).
- Testy nie łączą się z siecią: wyszukiwanie STAC i wczytywanie scen w `current.py` są wstrzykiwane. Testy na prawdziwych danych mają marker `real` i są pomijane, gdy brak `data/processed/model/all/`.
- Commity kończą się linią `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Obraz warstwy w złym układzie:** PNG w EPSG:2180 położony przez MapLibre jako `image` jest przesunięty i obrócony o ~1°. Użytkownik oczekuje, że kolor dna leży pod linią brzegową. → test w Task 8: znany piksel trafia w swoje lon/lat po reprojekcji do 3857.
2. **Zamiana osi lon/lat:** kliknięcie w punkt musi zwrócić wartości tego piksela, nie piksela z zamienionymi współrzędnymi. → test w Task 6 (środek znanego piksela → jego `z_min/z_max`) i w Task 4 (pierwsza współrzędna GeoJSON to lon ≈ 17,2).
3. **Parametry spoza siatki 0,05 i szum float** (`h=195.2300001`, `d+m` dokładnie równe `D_lo`): ten sam wynik i ten sam ETag co dla wartości zaokrąglonej; równość `D_lo == d + m` daje strefę bezpieczną. → testy w Task 3 i Task 5.
4. **Brak świeżej sceny lub awaria S2** (brak sieci, pusta odpowiedź STAC, chmury, uszkodzona radiometria, QC niezaliczone, lód zimą): `/api/current-level` odpowiada zawsze (200) ostatnią znaną wartością z datą i `stale`, a zadanie w tle nie umiera po wyjątku. → testy w Task 9 i Task 10.
5. **Wartości nieskończone i puste mianowniki w JSON:** punkt „zawsze zalany” ma `depth_max = null`, a nie `Infinity`; poziom tak niski, że akwen ma 0 pikseli, daje udziały 0, a nie NaN. → testy w Task 3 i Task 6.

---

### Task 1: `classify.analyze_scene` i nadpisanie katalogu danych (pipeline)

Odłożone z planu 1 (final review S1, S2). Skrypt 04 i backend mają liczyć scenę jedną funkcją.

**Files:**
- Modify: `pipeline/mielizna/classify.py` (nowa funkcja na końcu)
- Modify: `pipeline/04_classify.py:87-99` (pętla używa `analyze_scene`)
- Modify: `pipeline/mielizna/config.py` (`DATA_DIR` z env)
- Test: `pipeline/tests/test_classify.py`, `pipeline/tests/test_config.py` (nowy)

**Interfaces:**
- Produces:
  - `classify.analyze_scene(bands: dict, scl: np.ndarray, date, bundle: dict, aoi: np.ndarray, lake: np.ndarray, core: np.ndarray) -> dict` z kluczami: `mask`, `mask_otsu`, `proba` (uint8 H×W), `otsu_threshold`, `area_km2` (RF), `area_otsu_km2`, `lake_nodata_pct`, `local_cloud_pct` (float) oraz 5 kluczy z `scene_qc`. Najpierw `s2.check_radiometry(bands, valid_mask(bands, scl) & aoi, str(date))` (ValueError przepuszczany dalej).
  - `config.data_dir() -> Path`: `Path(os.environ["MIELIZNA_DATA_DIR"])`, gdy zmienna ustawiona, inaczej dotychczasowe `DATA_DIR`. `data_path` używa `data_dir()` przy każdym wywołaniu (nie przy imporcie).

- [ ] **Step 1: Write the failing tests**
```python
# test_classify.py — na istniejącej syntetycznej scenie z tego pliku (fixture sceny/bundle)
def test_analyze_scene_matches_parts(scene, bundle, aoi, lake, core):
    bands, scl, d = scene
    r = analyze_scene(bands, scl, d, bundle, aoi, lake, core)
    mask, proba, t = classify_scene_full(bands, scl, d, bundle, aoi, core)
    assert np.array_equal(r["mask"], mask) and np.array_equal(r["proba"], proba)
    assert r["otsu_threshold"] == t
    assert np.array_equal(r["mask_otsu"], otsu_scene_mask(bands, scl, aoi, core, t))
    assert r["area_otsu_km2"] == (r["mask_otsu"] == 1).sum() * PIXEL_KM2
    assert set(scene_qc(mask, r["mask_otsu"], core)) <= set(r)

def test_analyze_scene_rejects_corrupt_radiometry(scene, bundle, aoi, lake, core):
    bands, scl, d = scene
    bad = {k: np.full_like(v, 1e-4) for k, v in bands.items()}
    with pytest.raises(ValueError, match="radiometrically corrupt"):
        analyze_scene(bad, scl, d, bundle, aoi, lake, core)

# test_config.py
def test_data_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MIELIZNA_DATA_DIR", str(tmp_path))
    assert data_path("processed", "x.tif") == tmp_path / "processed" / "x.tif"
```
Jeśli w `test_classify.py` nie ma fixture'ów sceny o tych nazwach, dopisać je z istniejących pomocników tego pliku (scena ≥ 1000 ważnych pikseli, żeby `check_radiometry` działał).
- [ ] **Step 2:** Run `cd pipeline && uv run pytest tests/test_classify.py tests/test_config.py -v` → FAIL (import).
- [ ] **Step 3:** Implement `analyze_scene` (składa `check_radiometry`, `classify_scene_full`, `otsu_scene_mask`, `scene_quality`, `scene_qc`; `lake_nodata_pct` jak w 04: `100 * ((mask == 255) & lake).sum() / lake.sum()`) i `data_dir()`. W 04 zastąpić wiersze 90–99 wywołaniem `analyze_scene`; wiersz statystyk = wynik bez `mask/mask_otsu/proba` + `model_sha`.
- [ ] **Step 4:** Run cały pakiet `uv run pytest -q` → 182 + 3 testy PASS.
- [ ] **Step 5: Kontrola na prawdziwych danych:** jednorazowy skrypt w scratchpadzie liczy `analyze_scene` dla `2017-03-19`, `2024-09-06`, `2026-10-26` i porównuje z `data/processed/masks*/{d}.tif`, `proba/{d}.tif` i wierszem `classify_stats.csv`. Oczekiwane: maski identyczne bajt w bajt, liczby równe (|Δ| < 1e-12). Wynik wpisać do opisu commita.
- [ ] **Step 6: Commit** `refactor(classify): analyze_scene shared by 04 and backend; MIELIZNA_DATA_DIR`

---

### Task 2: Szkielet backendu i wczytanie produktów

**Files:**
- Create: `backend/pyproject.toml`, `backend/.python-version`, `backend/app/__init__.py`, `backend/app/settings.py`, `backend/app/data.py`
- Create: `backend/tests/conftest.py` (budowa małego zbioru danych), `backend/tests/test_data.py`
- Modify: `.gitignore` (`backend/.venv/`), `README.md` (sekcja „Backend”)

**Interfaces:**
- Produces:
  - `settings.Settings` (dataclass, z env): `data_dir: Path` (`MIELIZNA_DATA_DIR`, domyślnie `mielizna.config.data_dir()`), `period: str = "all"` (`MIELIZNA_PERIOD`), `live: bool = True` (`MIELIZNA_LIVE`, „0” wyłącza), `refresh_hours: float = 6` (`MIELIZNA_REFRESH_H`), `fresh_days: int = 10` (`MIELIZNA_FRESH_DAYS`). `settings.get_settings() -> Settings`.
  - `data.Products` (dataclass): `transform: Affine`, `crs: str`, `shape: tuple[int, int]`, `z_lo`, `z_hi` (float64, ±inf zamiast NaN, NaN poza modelem), `z`, `unc` (float32 jak w pliku), `obs_count` (uint16), `in_model` (bool), `meta: dict` (model_meta.json), `version: str` (`f"{period}-{meta['version']}"`), `scenes: list[dict]` (z `scenes.json` tylko `qc_ok` i `h_t is not None`, posortowane po dacie), `shorelines: GeoDataFrame` (EPSG:2180, tylko daty z `scenes`, indeks `date` str), `marinas: GeoDataFrame` (EPSG:2180), `curve: AreaLevelCurve`, `rf_metrics: dict`, `z_max_floor: float` (min skończonego `z_max` w modelu), `npp: float`, `max_pp: float`.
  - `data.load_products(data_dir: Path, period: str = "all") -> Products`; `bottom.read_model` do rastrów, `levels.load_area_level_curve`, `capacity.capacity_to_level` (z `MIELIZNA_DATA_DIR` ustawionym na `data_dir`).
  - `conftest.make_dataset(root: Path) -> Path`: zapisuje w `root` strukturę `processed/{model/all/*, model/area_level_curve.json, model/rf_metrics.json, scenes.json, shorelines.gpkg, marinas.gpkg}` i kopiuje `reference/kz_pojemnosc_rzedna.csv` z repo. Siatka 20 wierszy × 30 kolumn, `Affine(10, 0, 375000, 0, -10, 290000)`, EPSG:2180. Rastry przez `mielizna.bottom.write_model` z ręcznie ułożonymi wartościami: kolumny 0–9 przedział `[193.0, 194.0]`, 10–19 „zawsze woda” (`z_min` NaN, `z_max` 193.05), 20–24 „zawsze ląd” (`z_min` 196.0, `z_max` NaN), 25–29 poza modelem (`obs_count` 0, `flags` 255). Meta minimalne: `version "testver00001"`, `period "all"`, `period_dates`, `n_scenes 3`, `n_scenes_by_method {"B": 2, "C": 1}`, `h_min_obs 192.9`, `h_max_obs 197.92`. Trzy sceny w `scenes.json`: `2026-09-30` (B) i `2026-10-20` (B) opublikowane, `2026-10-05` z `qc_ok: false` (fixture `dataset_qc_false_date`), dwie linie brzegowe, dwie przystanie, krzywa z 3 węzłów, `rf_metrics` z kluczami `by_block.per_stratum.shore.{rf_t,otsu}`. Fixture `dataset` (tmp_path) i `products`.

- [ ] **Step 1: Write the failing test** `test_data.py`:
```python
def test_load_products_semantics(products):
    p = products
    assert p.shape == (20, 30) and p.crs == "EPSG:2180"
    assert p.in_model[:, :25].all() and not p.in_model[:, 25:].any()
    assert np.isneginf(p.z_lo[0, 15]) and p.z_hi[0, 15] == pytest.approx(193.05)
    assert np.isposinf(p.z_hi[0, 22])
    assert p.version == "all-testver00001"
    assert [s["date"] for s in p.scenes] == sorted(s["date"] for s in p.scenes) and len(p.scenes) == 2
    assert set(p.shorelines.index) <= {s["date"] for s in p.scenes}
    assert p.z_max_floor == pytest.approx(193.05)
    assert p.npp == pytest.approx(195.91, abs=0.01) and p.max_pp == pytest.approx(198.89, abs=0.01)
```
- [ ] **Step 2:** Run `cd backend && uv sync && uv run pytest tests/test_data.py -v` → FAIL (import).
- [ ] **Step 3:** Napisać `pyproject.toml` (zależności z Tech Stack, dev: `pytest`, `httpx`; `[tool.pytest.ini_options] markers = ["real: wymaga data/processed"]`), `settings.py`, `data.py`, `conftest.py`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(backend): scaffold and in-memory products`

---

### Task 3: Reguła stref i podsumowanie (`zones.py`, część 1)

**Files:**
- Create: `backend/app/zones.py`
- Test: `backend/tests/test_zones.py`

**Interfaces:**
- Consumes: `Products.z_lo`, `z_hi`, `in_model` (Task 2).
- Produces:
  - stałe `NONE, SAFE, RISK, DANGER = 0, 1, 2, 3`; `ZONE_NAMES = {1: "safe", 2: "risk", 3: "danger"}`; `PIXEL_KM2 = 1e-4`.
  - `round_param(x: float, step: float = 0.05) -> float`.
  - `zone_classes(h: float, draft: float, margin: float, z_lo: np.ndarray, z_hi: np.ndarray, in_model: np.ndarray) -> np.ndarray` (uint8, kształt wejścia; działa też dla tablic 1×1, z tego korzysta Task 6).
  - `zone_stats(classes: np.ndarray, h: float, z_lo: np.ndarray, in_model: np.ndarray) -> dict` z kluczami `water_km2` (akwen = `in_model & (h > z_lo)`), `safe_km2`, `risk_km2`, `danger_km2` (cały model, ląd wliczony do danger), `safe_pct`, `risk_pct`, `danger_pct` (udział w akwenie, 0 gdy akwen pusty).
  - `zone_warnings(h: float, draft: float, margin: float, products) -> list[str]`: `"h_out_of_range"` gdy h poza `[meta.h_min_obs, meta.h_max_obs]`; `"below_observed_bottom"` gdy `h − draft − margin < z_max_floor` (frontend pokaże „dna poniżej … m nie obserwowano”, ledger planu 1 w. 132).

- [ ] **Step 1: Write the failing tests**
```python
def arr(*v): return np.array(v, dtype=float).reshape(1, -1)

def test_zone_rule_brief_6_4():
    z_lo = arr(193.0, 193.0, 193.0, -np.inf, 196.0)
    z_hi = arr(193.4, 194.0, 195.0, 193.05, np.inf)
    c = zone_classes(195.0, 1.2, 0.3, z_lo, z_hi, np.ones_like(z_lo, bool))
    # D_lo=1.6>=1.5 safe; D_lo=1.0, D_hi=2.0 risk; D_hi=2.0, D_lo=0 risk; always water D_lo=1.95 safe; land h<z_min danger
    assert c.tolist() == [[SAFE, RISK, RISK, SAFE, DANGER]]

def test_boundary_equality_is_safe():
    c = zone_classes(195.5, 1.2, 0.3, arr(190.0), arr(194.0), np.ones((1, 1), bool))
    assert c[0, 0] == SAFE            # D_lo == d + m dokładnie

def test_danger_wins_on_inverted_bounds():
    c = zone_classes(195.0, 0.5, 0.0, arr(194.8), arr(194.0), np.ones((1, 1), bool))
    assert c[0, 0] == DANGER          # D_lo=1.0 >= 0.5, ale D_hi=0.2 < 0.5

def test_outside_model_is_none():
    c = zone_classes(195.0, 1.2, 0.3, arr(193.0), arr(194.0), np.zeros((1, 1), bool))
    assert c[0, 0] == NONE

def test_round_param():
    assert round_param(195.2300001) == 195.25 and round_param(1.224) == 1.2 and round_param(0.3) == 0.3

def test_stats_empty_water_gives_zero_pct():
    z_lo = arr(196.0, 196.0); c = zone_classes(192.0, 1.0, 0.3, z_lo, arr(np.inf, np.inf), np.ones((1, 2), bool))
    s = zone_stats(c, 192.0, z_lo, np.ones((1, 2), bool))
    assert s["water_km2"] == 0 and s["safe_pct"] == s["risk_pct"] == s["danger_pct"] == 0
    assert s["danger_km2"] == pytest.approx(2e-4)

def test_warnings(products):
    assert zone_warnings(195.0, 1.2, 0.3, products) == []
    assert "h_out_of_range" in zone_warnings(198.5, 1.2, 0.3, products)
    assert "below_observed_bottom" in zone_warnings(194.0, 1.0, 0.3, products)
```
- [ ] **Step 2:** Run `uv run pytest tests/test_zones.py -v` → FAIL.
- [ ] **Step 3:** Implement w `zones.py` (float64, jawne kroki numpy z nazwami `D_lo`, `D_hi` — spec §4).
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(backend): zone rule (brief 6.4) and zone stats`

---

### Task 4: Wektoryzacja stref do GeoJSON (`zones.py`, część 2)

**Files:**
- Modify: `backend/app/zones.py`
- Test: `backend/tests/test_zones.py`

**Interfaces:**
- Produces: `zones_geojson(classes: np.ndarray, transform: Affine, crs: str, simplify_m: float = 5.0) -> dict` — FeatureCollection z maks. 3 obiektami (jeden na strefę obecną w rastrze, w kolejności safe, risk, danger), `properties = {"zone": "safe"|"risk"|"danger"}`, geometria (Multi)Polygon w EPSG:4326, współrzędne zaokrąglone do 6 miejsc.
- Kroki: `rasterio.features.shapes(classes, mask=classes > 0, transform=transform, connectivity=4)` → `GeoDataFrame(crs=crs)` → `dissolve("zone")` → `.simplify(simplify_m, preserve_topology=True)` → `to_crs(4326)` → `shapely.set_precision(geom, 1e-6)` → `__geo_interface__`.

- [ ] **Step 1: Write the failing test**
```python
def test_zones_geojson_shape_and_crs(products):
    c = zone_classes(195.0, 1.2, 0.3, products.z_lo, products.z_hi, products.in_model)
    fc = zones_geojson(c, products.transform, products.crs)
    assert fc["type"] == "FeatureCollection"
    assert [f["properties"]["zone"] for f in fc["features"]] == sorted(
        {ZONE_NAMES[v] for v in np.unique(c) if v}, key=["safe", "risk", "danger"].index)
    lon, lat = _first_coord(fc["features"][0]["geometry"])
    assert 17.0 < lon < 17.5 and 50.3 < lat < 50.6          # lon pierwsza (Review Focus 2)
    area = gpd.GeoDataFrame.from_features(fc["features"], crs=4326).to_crs(2180).area.sum()
    assert area == pytest.approx((c > 0).sum() * 100, rel=0.02)
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(backend): vectorize zones to GeoJSON`

---

### Task 5: Aplikacja, kontrakt, cache, `/api/meta` i `/api/zones`

**Files:**
- Create: `backend/app/schemas.py`, `backend/app/cache.py`, `backend/app/main.py`, `backend/openapi.json`
- Test: `backend/tests/test_api_zones.py`, `backend/tests/test_openapi.py`

**Interfaces:**
- Consumes: Task 2–4.
- Produces:
  - `cache.TTLStore(maxsize: int = 256, ttl_s: float = 3600)` z `get(key) -> Any | None` i `set(key, value) -> None` (`cachetools.TTLCache` + `threading.Lock`; jedyny plik do podmiany na Redis — spec §3).
  - `main.create_app(settings: Settings | None = None, products: Products | None = None) -> FastAPI` (testy podają `products`); `app = create_app()` na poziomie modułu dla uvicorn. Produkty i usługi w `app.state`.
  - `schemas` (pydantic v2): `MetaResponse`, `ZonesResponse`, `ZoneStats`, `Params` (`h`, `draft`, `margin`) oraz modele z Task 6–10. Pole zmiennoprzecinkowe, które może być nieskończone, ma typ `float | None` i serializuje się jako `null` (Review Focus 5).
  - `GET /api/meta` → `MetaResponse`: `model_version`, `period`, `period_dates`, `n_scenes` (= `len(products.scenes)`), `n_scenes_by_method`, `first_scene_date`, `last_scene_date`, `h_min_obs`, `h_max_obs`, `npp`, `max_pp`, `slider {min, max, step}` z `min = round_param(h_min_obs − 0.5)`, `max = round_param(max(h_max_obs + 0.5, max_pp))`, `step = 0.05`, `defaults {h, draft, margin}` (`h` = `h_t` ostatniej sceny zaokrąglone, `draft` 1.20, `margin` 0.30), `limits {draft: [0.10, 3.00], margin: [0.00, 1.00]}`, `draft_presets` (lista `{label, draft}`: „Omega” 0.90, „Sasanka 660 miecz w górze” 0.40, „Sasanka 660 miecz w dole” 1.25 + `presets_provisional: true` — brief §16.4 „do potwierdzenia”), `bbox_wgs84 [lon_min, lat_min, lon_max, lat_max]` (z granic rastra), `crs: "EPSG:2180"`, `z_max_floor`, `accuracy {rf_oa, rf_ba, rf_kappa, otsu_ba, n_labels}` z `rf_metrics.by_block.per_stratum.shore.rf_t` / `.otsu` (nagłówek planu 1: human shore, by_block, RF t*), `area_level {nodes_area_km2, nodes_h, rmse_loo, rmse_loyo, points: [{date, area_otsu_km2, h_t, h_method}]}` (do wykresu w „O metodzie”), `layers` (dopisuje Task 8).
  - `GET /api/zones?h=&draft=&margin=` (`margin` domyślnie 0.30) → `ZonesResponse {type, features, stats, params, warnings, model_version}`; parametry zaokrąglone `round_param`; h poza `slider` → 422.
  - Nagłówki `/api/zones` i `/api/meta`: `ETag: W/"{version}-{h:.2f}-{draft:.2f}-{margin:.2f}"` (meta: `W/"{version}"`), `Cache-Control: public, max-age=300`; `If-None-Match` równy ETagowi → 304 bez ciała. Wynik w `TTLStore` po `("zones", h, draft, margin, version)`.
  - `backend/openapi.json` = `json.dumps(app.openapi(), indent=1, ensure_ascii=False)`; skrypt `backend/scripts/export_openapi.py` go zapisuje.

- [ ] **Step 1: Write the failing tests**
```python
def test_zones_endpoint(client):
    r = client.get("/api/zones", params={"h": 195.0, "draft": 1.2})
    assert r.status_code == 200
    j = r.json()
    assert j["params"] == {"h": 195.0, "draft": 1.2, "margin": 0.3}
    assert {f["properties"]["zone"] for f in j["features"]} <= {"safe", "risk", "danger"}
    assert abs(j["stats"]["safe_pct"] + j["stats"]["risk_pct"] + j["stats"]["danger_pct"] - 100) < 1e-6

def test_rounding_shares_etag(client):
    a = client.get("/api/zones", params={"h": 195.2300001, "draft": 1.2})
    b = client.get("/api/zones", params={"h": 195.25, "draft": 1.2})
    assert a.headers["etag"] == b.headers["etag"] and a.json()["params"]["h"] == 195.25

def test_if_none_match_304(client):
    e = client.get("/api/zones", params={"h": 195.0, "draft": 1.2}).headers["etag"]
    r = client.get("/api/zones", params={"h": 195.0, "draft": 1.2}, headers={"If-None-Match": e})
    assert r.status_code == 304 and r.content == b""

@pytest.mark.parametrize("q", [{"h": 150, "draft": 1}, {"h": 195, "draft": 5}, {"h": 195, "draft": 1, "margin": 2}])
def test_validation_422(client, q):
    assert client.get("/api/zones", params=q).status_code == 422

def test_meta(client):
    m = client.get("/api/meta").json()
    assert m["slider"] == {"min": 192.4, "max": 198.9, "step": 0.05}
    assert m["npp"] < m["max_pp"] <= m["slider"]["max"] and m["n_scenes"] == 2

# test_openapi.py
def test_openapi_snapshot_is_current(app):
    assert json.loads(Path("openapi.json").read_text("utf-8")) == app.openapi()
```
Fixture `client` = `TestClient(create_app(Settings(live=False, ...), products))`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement `cache.py`, `schemas.py`, `main.py`; wygenerować `openapi.json`. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(backend): app, /api/meta, /api/zones with ETag and cache`

---

### Task 6: `/api/point`

**Files:**
- Create: `backend/app/point.py`
- Modify: `backend/app/main.py`, `backend/app/schemas.py`, `backend/openapi.json`
- Test: `backend/tests/test_point.py`

**Interfaces:**
- Consumes: `zones.zone_classes` (ta sama reguła — spec §4), `Products`.
- Produces:
  - `point.point_info(products, lon: float, lat: float, h: float, draft: float, margin: float) -> dict` → `PointResponse`: `kind` ∈ `"model" | "always_water" | "land" | "outside"`, `lon`, `lat`, `h`, `draft`, `margin`, `zone` (`"safe"|"risk"|"danger"|None`), `depth_min` (`max(D_lo, 0)`), `depth_max` (`D_hi`, `None` gdy +∞), `clearance_min` / `clearance_max` (`D_lo − draft`, `D_hi − draft`, `None` gdy nieskończone), `z_min`, `z_max`, `z`, `unc` (`None` gdy nieskończone/NaN), `bottom_above_water_min` / `_max` (`z_lo − h`, `z_hi − h`; tylko dla `land`), `obs_count`. Liczby zaokrąglone do 2 miejsc.
  - Rozstrzyganie `kind` (w tej kolejności): poza siatką lub `~in_model` → `outside` (zone `None`); `h <= z_lo` → `land`; `z_lo == −∞` → `always_water`; inaczej `model`.
  - `GET /api/point?lon=&lat=&h=&draft=&margin=` (parametry jak w `/api/zones`, te same zaokrąglenia i 422).
  - Pixel: `Transformer.from_crs(4326, products.crs, always_xy=True)`, potem `rasterio.transform.rowcol(products.transform, x, y)`.

- [ ] **Step 1: Write the failing tests**
```python
def lonlat_of(products, row, col):
    x, y = rasterio.transform.xy(products.transform, row, col)
    return Transformer.from_crs(products.crs, 4326, always_xy=True).transform(x, y)

def test_point_kinds(products):
    k = lambda col, h=195.0: point_info(products, *lonlat_of(products, 5, col), h, 1.2, 0.3)
    assert k(3)["kind"] == "model" and k(3)["z_min"] == 193.0 and k(3)["z_max"] == 194.0
    aw = k(15)
    assert aw["kind"] == "always_water" and aw["depth_max"] is None and aw["depth_min"] == 1.95
    assert k(22)["kind"] == "land" and k(22)["bottom_above_water_min"] == 1.0
    assert k(27)["kind"] == "outside" and k(27)["zone"] is None

def test_point_zone_equals_zone_raster(products):
    c = zone_classes(195.0, 1.2, 0.3, products.z_lo, products.z_hi, products.in_model)
    for col in (3, 15, 22):
        assert point_info(products, *lonlat_of(products, 5, col), 195.0, 1.2, 0.3)["zone"] == ZONE_NAMES[c[5, col]]

def test_point_far_away_is_outside(products):
    assert point_info(products, 21.0, 52.2, 195.0, 1.2, 0.3)["kind"] == "outside"

def test_point_endpoint_json_has_no_infinity(client, products):
    lon, lat = lonlat_of(products, 5, 15)
    r = client.get("/api/point", params={"lon": lon, "lat": lat, "h": 195.0, "draft": 1.2})
    assert r.status_code == 200 and "Infinity" not in r.text and "NaN" not in r.text
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; odświeżyć `openapi.json`. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(backend): /api/point with four popup variants`

---

### Task 7: Sceny, linie brzegowe, przystanie, pojemność

**Files:**
- Modify: `backend/app/main.py`, `backend/app/schemas.py`, `backend/openapi.json`
- Test: `backend/tests/test_api_lists.py`

**Interfaces:**
- Produces:
  - `GET /api/scenes` → `list[SceneOut]`: `date`, `h_t`, `h_sigma`, `h_method`, `area_km2` (RF, ta sama co linia brzegowa), `area_otsu_km2`, `otsu_threshold`, `local_cloud_pct`, `lake_nodata_pct` — tylko `products.scenes` (opublikowane: `qc_ok` i `h_t`), rosnąco po dacie.
  - `GET /api/shorelines?date=YYYY-MM-DD` → GeoJSON `Feature` (EPSG:4326) z `properties` = pola `SceneOut` tej daty; nieznana data albo scena nieopublikowana → 404.
  - `GET /api/marinas` → `FeatureCollection` (EPSG:4326), `properties {osm_id, kind, name}`.
  - `GET /api/capacity-to-level?v=` (0 < v ≤ 200, inaczej 422) → `{v, h, in_table}` (`h = None`, `in_table = False` poza tabelą KŻ); `GET /api/level-to-capacity?h=` → `{h, v, in_table}` (do „≈ X mln m³” w panelu, brief §16.4).
  - Wszystkie z `ETag: W/"{version}"` i `Cache-Control: public, max-age=3600`.

- [ ] **Step 1: Write the failing tests**
```python
def test_scenes_only_published(client):
    s = client.get("/api/scenes").json()
    assert len(s) == 2 and all(x["h_t"] is not None for x in s)
    assert [x["date"] for x in s] == sorted(x["date"] for x in s)

def test_shoreline_feature_and_404(client, dataset_qc_false_date):
    d = client.get("/api/scenes").json()[0]["date"]
    f = client.get("/api/shorelines", params={"date": d}).json()
    assert f["type"] == "Feature" and f["properties"]["date"] == d
    assert client.get("/api/shorelines", params={"date": dataset_qc_false_date}).status_code == 404
    assert client.get("/api/shorelines", params={"date": "1999-01-01"}).status_code == 404

def test_capacity_roundtrip(client):
    h = client.get("/api/capacity-to-level", params={"v": 65.69}).json()
    assert h["in_table"] and h["h"] == pytest.approx(195.91, abs=0.01)
    v = client.get("/api/level-to-capacity", params={"h": h["h"]}).json()
    assert v["v"] == pytest.approx(65.69, abs=0.01)
    assert client.get("/api/capacity-to-level", params={"v": 150}).json() == {"v": 150.0, "h": None, "in_table": False}

def test_marinas(client):
    fc = client.get("/api/marinas").json()
    assert len(fc["features"]) == 2 and {"osm_id", "kind", "name"} <= set(fc["features"][0]["properties"])
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; odświeżyć `openapi.json`. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(backend): scenes, shorelines, marinas, capacity endpoints`

---

### Task 8: Obrazy warstw dna i niepewności (`layers.py`)

**Files:**
- Create: `backend/app/layers.py`
- Modify: `backend/app/main.py`, `backend/app/schemas.py` (`MetaResponse.layers`), `backend/openapi.json`
- Test: `backend/tests/test_layers.py`

**Interfaces:**
- Produces:
  - `layers.to_web_mercator(arr: np.ndarray, products) -> tuple[np.ndarray, Affine]`: `rasterio.warp.reproject` do EPSG:3857 (transform z `calculate_default_transform`, rozdzielczość 10 m, `Resampling.nearest`, NaN jako nodata).
  - `layers.image_coordinates(dst_transform: Affine, shape) -> list[list[float]]`: 4 narożniki `[lon, lat]` w kolejności MapLibre `image` source: lewy górny, prawy górny, prawy dolny, lewy dolny.
  - `layers.bottom_breaks(products) -> list[float]`: percentyle 0, 20, 40, 60, 80, 100 skończonego `z` w modelu, zaokrąglone do 0,01.
  - `layers.render_bottom_png(products, theme: str) -> bytes`: RGBA, 5 klas wg `bottom_breaks`, kolory interpolowane liniowo w RGB od `#C4DDE9` (najwyżej, płytko) do `#215C86` (najgłębiej) dla `light`, `#2A4C5E` → `#1675AB` dla `dark` (brief §16.3); poza modelem i NaN przezroczyste.
  - `layers.render_uncertainty_png(products, theme: str) -> bytes`: obraz powiększony 4× (nearest); w każdej komórce 4×4 piksela z `unc ≥ 0.5` m kropka 2×2 (wiersze i kolumny 1–2 komórki) w kolorze `#0E2433` (light) / `#E6EEF3` (dark), alfa 0,6; reszta przezroczysta.
  - `GET /api/layers/bottom.png?theme=light|dark`, `GET /api/layers/uncertainty.png?theme=` (`image/png`, ETag `W/"{version}-{name}-{theme}"`, `max-age=86400`; obrazy liczone raz i trzymane w `TTLStore`).
  - `MetaResponse.layers = {bottom: {url, coordinates, breaks}, uncertainty: {url, coordinates, min_unc: 0.5}}` (`url` bez `theme`; front dopisuje `?theme=`).

- [ ] **Step 1: Write the failing tests**
```python
def test_known_pixel_lands_on_its_lonlat(products):
    marker = np.full(products.shape, np.nan, np.float32); marker[5, 7] = 1.0
    dst, tr = to_web_mercator(marker, products)
    r, c = np.argwhere(np.isfinite(dst)).mean(axis=0)
    x, y = rasterio.transform.xy(tr, r, c)
    lon, lat = Transformer.from_crs(3857, 4326, always_xy=True).transform(x, y)
    exp = Transformer.from_crs(products.crs, 4326, always_xy=True).transform(*rasterio.transform.xy(products.transform, 5, 7))
    assert abs(lon - exp[0]) < 1.5e-4 and abs(lat - exp[1]) < 1e-4      # < ~10 m

def test_coordinates_order(products):
    _, tr = to_web_mercator(products.z.astype(np.float32), products)
    tl, tr_, br, bl = image_coordinates(tr, (3, 3))
    assert tl[1] == tr_[1] > br[1] == bl[1] and tl[0] == bl[0] < tr_[0] == br[0]

def test_bottom_png_transparent_outside(products):
    img = Image.open(io.BytesIO(render_bottom_png(products, "light")))
    assert img.mode == "RGBA" and img.getextrema()[3] == (0, 255)

def test_meta_has_layers(client):
    L = client.get("/api/meta").json()["layers"]
    assert len(L["bottom"]["coordinates"]) == 4 and len(L["bottom"]["breaks"]) == 6
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; odświeżyć `openapi.json`. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(backend): bottom and uncertainty image layers in EPSG:3857`

---

### Task 9: Bieżący poziom z najnowszej sceny (`current.py`)

Spec §2 pkt 6. Szczegóły zostawione builderowi (próg świeżości, limit chmur) ustala ten plan: świeża scena ≤ **10 dni**, wyszukiwanie **30 dni** wstecz, filtr chmur i ważności z `config.yaml` (`is_usable`), maks. **3** nowe akwizycje sprawdzane w jednym odświeżeniu, od najnowszej.

**Files:**
- Create: `backend/app/current.py`
- Test: `backend/tests/test_current.py`

**Interfaces:**
- Consumes: `classify.analyze_scene` (Task 1), `s2.search_items`, `s2.group_acquisitions`, `s2.load_day`, `s2.scene_quality`, `s2.is_usable`, `s2.valid_mask`, `rf.load_model`, `osm.aoi_mask`, `osm.lake_mask`, `classify.lake_core`, `shoreline.mask_to_shoreline`, `levels.C_EXTRAP_EXTRA`, `Products.curve`, `Products.scenes`, `Products.shorelines`.
- Produces:
  - `current.CurrentLevel` (dataclass): `source` (`"satellite"` | `"pipeline"`), `scene_date: str`, `acq_id: str | None`, `h: float`, `h_sigma: float`, `h_method: str` (`"C_live"` dla `satellite`, metoda sceny dla `pipeline`), `extrapolated: bool`, `area_biased: bool` (`lake_nodata_pct > 1`), `ice_unverified: bool` (miesiąc sceny ∈ {11, 12, 1, 2, 3}: SCL nie widzi lodu — w planie 1 lód odrzucał przegląd wizualny, ledger w. 60), `local_cloud_pct`, `area_otsu_km2`, `shoreline: dict | None` (GeoJSON geometry, EPSG:4326), `computed_at: str` (UTC ISO).
  - `current.pipeline_fallback(products) -> CurrentLevel`: ostatnia opublikowana scena (`products.scenes[-1]`), linia z `products.shorelines`.
  - `current.evaluate(items: list, date: str, ctx: SceneContext, load_fn=s2.load_day) -> CurrentLevel | str` (str = powód odrzucenia: `"not_usable"`, `"radiometry"`, `"qc:<qc_reason>"`, `"no_water"`). `h, extrap = curve(area_otsu_km2)`; `h_sigma = curve.sigma + (C_EXTRAP_EXTRA if extrap else 0)`.
  - `current.SceneContext` (dataclass): `cfg`, `grid`, `aoi`, `lake`, `core`, `bundle`, `curve`; `SceneContext.build(products) -> SceneContext` (sprawdza `reference_grid() == siatka produktów`).
  - `current.CurrentLevelService(products, cache_dir: Path, search_fn, load_fn, ctx_factory, fresh_days: int = 10, clock=date.today)`:
    - `refresh() -> None`: `search_fn(today − 30 dni, today)` → akwizycje `(date, platform)` malejąco po dacie; pomija te z plikiem `cache_dir/{date}_{platform}.json`; ocenia maks. 3; każdy wynik zapisuje atomowo do tego pliku jako `{"accepted": <CurrentLevel jako dict>}` albo `{"rejected": "<powód>", "checked_at": "<UTC ISO>"}`; wyjątek pojedynczej akwizycji = odrzucenie `"error:<typ>"`; wyjątek `search_fn` zapisuje `last_error` i kończy bez rzucania. Kontekst (`ctx_factory`) budowany leniwie przy pierwszej ocenie.
    - `get() -> dict` (`CurrentLevelResponse`): najlepsza z (najnowsza przyjęta akwizycja z `cache_dir`, `pipeline_fallback`) wg `scene_date` (remis → `pipeline`, bo ma pełny wariant B/C); dopisuje `age_days`, `stale = age_days > fresh_days`, `refreshing: bool`, `last_checked: str | None`, `last_error: str | None`.
  - `search_fn(start: date, end: date) -> dict[(date, platform), list[Item]]`; `load_fn(items, grid, cfg) -> (bands, scl)` (jak `s2.load_day`).
  - `current.stac_search(cfg, start: date, end: date) -> dict` (domyślny `search_fn` = `functools.partial(stac_search, cfg)`): kopia `cfg` z `period = {start, end}`, `s2.search_items(cfg2, cache=None)`, `group_acquisitions`. Odczyt COG z S3 w `rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="2", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")` — te same wartości co `pipeline/01_fetch_s2.py`.
  - `cache_dir` = `data/processed/current/` (poza gitem jak całe `processed/`).

- [ ] **Step 1: Write the failing tests** (sztuczne `search_fn`/`load_fn`/`ctx_factory`; `ctx` z siatką fixture'u i bundle-atrapą o `predict_proba` z MNDWI; `load_fn` zwraca pasma, w których kolumny 0–19 są wodą)
```python
def test_fallback_when_nothing_found(service_factory):
    s = service_factory(search=lambda a, b: {})
    s.refresh(); r = s.get()
    assert r["source"] == "pipeline" and r["scene_date"] == "2026-10-20"
    assert r["stale"] is False and r["last_error"] is None           # zegar testu 2026-10-27

def test_live_scene_newer_than_pipeline(service_factory):
    s = service_factory(search=one_acq("2026-10-26")); s.refresh(); r = s.get()
    assert r["source"] == "satellite" and r["h_method"] == "C_live" and r["shoreline"]["type"] in ("LineString", "MultiLineString")
    assert r["h_sigma"] >= s.products.curve.sigma

def test_rejections_are_cached_and_not_retried(service_factory, tmp_path):
    calls = []
    s = service_factory(search=one_acq("2026-10-26"), load=cloudy_scene(calls))
    s.refresh(); s.refresh()
    assert len(calls) == 1 and s.get()["source"] == "pipeline"
    assert json.loads(next(tmp_path.glob("current/2026-10-26_*.json")).read_text())["rejected"] == "not_usable"

def test_search_error_never_raises(service_factory):
    def boom(a, b): raise ConnectionError("offline")
    s = service_factory(search=boom); s.refresh(); r = s.get()
    assert r["source"] == "pipeline" and "offline" in r["last_error"]

def test_corrupt_scene_rejected(service_factory):
    s = service_factory(search=one_acq("2026-10-26"), load=corrupt_scene); s.refresh()
    assert s.get()["source"] == "pipeline"

def test_stale_after_fresh_days(service_factory):
    s = service_factory(search=lambda a, b: {}, today=date(2026, 11, 15)); s.refresh()
    assert s.get()["stale"] is True and s.get()["age_days"] == 26

def test_winter_scene_flags_ice(service_factory):
    s = service_factory(search=one_acq("2026-12-10"), today=date(2026, 12, 12)); s.refresh()
    assert s.get()["ice_unverified"] is True
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(backend): current level from newest S2 scene with fallback`

---

### Task 10: `/api/current-level` i odświeżanie w tle

**Files:**
- Modify: `backend/app/main.py`, `backend/app/schemas.py` (`CurrentLevelResponse`), `backend/openapi.json`
- Test: `backend/tests/test_api_current.py`

**Interfaces:**
- Consumes: `CurrentLevelService` (Task 9).
- Produces:
  - `GET /api/current-level` → `CurrentLevelResponse` (pola `get()`), zawsze 200, odpowiedź natychmiastowa (bez czekania na S2); `Cache-Control: no-cache`.
  - `lifespan` w `create_app`: gdy `settings.live`, zadanie `asyncio` w pętli: `await asyncio.to_thread(service.refresh)`, potem `await asyncio.sleep(settings.refresh_hours * 3600)`; każdy wyjątek łapany i logowany (`logging`, `last_error`), pętla trwa; anulowane przy zamknięciu aplikacji. `refreshing = True` na czas `refresh`.
  - Przy `live = False` usługa działa tylko na `pipeline_fallback` i wynikach z `cache_dir`.

- [ ] **Step 1: Write the failing tests**
```python
def test_current_level_offline(client):
    r = client.get("/api/current-level")
    assert r.status_code == 200 and r.json()["source"] == "pipeline" and "stale" in r.json()

def test_background_task_survives_exception(products, tmp_path):
    n = {"calls": 0}
    def flaky(a, b):
        n["calls"] += 1; raise RuntimeError("boom")
    app = create_app(Settings(data_dir=tmp_path, live=True, refresh_hours=0.00002), products, search_fn=flaky)
    with TestClient(app) as c:                     # 0.00002 h = 0,072 s między odświeżeniami
        time.sleep(0.3)
        assert c.get("/api/current-level").status_code == 200
    assert n["calls"] >= 2
```
(`create_app` przyjmuje opcjonalne `search_fn`/`load_fn` przekazywane do usługi.)
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; odświeżyć `openapi.json`. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(backend): /api/current-level with background refresh`

---

### Task 11: Prawdziwe dane, wydajność i notatka do nauki

**Files:**
- Create: `backend/tests/test_real.py` (marker `real`), `docs/nauka/M5-backend.md`
- Modify: `README.md` (uruchomienie backendu, zmienne `MIELIZNA_*`), `docs/nauka/decyzje.md` (decyzje z tego planu)

**Interfaces:**
- Consumes: wszystko powyżej, `data/processed/` z planu 1.

- [ ] **Step 1: Write the tests** `test_real.py` (pomijane, gdy brak `data/processed/model/all/model_meta.json`):
```python
def test_zones_under_one_second_cold(real_client):
    t = time.perf_counter()
    r = real_client.get("/api/zones", params={"h": 195.5, "draft": 1.0, "margin": 0.3})
    assert r.status_code == 200 and time.perf_counter() - t < 1.0          # brief M5

def test_real_meta_numbers(real_client):
    m = real_client.get("/api/meta").json()
    assert m["n_scenes"] == 218 and m["h_min_obs"] == 192.9 and m["z_max_floor"] == pytest.approx(193.05)
    assert m["model_version"].endswith("311e18c951a8")

def test_safe_area_matches_plan1(real_client):
    s = real_client.get("/api/zones", params={"h": 195.5, "draft": 1.0, "margin": 0.0}).json()["stats"]
    assert 12.70 <= s["safe_km2"] <= 12.891    # ledger planu 1 w. 133: 128 908 px przed R25; R25 może tylko zmniejszyć
```
Górna granica 12,891 km² (128 908 px) pochodzi z ledgera planu 1 (h 195,5, d 1,0, bez zapasu, przed R25). R25 tylko podnosi `z_max`, więc bezpiecznych pikseli może tylko ubyć. Jeśli wynik jest poza przedziałem, **nie poprawiać granic w teście**: sprawdzić, czy ledger liczył z zapasem albo z innym okresem, i zapisać wynik w opisie commita.
- [ ] **Step 2:** Run `uv run pytest -m real -v` → PASS (albo zbadać rozbieżność, jak wyżej).
- [ ] **Step 3: Ręczny przegląd:** `uv run uvicorn app.main:app` z `MIELIZNA_LIVE=1`; po zakończeniu pierwszego odświeżenia `GET /api/current-level` zwraca scenę z `source` i datą; zapisać wynik (data, h, różnica względem `h_t` tej daty w `scenes.json`, jeśli jest) do `M5-backend.md`.
- [ ] **Step 4:** Napisać `docs/nauka/M5-backend.md` (co powstało; reguła stref i dlaczego zbyt płytka wygrywa; dlaczego Otsu do krzywej; reprojekcja obrazów do 3857; cache i ETag; liczby z testów `real`; pytania prowadzącego z odpowiedziami) i dopisać decyzje do `decyzje.md`.
- [ ] **Step 5:** Run cały zestaw `uv run pytest -q` w `backend/` i w `pipeline/` → PASS.
- [ ] **Step 6:** Commit `docs: M5 backend notes, real-data checks`
