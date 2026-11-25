# Plan 6: dno głębokiej części z KŻ, kalibracja przedziałów, czytelna ścieżka głębokości

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Czytelna ścieżka „dane → głębokość → strefa” z przewodnikiem, zmierzony wpływ źródeł poziomu wody,
skalibrowane przedziały dna i dno z mapy KŻ w strefie „zawsze woda”, pokazane w API, na mapie i w raporcie.

**Architecture:** Backend dostaje moduł `app/depth.py` ze ścieżką krok po kroku (refaktor bez zmiany wyników,
pilnowany testem regresji na prawdziwych danych). Pipeline liczy LOO KŻ, kalibrację z hold-outu i zapisuje rastry
łączone w osobnym katalogu `model/<okres>_kz/`; backend tylko je wczytuje. Kontrole (08, 10, 12, 13) czytają wyłącznie
rastry satelitarne.

**Tech Stack:** Python 3.12 (numpy, rasterio, scipy, geopandas, pytest, uv), FastAPI + pydantic, React/TS
(TanStack Query, MapLibre, vitest), openapi-typescript.

**Spec:** `docs/superpowers/specs/2026-11-25-kz-deep-bottom-design.md` (zaakceptowany 2026-11-25).

## Global Constraints

- Refaktor (Task 1–2) nie zmienia żadnej liczby: test regresji na prawdziwych danych przechodzi bit w bit; refaktor i
  nowe funkcje w osobnych commitach.
- `pipeline/mielizna/bottom.py` bez zmian. Wariant D i `kz_surface.tif` bez zmian.
- Kontrole K5, hold-out, budżet liczone na rastrach satelitarnych (`model/<okres>/`), nigdy na `model/<okres>_kz/`.
- Reguła KŻ tylko dla pikseli „zawsze woda” (`z_lo = −∞`) z powierzchnią KŻ:
  `z_hi = min(z_hi_cal, kz − P5)`, `z_lo = kz − P95`; sprzeczność `kz − P95 > z_hi_cal` → piksel satelitarny
  (`z_lo = −∞`, `z_hi = z_hi_cal`), źródło `satellite`, flaga `kz_conflict`. Błąd LOO ze znakiem: `err = odczyt − rzędna`.
- Powierzchnia KŻ dla głębokiej części: punkty po kontroli (`kz.load_qc_spots`) + poziomica 192,5 m, **bez 195,0 m**,
  żwirownia NaN.
- Kalibracja: z hold-outu (poza próbą), na pasmo budżetu `192.9-194.8` i `194.8+`: `δ_lo` = P95 `max(0, z_min − h)`,
  `δ_hi` = P95 `max(0, h − z_max)`; granice skończone: `z_lo − δ_lo`, `z_hi + δ_hi`; ±∞ bez zmian; pasmo piksela
  wg środka przedziału (jednostronnie skończone: wg granicy skończonej); poniżej 192,9 m δ pasma `192.9-194.8`.
  Kolejność: kalibracja → reguła KŻ (sprzeczność względem skalibrowanego `z_hi`).
- `z_max_floor` liczony z surowego satelitarnego `z_max`, jak dziś.
- `Products.version` zawiera hash rastrów łączonych i `kz_loo.json`, gdy istnieją.
- `/api/point`: `kind` bez zmian; nowe pola we wszystkich wariantach `bottom_source: "satellite" | "kz"`,
  `kz_conflict: bool`.
- Nazwa w JSON/UI/raporcie: „błąd interpolacji mapy KŻ”, nigdy „dokładność”/„całkowity błąd”.
- Każdy produkt pochodny z KŻ (warstwa, popup, raport) odsyła do warunków „UWAGA”
  (`data/reference/KZ_ZRODLO_I_WARUNKI.md`); atrybucja jak żwirownia: „Mapa KŻ Nysa (W. Wróblewski, 2023)”.
- JSON bez NaN/∞ (`allow_nan=False`, `None`). Teksty UI po polsku, liczby z przecinkiem; zakaz surowych kluczy w UI
  (istniejący test).
- Typowe poziomy do raportu: 194,5 m (najczęstszy) i 193,6 m (typowa zima).
- Commity kończą się linią `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Piksel „zawsze woda” z KŻ i `h ≤ z_lo` (bardzo niska woda nad wysokim punktem KŻ): `kind = land`, popup mówi
   „ląd”, źródło `kz` — test w Task 8.
2. Brak plików `model/<okres>_kz/` (stary pipeline, świeży klon): backend działa jak dziś, `bottom_source =
   satellite` wszędzie, endpoint obrysu zwraca pustą kolekcję — test w Task 8.
3. Punkt KŻ na krawędzi otoczki: po usunięciu wypada poza TIN → pominięty i policzony w `n_skipped`, nie NaN w
   statystykach — test w Task 5.
4. Pasmo bez pikseli z obiema granicami w hold-oucie (δ nieobliczalne) → δ = 0 z notką, nie NaN w rastrze — test w
   Task 4.
5. ETag po ponownym przeliczeniu KŻ bez zmiany modelu satelitarnego się zmienia — test w Task 8.

---

### Task 1: Test regresji ścieżki głębokości na prawdziwych danych

**Files:**
- Create: `backend/tests/depth_baseline.py` (generator referencji, uruchamiany ręcznie raz przed refaktorem)
- Create: `backend/tests/fixtures/depth_baseline.json`
- Create: `backend/tests/test_depth_regression.py`

**Interfaces:**
- Produces: `depth_baseline.json` = `{"zones": {"<h>|<draft>|<margin>": {"sha1": str, "stats": dict}},
  "points": [{"lon", "lat", "h", "draft", "margin", "out": dict}]}`.

- [ ] **Step 1:** Napisz `depth_baseline.py`: `load_products(DATA, "all")`; dla h ∈ {193.0, 194.0, 195.0, 195.91},
  draft ∈ {0.3, 0.5, 1.0}, margin ∈ {0.0, 0.3} zapisz sha1 bajtów `zone_classes(...)` i `zone_stats(...)` oraz
  `zone_warnings(...)`; dla punktów: po 3 losowe (seed 0) piksele każdego wariantu `outside`/`land`/`always_water`/
  `model` przy h = 194.5 (współrzędne środka piksela przeliczone do 4326) + 2 piksele w żwirowni, wynik
  `point_info` dla draft 0.5, margin 0.3 i h ∈ {193.0, 194.5}.
- [ ] **Step 2:** Uruchom `cd backend && uv run python tests/depth_baseline.py` na obecnym `main` (przed zmianami w
  `app/`); commit fixture.
- [ ] **Step 3:** `test_depth_regression.py` (marker `real`, pominięcie jak w `test_real.py`): przelicza to samo i
  porównuje równość (`==` na dict, sha1 na klasach).
- [ ] **Step 4:** `uv run pytest tests/test_depth_regression.py -m real -v` → PASS.
- [ ] **Step 5:** Commit `test: depth path regression baseline on real data`.

### Task 2: Refaktor ścieżki głębokości w backendzie

**Files:**
- Create: `backend/app/depth.py`
- Modify: `backend/app/data.py` (część granic dna w `load_products`), `backend/app/zones.py`, `backend/app/point.py`
- Test: `backend/tests/test_depth.py`

**Interfaces:**
- Produces (`app/depth.py`), w tej kolejności w pliku, każda funkcja z docstringiem „co / dlaczego / przykład”:
  - `@dataclass Bounds: z_lo: np.ndarray; z_hi: np.ndarray; in_model: np.ndarray; source: np.ndarray (uint8, 0 =
    satellite, 1 = kz); kz_conflict: np.ndarray (bool)`
  - `satellite_bounds(z_min, z_max, obs_count, flags) -> Bounds` (dzisiejsza logika ±∞ z `load_products`)
  - `depth_range(h: float, z_lo, z_hi) -> tuple[np.ndarray, np.ndarray]` (`D_lo = h − z_hi`, `D_hi = h − z_lo`)
  - `classify(h, draft, margin, b: Bounds) -> np.ndarray` (reguła z `zone_classes`; `zone_classes` w `zones.py`
    zostaje jako cienkie wywołanie dla zgodności importów)
  - `point_kind(h, z_lo) -> str` (`land` / `always_water` / `model`)
- `Products` dostaje pole `bounds: Bounds`; `z_lo`, `z_hi`, `in_model` zostają jako właściwości delegujące
  (zgodność z `main.py`, `layers.py`, testami).

- [ ] **Step 1:** Testy jednostkowe `test_depth.py`: `satellite_bounds` na tablicy 2×3 z NaN w `z_min` (→ −∞), NaN w
  `z_max` (→ +∞), `obs=0` (→ NaN, poza modelem); `depth_range(195.0, [[193.0]], [[194.0]])` → `([[1.0]], [[2.0]])`;
  `classify` dla trzech pikseli z oczekiwanymi SAFE/RISK/DANGER; `point_kind`.
- [ ] **Step 2:** Uruchom → FAIL (brak modułu).
- [ ] **Step 3:** Zaimplementuj `depth.py`; przepnij `data.py`, `zones.py`, `point.py` na niego bez zmiany logiki.
- [ ] **Step 4:** `uv run pytest -q` (cały backend) i `uv run pytest tests/test_depth_regression.py -m real` → PASS.
- [ ] **Step 5:** Commit `refactor: readable depth path in app/depth.py (no result changes)`.

### Task 3: Przewodnik `docs/jak-czytac-kod.md` (część satelitarna)

**Files:**
- Create: `docs/jak-czytac-kod.md`
- Test: `backend/tests/test_guide_example.py`

- [ ] **Step 1:** Przewodnik: kolejność czytania (1) `pipeline/06_water_levels.py` + `mielizna/levels.py` — skąd
  `h_t` i `h_sigma` sceny (A/B/C/R); (2) `mielizna/bottom.py:compute_bounds` — mokro przy `h` → dno < h, sucho → dno
  > h, przedział; (3) `backend/app/data.py:load_products` → `depth.satellite_bounds`; (4) `depth.depth_range` →
  `depth.classify`; (5) `point.point_info`. Przykład liczbowy A: piksel z 4 scenami (194,9 mokro; 194,2 sucho; 195,6
  mokro; 193,8 sucho) → przedział [194,2; 194,9] (z uwzględnieniem k_sigma — opisz, jak w `compute_bounds`), przy
  h = 195,5, zanurzeniu 0,5, zapasie 0,3 → D 0,6–1,3 m → strefa RISK. Liczby dobierz tak, by wynikały z kodu.
- [ ] **Step 2:** `test_guide_example.py` odtwarza przykład A funkcjami z `depth.py` (i `bottom.compute_bounds`,
  jeśli importowalny z backendu; inaczej tylko część backendową) i sprawdza liczby z przewodnika.
- [ ] **Step 3:** `uv run pytest tests/test_guide_example.py -v` → PASS.
- [ ] **Step 4:** Commit `docs: how-to-read guide for the depth path`.

### Task 4: Hold-out — reszty poza przedziałem i kalibracja

**Files:**
- Modify: `pipeline/mielizna/holdout.py`, `pipeline/12_holdout.py`
- Create: `pipeline/mielizna/calibration.py`
- Test: `pipeline/tests/test_holdout.py`, `pipeline/tests/test_calibration.py`

**Interfaces:**
- Produces:
  - `holdout.bound_residuals(model: dict, shore: np.ndarray, h: float) -> tuple[np.ndarray, np.ndarray]` —
    `(max(0, z_min − h), max(0, h − z_max))` na pikselach z obiema granicami skończonymi.
  - `calibration.deltas(res_lo_by_band: dict[str, np.ndarray], res_hi_by_band: dict[str, np.ndarray], q: float = 95)
    -> dict[str, dict]` → `{band: {"delta_lo", "delta_hi", "n", "note"}}`; puste pasmo → δ = 0, `note` „brak
    pikseli”.
  - `calibration.coverage(err_in_bounds...)` — udział w przedziale przed/po (do `calibration.json`).
  - `calibration.apply(z_lo, z_hi, d: dict) -> tuple[np.ndarray, np.ndarray]` (reguła pasm z Global Constraints).
  - `data/processed/eval/calibration.json`: `{"bands": {...}, "coverage_before", "coverage_after", "method"}`.

- [ ] **Step 1:** Testy: `bound_residuals` na 1×3 (dno poniżej, w, powyżej przedziału); `deltas` z tablicami 0..99 →
  P95; puste pasmo → 0 i notka; `apply`: piksel w paśmie 192,9–194,8, piksel ≥ 194,8, piksel −∞/skończony (pasmo wg
  `z_hi`), piksel < 192,9 (δ pasma `192.9-194.8`), ±∞ nietknięte.
- [ ] **Step 2:** Uruchom → FAIL.
- [ ] **Step 3:** Zaimplementuj; w `12_holdout.py` zbieraj reszty z foldów (model hold-outowy, nie serwowany) per
  pasmo `budget.band_of(h)`, licz `deltas`, pokrycie po kalibracji na tych samych resztach, zapisz `calibration.json`.
  `holdout.json` bez zmian treści.
- [ ] **Step 4:** `uv run pytest tests/test_holdout.py tests/test_calibration.py -q` → PASS; `rm
  ../data/processed/eval/holdout.json && make holdout`; sprawdź, że `holdout.json` ma te same liczby co przed
  (`git diff --stat` na pliku oceny pusty, jeśli wersjonowany; inaczej porównaj MAE 0,944) i `coverage_after` ≈ 0,9.
- [ ] **Step 5:** Commit `eval: out-of-sample interval calibration from yearly hold-out`.

### Task 5: Eksperyment źródeł poziomu wody

**Files:**
- Modify: `pipeline/12_holdout.py` (wydziel `run_folds(sel, ev, h, sig, is_c, train_filter) -> list[dict]`)
- Create: `pipeline/12a_holdout_levels.py`
- Modify: `pipeline/Makefile` (cel `holdout-levels`)
- Test: `pipeline/tests/test_holdout.py`

**Interfaces:**
- Produces: `data/processed/eval/holdout_level_sources.json` =
  `{"variants": {"all": {...}, "no_c": {...}, "b_r_only": {...}}, "method": str}`, każdy wariant: `n_train_scenes`,
  `vertical` (n, mae, bias, p90_abs, share_in_bounds), `by_band`. Foldy i sceny testowe identyczne we wszystkich
  wariantach (test = B/R jak dziś); filtr dotyczy tylko scen budujących.

- [ ] **Step 1:** Test: `run_folds` z `train_filter` wykluczającym C nie przekazuje scen C do `compute_bounds`
  (monkeypatch `bottom.compute_bounds` rejestrujący `is_c`), a zbiory testowe są równe dla wariantów.
- [ ] **Step 2:** Uruchom → FAIL.
- [ ] **Step 3:** Zaimplementuj; `12_holdout.py` używa `run_folds` z filtrem „wszystkie” (wynik identyczny —
  sprawdź jak w Task 4). `12a` liczy trzy warianty.
- [ ] **Step 4:** Testy PASS; `make holdout-levels`; zapisz liczby wariantów do ledgera.
- [ ] **Step 5:** Commit `eval: hold-out by water-level source (no C, B/R only)`.

### Task 6: Powierzchnia KŻ dla głębokiej części i LOO

**Files:**
- Create: `pipeline/mielizna/kz_deep.py`
- Test: `pipeline/tests/test_kz_deep.py`

**Interfaces:**
- Consumes: `variant_d.kz_surface(spots, contours, grid, gravel)`, `kz.load_qc_spots`.
- Produces:
  - `DEEP_CONTOURS = (192.5,)`
  - `deep_surface(spots, contours, grid, gravel) -> np.ndarray` (= `kz_surface` z poziomicami filtrowanymi do
    `DEEP_CONTOURS`)
  - `loo(spots, contours, grid, gravel, mask: np.ndarray) -> dict` → `{"n", "n_skipped", "mae", "bias", "p5", "p95",
    "p90_abs", "below_192_9": {...same...}, "errors": [{"id", "z", "pred", "err"}]}`; punkty brane do LOO: te, których
    piksel leży w `mask` (zawsze woda) i poza żwirownią.

- [ ] **Step 1:** Testy na syntetycznej płaszczyźnie `z = 190 + 0,001·x` z 30 punktami i poziomicą 192,5: LOO ≈ 0
  (|mae| < 1e-6); punkt na wierzchołku otoczki → `n_skipped ≥ 1`, brak NaN w wyniku; poziomica 195,0 w danych
  wejściowych nie wpływa na `deep_surface`; znak `err` dodatni, gdy powierzchnia wyżej niż punkt.
- [ ] **Step 2:** Uruchom → FAIL.
- [ ] **Step 3:** Zaimplementuj (LOO: dla każdego punktu `deep_surface` bez niego; odczyt w pikselu punktu).
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `model: KŻ deep-bottom surface (no 195 m contour) and leave-one-out`.

### Task 7: Rastry łączone (kalibracja + KŻ) i skrypt 14

**Files:**
- Create: `pipeline/mielizna/combine.py`, `pipeline/14_kz_deep.py`
- Modify: `pipeline/Makefile` (cel `kz-deep`, zależny od `holdout`, `variant-d`)
- Test: `pipeline/tests/test_combine.py`, `pipeline/tests/test_independence.py`

**Interfaces:**
- Produces:
  - `combine.merge_kz(z_lo, z_hi, kz, p5, p95) -> tuple[z_lo, z_hi, source(uint8), conflict(bool)]` (reguła z Global
    Constraints; działa tylko tam, gdzie `z_lo == −inf` i `kz` skończone).
  - `data/processed/model/<okres>_kz/`: `bottom_zlo.tif`, `bottom_zhi.tif` (float32, ±∞ zapisane jako ±inf),
    `bottom_source.tif` (uint8, bit 0 = kz, bit 1 = kz_conflict), `meta.json` (`period`, `p5`, `p95`, `deltas`,
    `inputs_sha1`).
  - `data/processed/eval/kz_loo.json` (wynik `loo` bez listy `errors` w wersji skróconej + `errors` pełne),
    `data/processed/eval/kz_deep.json` (pokrycie, udział sprzeczności, udziały stref przed/po przy h ∈ {194.5,
    193.6}, draft 0.5, margin 0.3).
- `14_kz_deep.py` czyta `model/<okres>/` (okres z `model_choice.json`), `calibration.json`, KŻ; kolejność:
  `calibration.apply` → `merge_kz`.

- [ ] **Step 1:** Testy `merge_kz`: piksel satelitarny skończony — bez zmian; −∞ + kz = 190, p5 = −1,4, p95 = 5,5,
  z_hi = 193,05 → (184,5; 191,4; kz; False); −∞ + kz = 193,0 → z_hi = min(193,05; 194,4) = 193,05, z_lo = 187,5;
  sprzeczność kz = 199 → (−∞; 193,05; satellite; True); −∞ bez kz — bez zmian.
- [ ] **Step 2:** `test_independence.py`: teksty `08_evaluate.py`, `10_kz_compare.py`, `12_holdout.py`,
  `12a_holdout_levels.py`, `13_error_budget.py` nie zawierają `_kz"`, `_kz/` ani `"_kz` (grep na źródle).
- [ ] **Step 3:** Uruchom → FAIL; zaimplementuj; PASS.
- [ ] **Step 4:** `make kz-deep`; zapisz do ledgera p5, p95, n, pokrycie, udział sprzeczności, udziały stref.
- [ ] **Step 5:** Commit `model: combined bottom rasters (calibrated + KŻ deep) in model/<period>_kz`.

### Task 8: Backend — rastry łączone, wersja, pola punktu, obrys KŻ

**Files:**
- Modify: `backend/app/data.py`, `backend/app/depth.py`, `backend/app/point.py`, `backend/app/schemas.py`,
  `backend/app/main.py`, `backend/app/zones.py` (tylko `z_max_floor`, jeśli dotyczy)
- Modify: `frontend/src/api/schema.ts` (regeneracja)
- Test: `backend/tests/test_data.py`, `test_point.py`, `test_api_point.py`, `test_api_zones.py`,
  nowy `test_api_kz_deep.py`, `backend/tests/conftest.py` (syntetyczny `model/all_kz/`)

**Interfaces:**
- `depth.combined_bounds(sat: Bounds, kz_dir: Path) -> Bounds` (gdy brak katalogu: zwraca `sat`).
- `Products.version = f"{period}-{meta['version']}" + (f"-kz{sha}" if combined else "")`, `sha` z
  `meta.json.inputs_sha1` + bajtów `kz_loo.json`.
- `Products.z_max_floor` z surowego `sat.z_hi`.
- `PointResponse`: `bottom_source: Literal["satellite", "kz"]`, `kz_conflict: bool`, `kz_interp: {"p5": float,
  "p95": float} | None` (wypełnione, gdy `bottom_source == "kz"`).
- `GET /api/kz-deep` → GeoJSON FeatureCollection (EPSG:4326, 1 obiekt: obszar `source == kz`, właściwości
  `attribution`, `note`), ETag jak `/api/gravel` (`static_json`), pusta kolekcja bez rastrów łączonych.
- `load_eval` czyta też `calibration`, `kz_loo`, `kz_deep`, `holdout_level_sources`.

- [ ] **Step 1:** Testy (syntetyczne): punkt w pikselu KŻ → `kind = always_water`, `bottom_source = kz`, głębokości
  skończone; ten sam piksel przy h ≤ z_lo → `kind = land`; piksel sprzeczny → `kz_conflict = True`, `bottom_source =
  satellite`, `depth_max = None`; brak `model/all_kz/` → wszystko jak dziś (`bottom_source = satellite`, `/api/kz-deep`
  pusty); zmiana bajtów `kz_loo.json` zmienia ETag `/api/zones`; `z_max_floor` równy satelitarnemu przy obecności KŻ.
- [ ] **Step 2:** FAIL → implementacja → `uv run pytest -q` PASS. Test regresji z Task 1 przestaje dotyczyć
  danych z KŻ: uruchom go z `MIELIZNA_NO_KZ=1` (zmienna, która wyłącza wczytanie rastrów łączonych; dodaj do
  `Settings`) — musi dalej przechodzić.
- [ ] **Step 3:** Regeneruj `schema.ts` (skrypt z `frontend/package.json`), `npm run typecheck` PASS.
- [ ] **Step 4:** Commit `api: combined bottom (calibrated + KŻ), bottom_source on /api/point, /api/kz-deep`.

### Task 9: Frontend — popup i warstwa „Dno wg mapy KŻ”

**Files:**
- Modify: `frontend/src/vm/usePointVm.ts`, `frontend/src/api/client.ts`, `frontend/src/vm/queryClient.ts`,
  `frontend/src/components/map/{layers.ts,MapView.tsx,types.ts}`, `frontend/src/components/panel/LayersControl.tsx`,
  `frontend/src/vm/useMapPageVm.ts`
- Create: `frontend/src/vm/useKzDeepVm.ts`
- Test: `frontend/src/vm/usePointVm.test.tsx`, `frontend/src/vm/useKzDeepVm.test.tsx`,
  `frontend/src/components/map/layers.test.ts`

**Interfaces / copy (dokładne teksty):**
- Wiersz popupu dla `bottom_source = kz`: term „Dno”, desc „mapa KŻ 2023 (orientacyjne; błąd interpolacji od
  −{p95} do +{|p5|} m)” (liczby z `kz_interp`, format `fmtNum(·, 1)`).
- Dla `satellite`: term „Dno”, desc „model satelitarny”.
- `kz_conflict`: wiersz ostrzegawczy „Mapa KŻ jest tu sprzeczna z satelitą — pokazujemy tylko model satelitarny.”
- Zastrzeżenie przy `kz`: „Mapa KŻ opisuje dno z 2023 r.; poniżej 192,5 m jest orientacyjna.”
- `always_water` z `bottom_source = kz`: wartość jak dla `model` (zakres głębokości, strefa, `clearanceNote`).
- `RANGE_CAVEAT` → „Przedział obejmuje dno w ok. 90 % sprawdzonych przypadków.” (po kalibracji; liczba z meta, gdy
  dostępna — `calibration.coverage_after`, zaokrąglona do pełnych %).
- Warstwa: nazwa „Dno wg mapy KŻ”, domyślnie włączona, kreskowanie odróżnialne od żwirowni, atrybucja „Mapa KŻ Nysa
  (W. Wróblewski, 2023)”.

- [ ] **Step 1:** Testy VM dla trzech przypadków (kz, satellite, conflict) i warstwy (pusta kolekcja → brak warstwy).
- [ ] **Step 2:** FAIL → implementacja → `npm test` i `npm run typecheck` PASS.
- [ ] **Step 3:** Commit `ui: bottom source in popup and KŻ deep-bottom layer`.

### Task 10: Budżet błędu — pole KŻ LOO

**Files:**
- Modify: `pipeline/13_error_budget.py`, `backend/app/schemas.py` (`ValidationBand.kz_loo: KzLoo | None`),
  `backend/app/main.py` (budowa `Validation`), `frontend/src/components/method/ValidationSection.tsx`,
  `frontend/src/vm/useMethodVm.ts`, `frontend/src/api/schema.ts`
- Test: `pipeline/tests/test_budget.py` (lub test `build`), `backend/tests/test_api_meta.py`,
  `frontend/src/vm/useMethodVm.test.tsx`

- [ ] **Step 1:** Test `build(..., kz_loo=...)`: pasmo `<192.9` ma `kz_loo = {n, mae, p5, p95}` z
  `kz_loo.below_192_9`, `range_m` dalej `None`, nowa notka „Błąd interpolacji mapy KŻ (punkt odłożony, n = …): MAE …
  m; to błąd mapy względem samej siebie, nie modelu.”; bez pliku `kz_loo.json` — jak dziś.
- [ ] **Step 2:** FAIL → implementacja (13 czyta opcjonalnie `kz_loo.json`) → PASS; regeneruj `schema.ts`; UI:
  w wierszu `<192.9` tekst „błąd interpolacji KŻ: MAE … m” zamiast „brak danych”, kolumna zakresu dalej „—”.
- [ ] **Step 3:** `make error-budget`; testy backend + frontend PASS.
- [ ] **Step 4:** Commit `eval: KŻ interpolation error in the deep band of the error budget`.

### Task 11: Raport, „O metodzie”, uzupełnienie przewodnika

**Files:**
- Modify: `docs/raport.md` (nowa sekcja „Dno głębokiej części z mapy KŻ”, akapit w §5.5 o eksperymencie źródeł
  poziomu, akapit o kalibracji w §5.6, wiersze tabeli §5.1), `frontend/src/vm/useMethodVm.ts` i komponenty metody
  (akapit + wiersz), `docs/jak-czytac-kod.md` (kroki 6–7: kalibracja i KŻ, przykład B: piksel „zawsze woda” z KŻ)
- Test: `pipeline/tests/test_report_numbers.py` (markery `<!-- eval:... -->` dla `kz_loo.json`, `kz_deep.json`,
  `calibration.json`, `holdout_level_sources.json`), `backend/tests/test_guide_example.py` (przykład B przez
  `combine.merge_kz`-równoważną ścieżkę backendu)

- [ ] **Step 1:** Treść raportu: reguła, LOO (n, MAE, P5/P95, pominięte), sprzeczności i związek z poziomicą 195 m,
  udziały stref przed/po przy 194,5 i 193,6 m, ograniczenia (2023, orientacyjne < 192,5 m, LOO ≠ całkowity błąd,
  bias K5 +0,30 m), wynik eksperymentu poziomów (także „brak poprawy”, jeśli tak wyszło), kalibracja (δ na pasmo,
  pokrycie przed/po). Każda liczba z markerem eval.
- [ ] **Step 2:** `uv run pytest tests/test_report_numbers.py` i `tests/test_guide_example.py` PASS; `npm test` PASS.
- [ ] **Step 3:** Commit `docs: report, method page and guide for KŻ deep bottom and calibration`.
