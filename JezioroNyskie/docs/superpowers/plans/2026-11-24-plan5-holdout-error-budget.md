# Hold-out roczny i budżet błędu dna — plan wdrożenia

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zmierzyć błąd modelu dna na latach, których nie widział (hold-out roczny), zestawić wszystkie kontrole w budżet błędu wg pasm wysokości i pokazać to w raporcie i na stronie „O metodzie”.

**Architecture:** Czyste funkcje w `mielizna/holdout.py` i `mielizna/budget.py`; skrypty `12_holdout.py` (ciężki, przelicza `compute_bounds` na 7 fałdach) i `13_error_budget.py` (lekki, składa JSON-y oceny). 08 i 10 dostają po jednym nowym kluczu z rozbiciem na pasma budżetu. Backend czyta `holdout.json` i `error_budget.json` jak inne pliki eval; frontend dostaje sekcję „Jak sprawdziliśmy model”.

**Tech Stack:** Python 3 (uv, numpy, rasterio, pytest), FastAPI + pydantic, React + TypeScript (vitest, openapi-typescript).

**Spec:** `docs/superpowers/specs/2026-11-24-holdout-error-budget-design.md`

## Global Constraints

- Docstringi modułów i funkcji publicznych w stylu repo: „Co robi / Dlaczego tak / Wejście → wyjście / Jak to obronić”, po polsku.
- Liczby w raporcie tylko przez znaczniki `<!-- eval:plik.json:ścieżka -->` (gramatyka w `pipeline/tests/test_report_numbers.py`); `make test` musi przechodzić.
- Kroki eval w Makefile zależą tylko od kodu i plików eval (jak `evaluate`/`volume`), nigdy od łańcucha S2 → klasyfikacja → model.
- Istniejące klucze JSON-ów oceny nie zmieniają się; tylko nowe klucze.
- JSON-y zapisywane z `allow_nan=False` (NaN → `null`).
- Pasma budżetu: `"<192.9"` = (−∞, 192,9), `"192.9-194.8"` = [192,9, 194,8), `"194.8+"` = [194,8, +∞). Dolna granica włącznie.
- Fałdy: lata 2020–2026; test = sceny `h_method ∈ {B, R}` z okresu `all` (155 scen); trening = sceny okresu `all` bez roku fałdy. RF i krzywa C nie są trenowane od nowa (przeciek opisany w raporcie).
- Do zakresu w metrach wchodzą tylko hold-out, LiDAR (model `all`, MAE wprost, bez odejmowania biasu) i KŻ. Objętość i poziomy = kontekst. Pasmo `<192.9` bez liczby.
- Na stronie nie wolno pisać „pięć niezależnych źródeł”: pięć kontroli, trzy na danych niezależnych od satelity.
- Commity kończą się linią `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Piksele brzegowe sceny testowej, dla których model fałdy nie ma obu granic (np. poziom poniżej wszystkich poziomów treningu): muszą trafić do `share_no_pred`, a nie zniknąć z mianownika. Test w Task 1.
2. Scena testowa bez pikseli brzegowych lub z samymi 255 (chmury): pomijana i liczona w `n_skipped`, bez NaN w statystykach zbiorczych. Test w Task 1 i Task 2.
3. Piksel UNRESOLVED (dwa treningowe poziomy równe, sprzeczne): `predict_water` zwraca 255, nie 0. Test w Task 1.
4. Pasmo bez danych w źródle (np. LiDAR 192,9–194,8 m, `n = 0`): `combine_band` pomija źródło, komórka `range_m = null` z notą, JSON bez NaN. Test w Task 4.
5. Brak `holdout.json` / `error_budget.json` na serwerze: API zwraca `validation: null` i pola hold-out `null`, strona ukrywa sekcję. Testy w Task 6 i Task 7.

---

### Task 1: `mielizna/budget.py` (pasma) i `mielizna/holdout.py` (funkcje hold-out)

**Files:**
- Create: `pipeline/mielizna/budget.py`, `pipeline/mielizna/holdout.py`
- Test: `pipeline/tests/test_holdout.py`

**Interfaces:**
- Consumes: `bottom.FLAG_*`, `volume.bottom_bounds(model) -> {"low","mid","high","core"}` (NaN → ±inf), `shoreline.mask_to_shoreline(mask, transform)`, `kz_compare._dists(a, b)` → przemianować na publiczne `kz_compare.line_distances(a, b, step=LINE_STEP_M) -> np.ndarray` (zaktualizować wywołania w `kz_compare.py`).
- Produces:
  - `budget.BANDS: dict[str, tuple[float, float]]` (wartości z Global Constraints), `budget.band_of(z: np.ndarray) -> np.ndarray[str]`.
  - `holdout.year_folds(sel: pd.DataFrame, years=range(2020, 2027), test_methods=("B","R")) -> list[holdout.Fold]`; `Fold` = dataclass `(year: int, train: np.ndarray[int], test: np.ndarray[int])` (indeksy wierszy `sel`). Rok bez scen testowych pomijany.
  - `holdout.shore_pixels(ev: np.ndarray) -> np.ndarray[bool]`: piksel 1 z co najmniej jednym 4-sąsiadem 0.
  - `holdout.predict_water(model: dict, h: float) -> tuple[np.ndarray[uint8], np.ndarray[bool]]`: (maska 0/1/255, „niepewne” = low < h < high). Woda gdy `mid < h`; `mid` NaN → 255.
  - `holdout.vertical_errors(model: dict, shore: np.ndarray[bool], h: float) -> dict`: `{"err": z − h (piksele brzegowe z obiema granicami), "in_bounds": bool tablica dla tych pikseli (z_min ≤ h ≤ z_max), "n_shore": int, "n_pred": int}`.
  - `holdout.iou(pred: np.ndarray, ref: np.ndarray, zone: np.ndarray[bool]) -> float`: IoU wody na pikselach `zone` z oboma wartościami ≠ 255; pusty mianownik → NaN.
  - `holdout.shoreline_distance(pred, ref, transform) -> dict`: `{"mean_sym", "median", "p90"}` w m (przewidywana → obserwowana dla median/p90); pusta linia → NaN.
  - `holdout.summarize(err: np.ndarray, in_bounds: np.ndarray, n_shore: int) -> dict`: `{"n", "bias", "mae", "rmse", "p90_abs", "share_in_bounds", "share_no_pred"}`; `share_no_pred = 1 − n/n_shore`.

- [ ] **Step 1: Write failing tests** w `pipeline/tests/test_holdout.py` (styl `test_volume.py`, małe tablice ręcznie):
  - `test_year_folds_split`: 4 sceny (2019 C, 2020 B, 2020 A, 2021 R) → foldy dla 2020 i 2021; fold 2020: `test == [1]`, `train == [0, 3]`; scena A z 2020 nie jest ani w test, ani w train.
  - `test_shore_pixels_4_neighbours`: `[[1,1,0],[1,1,255]]` → `[[False,True,False],[False,False,False]]` (255 nie jest lądem; skośny sąsiad się nie liczy).
  - `test_predict_water_rules`: piksele (przedział 193–194, h=193.8 → woda i niepewny), (przedział 193–194, h=194.5 → ląd, pewny), (zawsze woda z_max=193.05, h=192.95 → woda), (zawsze ląd z_min=196, h=195 → ląd), (UNRESOLVED: z, z_min, z_max NaN → 255).
  - `test_vertical_errors_counts_unpredicted`: 3 piksele brzegowe, 1 bez granic → `n_shore == 3`, `n_pred == 2`; `summarize(...)["share_no_pred"] == pytest.approx(1/3)`.
  - `test_iou_empty_zone_is_nan`, `test_iou_ignores_255`.
  - `test_shoreline_distance_shifted_square`: kwadrat wody 10×10 px przesunięty o 1 px → `median == pytest.approx(10, abs=1)`.
  - `test_band_of_edges`: `band_of([192.89, 192.9, 194.79, 194.8])` → `["<192.9", "192.9-194.8", "192.9-194.8", "194.8+"]`.
- [ ] **Step 2:** `cd pipeline && uv run pytest tests/test_holdout.py -q` → FAIL (brak modułu).
- [ ] **Step 3:** Zaimplementuj `budget.py` (tylko `BANDS`, `band_of`) i `holdout.py` z interfejsami jak wyżej; przemianuj `_dists` → `line_distances`.
- [ ] **Step 4:** `uv run pytest tests/test_holdout.py tests/test_kz_compare.py tests/test_kz_contours.py -q` → PASS.
- [ ] **Step 5:** Commit `eval: hold-out helpers (folds, shore pixels, water prediction, metrics)`.

### Task 2: `12_holdout.py`, cel `make holdout`, rysunek

**Files:**
- Create: `pipeline/12_holdout.py`
- Modify: `pipeline/Makefile` (zmienna `EVALHO := $(PROC)/eval/holdout.json`, cel `holdout`, wpis w `.PHONY` i `help`)
- Test: `pipeline/tests/test_holdout.py` (dopisać test agregacji)

**Interfaces:**
- Consumes: wszystko z Task 1; `bottom.select_scenes`, `bottom.combine_evidence`, `bottom.compute_bounds(..., is_c=..., k_sigma=1.0)`, `bottom.read_model(proc/"model"/"all")`, ładowanie siatki/AOI/scen jak w `07_bottom_model.main` (`reference_grid(cfg)`, `aoi_mask`, `load_stacks`-owe czytanie masek `masks/` i `masks_otsu/`), okres `cfg["periods"]["all"]`.
- Produces: `data/processed/eval/holdout.json` o kluczach:
  - `method` (opis tekstowy), `leakage_note` (RF i krzywa C nie trenowane od nowa), `n_folds`, `n_test_scenes`, `n_skipped`;
  - `holdout` i `in_sample`: `{"vertical": summarize(...), "iou_zone": {"median","p10","p90"}, "iou_lake": {...}, "share_uncertain": {...}, "shore_dist_m": {"median","p90"}}` (rozkłady po scenach);
  - `by_fold`: `{"2020": {"n_scenes", "vertical": summarize(...), "iou_zone_median"}, ...}`;
  - `by_period`: klucze `"2020-2023"`, `"2024"`, `"2025-2026"` z `vertical`;
  - `by_band`: klucze z `budget.BANDS`, `vertical` liczone wg `band_of(h_t sceny)` (pasmo bez scen → `{"n": 0}`);
  - plik `docs/img/eval-holdout.png`: rozkład błędu pionowego (box/violin) wg pasm, hold-out vs w próbie.
- Funkcja testowalna: `aggregate(per_scene: list[dict]) -> dict` w `12_holdout.py` lub `holdout.py` (decyzja implementującego), łączy tablice `err`/`in_bounds` scen w `summarize`.

Strefa IoU: piksele, gdzie serwowany model ma obie granice albo `n_conflict > 0` (z `read_model`: flagi `FLAG_CONFLICT` lub skończone `z`). In-sample = serwowany model `all` z dysku na tych samych scenach testowych.

- [ ] **Step 1: Write failing test** `test_aggregate_skips_empty_scenes`: dwie sceny, jedna z `n_shore == 0` → `n_skipped == 1`, `vertical["n"]` równe liczbie z drugiej sceny, w wyniku brak NaN (`json.dumps(..., allow_nan=False)` nie rzuca).
- [ ] **Step 2:** Uruchom → FAIL.
- [ ] **Step 3:** Zaimplementuj `aggregate` i skrypt `12_holdout.py` (docstring repo, logowanie do `processed/logs/12_holdout.log`, `combine_evidence` raz dla wszystkich scen, potem fałdy).
- [ ] **Step 4:** `uv run pytest tests/test_holdout.py -q` → PASS; `make holdout` → plik powstaje; sprawdź: `n_folds == 7`, `n_test_scenes + n_skipped == 155`, `holdout.vertical.mae >= in_sample.vertical.mae` (jeśli nie, zatrzymaj się i zgłoś: to podejrzane, nie poprawiaj na siłę).
- [ ] **Step 5:** Commit `eval: yearly hold-out of the bottom model (12_holdout, make holdout)` (z `holdout.json`, jeśli inne pliki eval są w repo; jeśli nie, tylko kod i rysunek).

### Task 3: LiDAR i KŻ w pasmach budżetu (nowe klucze w 08 i 10)

**Files:**
- Modify: `pipeline/mielizna/evaluate.py` (nowa funkcja), `pipeline/08_evaluate.py` (klucz `all_by_band`), `pipeline/mielizna/kz_compare.py` (nowa funkcja), `pipeline/10_kz_compare.py` (klucz `budget_bands` w `kz_points.json`)
- Test: `pipeline/tests/test_evaluate.py`, `pipeline/tests/test_kz_compare.py`

**Interfaces:**
- Consumes: `budget.BANDS`, `budget.band_of`, `evaluate.pooled_bottom`, `kz_compare._pairs_points`/`_pairs_cells`, `_block`.
- Produces:
  - `evaluate.split_pairs_by_band(parts: list[dict], key: str = "ref") -> dict[str, list[dict]]`: podział pikseli wg `band_of(p[key])`; klucze = `budget.BANDS`.
  - `bottom_vs_nmt.json["all_by_band"][band] = {**pooled_bottom(...), "split_on": "ref"}` (model `all`, podział wg wysokości NMT).
  - `kz_compare.compare_points_by_band(spots, model, gravel, grid, verdict="good") -> dict[str, dict]` (podział wg rzędnej KŻ, model `pre_flood` jak w istniejącym porównaniu; pasmo puste → `{"n": 0}`).
  - `kz_points.json["budget_bands"]`.
- [ ] **Step 1: Write failing tests:** `test_split_pairs_by_band_on_ref` (piksele ref 192.0/193.0/195.0 → po jednym w każdym paśmie, `z` nie wpływa na podział); `test_compare_points_by_band_empty_band` (wszystkie punkty ≥ 194,8 → `"192.9-194.8": {"n": 0}`).
- [ ] **Step 2:** Uruchom → FAIL.
- [ ] **Step 3:** Zaimplementuj; dopisz klucze w 08 i 10 bez ruszania istniejących.
- [ ] **Step 4:** `uv run pytest -q` → PASS; `rm ../data/processed/eval/model_choice.json && make evaluate && make kz-compare`; sprawdź, że stare klucze mają te same wartości co przed zmianą (`git diff` na JSON-ach albo porównanie skryptem, jeśli nie są w gicie) i nowe klucze istnieją.
- [ ] **Step 5:** Commit `eval: LiDAR and KŻ errors split into error-budget bands`.

### Task 4: `13_error_budget.py` i `budget.combine_band`

**Files:**
- Modify: `pipeline/mielizna/budget.py`
- Create: `pipeline/13_error_budget.py`
- Modify: `pipeline/Makefile` (`EVALEB := $(PROC)/eval/error_budget.json`; zależności: `13_error_budget.py mielizna/budget.py $(EVALHO) $(EVALCH) $(EVALKZ) $(EVALVOL)`)
- Test: `pipeline/tests/test_budget.py`

**Interfaces:**
- Consumes: `holdout.json["by_band"]`, `bottom_vs_nmt.json["all_by_band"]`, `kz_points.json["budget_bands"]`, `volume.json["layers"]`, `levels.json` (`h_sigma_by_method`, `a_vs_b`, `control_2024_09_12`, `control_r_2025`).
- Produces:
  - `budget.combine_band(sources: dict[str, dict]) -> dict`: wejście `{"holdout": {"n","mae","bias"}, "lidar": {...}, "kz": {...}}`; źródła z `n == 0` lub brakiem `mae` pomijane. Wynik `{"range_m": [min_mae, max_mae] | None, "dominant": nazwa z max MAE | None, "sources": {...wejście z n>0}}`.
  - `budget.volume_context(layers: list[dict], lo: float, hi: float) -> dict | None`: suma `dv_model`/`dv_table` warstw całkowicie w [lo, hi); `{"ratio", "covered": [h1_min, h2_max]}`; brak warstw → None.
  - `error_budget.json`: `{"bands": {band: {**combine_band(...), "volume": volume_context|None, "note": str}}, "level_context": {...}, "checks": [{"name", "compared_with", "result"}], "lidar_note": str}`. Pasmo `<192.9`: `range_m = null`, nota „brak danych: model nie ma dolnej granicy dna; sprawdzi to echosonda”. `lidar_note` = hipoteza o przesunięciu RZGW↔EVRF (z `bottom_vs_nmt.json["datum_note"]`), liczba się nie zmienia.
  - `checks`: 5 pozycji po polsku (hold-out roczny, LiDAR, mapa KŻ, objętość, poziomy wody); `result` = krótki napis z liczbą (przecinek dziesiętny), budowany z JSON-ów, nie wpisany na sztywno.
- [ ] **Step 1: Write failing tests:** `test_combine_band_skips_empty_sources` (lidar `n=0` → `range_m == [0.4, 0.6]` z holdout 0.4 i kz 0.6, `dominant == "kz"`); `test_combine_band_all_empty` (→ `range_m is None`, `dominant is None`); `test_volume_context_partial_cover` (warstwy 193.3–193.8 i 193.8–194.3 w paśmie 192.9–194.8 → `covered == [193.3, 194.3]`); `test_budget_json_has_no_nan` (wywołanie funkcji składającej z minimalnymi słownikami wejściowymi, `json.dumps(..., allow_nan=False)`).
- [ ] **Step 2:** Uruchom → FAIL.
- [ ] **Step 3:** Zaimplementuj `combine_band`, `volume_context`, skrypt i cel `make error-budget`.
- [ ] **Step 4:** `uv run pytest -q` → PASS; `make error-budget`; sprawdź, że `bands["194.8+"].sources.lidar.mae` ≈ wartość z `all_by_band["194.8+"]` i że `<192.9` ma `range_m: null`.
- [ ] **Step 5:** Commit `eval: error budget by bottom height band (13_error_budget)`.

### Task 5: Raport §5.5, §5.6, §5.1

**Files:**
- Modify: `docs/raport.md` (spis treści, §5.1 tabela, nowe §5.5 i §5.6), §9 Odtwarzalność (cele `holdout`, `error-budget`)
- Test: `pipeline/tests/test_report_numbers.py` (istniejący)

**Interfaces:**
- Consumes: `holdout.json`, `error_budget.json`, `bottom_vs_nmt.json["all_by_band"]`, `kz_points.json["budget_bands"]`.

Treść (po polsku, styl reszty raportu):
- **§5.5 Hold-out roczny:** cel; fałdy (7, lata 2020–2026, 155 scen B/R); referencja = dowód RF∧Otsu sceny (podłoga OA ok. 0,90); miary (błąd pionowy na linii wody — wyjaśnić, czemu dno ≈ `h_t` tam; IoU w strefie zmiennej; odległość linii); tabela hold-out vs w próbie; tabela per fałd i per okres (przed/2024/po powodzi); rysunek `img/eval-holdout.png`; przeciek (RF, krzywa C) i co hold-out mówi, a czego nie (nic poniżej 192,9 m).
- **§5.6 Jak zmierzyliśmy i zakres błędu (bez terenu):** akapit na każdą z 5 kontroli: co, z czym, wynik, czego nie pokrywa, czy dane niezależne od satelity; tabela budżetu (pasmo, źródła z MAE i bias, zakres, dominujące, kontekst objętości); nota o LiDAR (MAE wprost, hipoteza datum w nocie); uzasadnienie „zestawienie, nie suma”; co zamknie teren (echosonda dla < 192,9 m i pasma środkowego, Messtischblatt, zdjęcia przy niskiej wodzie).
- **§5.1:** wiersze „Hold-out roczny” i „Zakres błędu dna wg pasm”.
- Każda liczba ze znacznikiem eval.
- [ ] **Step 1:** Napisz sekcje.
- [ ] **Step 2:** `cd pipeline && uv run pytest tests/test_report_numbers.py -q` → PASS (każdy znacznik zgodny z JSON).
- [ ] **Step 3:** Commit `docs: report §5.5 hold-out and §5.6 error budget without field data`.

### Task 6: Backend: pola hold-out i `validation`

**Files:**
- Modify: `backend/app/data.py:70` (`EVAL_FILES` += `"holdout"`, `"error_budget"`), `backend/app/schemas.py` (`Accuracy`, nowe `Validation*`, `MetaResponse.validation`), `backend/app/main.py` (`eval_accuracy`, `build_meta`), `backend/openapi.json` (przez `backend/scripts/export_openapi.py`)
- Test: `backend/tests/test_api_meta.py`, `backend/tests/test_openapi.py`

**Interfaces:**
- Produces:
  - `Accuracy`: `holdout_mae`, `holdout_bias`, `holdout_in_bounds` (`float | None = None`), `holdout_n_scenes: int | None = None` — z `holdout.json["holdout"]["vertical"]` i `n_test_scenes`.
  - `ValidationCheck(BaseModel)`: `name: str`, `compared_with: str`, `result: str`.
  - `ValidationBand(BaseModel)`: `band: str`, `range_m: tuple[float, float] | None`, `dominant: str | None`, `note: str`.
  - `Validation(BaseModel)`: `checks: list[ValidationCheck]`, `bands: list[ValidationBand]` (kolejność: od najwyższego pasma), `lidar_note: str`.
  - `MetaResponse.validation: Validation | None = None`; `None`, gdy brak `error_budget` w `products.eval` albo struktura nie pasuje (walidacja pydantic nie może wywrócić `/meta`).
- [ ] **Step 1: Write failing tests:** `test_meta_validation_null_without_budget` (fixture bez pliku → `validation is None`, pola hold-out `None`); `test_meta_validation_from_budget` (fixture z minimalnym `error_budget.json` i `holdout.json` → 3 pasma, `<192.9` ma `range_m is None`, `accuracy.holdout_mae` równe wartości z pliku); `test_meta_validation_malformed_budget_is_null`.
- [ ] **Step 2:** `cd backend && uv run pytest -q tests/test_api_meta.py` → FAIL.
- [ ] **Step 3:** Zaimplementuj; wyeksportuj `openapi.json`.
- [ ] **Step 4:** `uv run pytest -q` → PASS (w tym `test_openapi`).
- [ ] **Step 5:** Commit `api: hold-out accuracy fields and validation block in /meta`.

### Task 7: Frontend: sekcja „Jak sprawdziliśmy model” i kafelek hold-out

**Files:**
- Modify: `frontend/src/api/schema.ts` (`npm run gen:api`), `frontend/src/vm/useMethodVm.ts`, `frontend/src/pages/MethodPage.tsx`, `frontend/src/pages/methodPage.css`
- Create: `frontend/src/components/method/ValidationSection.tsx`
- Test: `frontend/src/pages/MethodPage.test.tsx`, `frontend/src/pages/MethodPage.mobile.test.tsx` lub test VM, jeśli istnieje

**Interfaces:**
- Consumes: `meta.validation`, `meta.accuracy.holdout_*`.
- Produces: `MethodVm.validation?: { intro: string; checks: {name: string; comparedWith: string; result: string}[]; bands: {label: string; range: string; dominant: string; note: string}[]; lidarNote: string }`; kafelek `{label: 'Hold-out roczny (MAE)', value: fmtM(holdout_mae), sub: 'model bez danego roku vs linie wody tego roku, N scen'}` dodawany tylko, gdy `holdout_mae` nie jest null.

Copy (ustalone):
- Nagłówek `h2 id="m-val"`: „Jak sprawdziliśmy model”.
- `intro`: „Bez pomiarów w terenie zrobiliśmy pięć kontroli; trzy z nich używają danych niezależnych od satelity (LiDAR, mapa KŻ, tabela pojemności).”
- Podtytuł tabeli: „Zakres błędu dna”; kolumny „wysokość dna”, „typowy błąd”, „główne źródło”. Pasmo bez danych: „brak danych” i nota.
- Etykiety pasm: `≥ 194,8 m`, `192,9–194,8 m`, `< 192,9 m`; zakres `0,6–1,3 m` (fmtM, polski przecinek, półpauza).
- Pod tabelą `lidarNote` drobnym drukiem.
- Sekcja między „Dokładność modelu” a „Źródła danych”; brak `validation` → sekcja nie renderuje się.
- [ ] **Step 1: Write failing tests:** render z `validation` → nagłówek „Jak sprawdziliśmy model”, 5 pozycji listy, wiersz „< 192,9 m” z „brak danych”; render bez `validation` → brak nagłówka; kafelek hold-out obecny/nieobecny zależnie od `holdout_mae`; mobile: sekcja się renderuje.
- [ ] **Step 2:** `cd frontend && npx vitest run src/pages` → FAIL.
- [ ] **Step 3:** `npm run gen:api`, zaimplementuj VM, komponent, CSS (tokeny z `methodPage.css`, tabela przewija się poziomo w kontenerze na mobile, nie strona).
- [ ] **Step 4:** `npx vitest run` → PASS; `npx tsc --noEmit` → bez błędów.
- [ ] **Step 5:** Commit `ui: method page section on how the model was checked, hold-out tile`.

### Task 8: Weryfikacja końcowa

- [ ] **Step 1:** `cd pipeline && uv run pytest -q`; `cd backend && uv run pytest -q`; `cd frontend && npx vitest run && npx tsc --noEmit` → wszystko PASS.
- [ ] **Step 2:** Uruchom aplikację (`docker compose up` albo dev serwery jak w README), otwórz „O metodzie”, sprawdź sekcję na desktop i szerokości telefonu.
- [ ] **Step 3:** Zaktualizuj pamięć projektu (`nysa-field-validation-deferred`: hold-out zrobiony, budżet błędu istnieje).
