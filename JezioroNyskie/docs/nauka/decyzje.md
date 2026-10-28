# Decyzje (ledger): co postanowiono, dlaczego, ile kosztuje pomyłka, gdzie to jest w kodzie

Źródło: `.superpowers/sdd/2026-10-27-plan1-pipeline-model-dna/progress.md` (rozstrzygnięcia R1–R25 i decyzja użytkownika U1).
„Ścieżki" są względem `pipeline/`. Gdy dwie reguły się różnią, wygrywa późniejsza (kolumna „uwagi").

## 1. Tabela decyzji

| # | Co | Dlaczego (po ludzku) | Koszt pomyłki | Gdzie w kodzie |
|---|---|---|---|---|
| R1 | `is_usable` czyta `cfg["scene_filter"]["exclude_dates"]` (słownik, nie atrybuty); wpis to `{date, reason}` lub zwykły tekst | konfiguracja z YAML to zwykły słownik | trywialna zmiana nazwy | `mielizna/s2.py: is_usable` |
| R2 | Etykiety w `data/reference/labels.gpkg`, nie `.geojson` | GeoJSON w EPSG:2180 nie jest standardem | zmiana nazwy pliku | `mielizna/labels.py`, `config.yaml` |
| R3 | `predict_scene(bands, scl, bundle, date, otsu_t)`, SCL jest argumentem | chmura → 255 wymaga warstwy SCL | zmiana jednego wywołania | `mielizna/classify.py: predict_scene` |
| R4 | Makefile: `labels` tylko generuje kandydatów, `label-ui` otwiera okno; `all` staje przed `rf`, jeśli < 150 etykiet | etykietowanie robi człowiek | edycja Makefile | `Makefile` (`check-labels`) |
| R5 | W Task 1 do repo trafiają też istniejące pliki: BRIEF, `scripts/`, `docs/design/`, PDF KŻ (7,2 MB), `data/raw/check/*` | to wejścia, których brief oczekuje w repo | `git rm` | historia git (Task 1) |
| R6 | `config.yaml: paths.reference` = `reference` (było `raw/check`) | brief trzyma pliki odniesienia w `data/reference` | brak (nic go nie używało) | `config.yaml` |
| R7 | Offset odbicia zawsze 0,0 (Earth Search ma dane zharmonizowane); `raster:bands.offset = -0,1` jest błędny; strażnik `check_harmonized` | zmierzyliśmy wodę w SWIR: 9–58 DN w każdym okresie | wszystkie odbicia po 2022 przesunięte o 0,1 (strażnik to wychwytuje) | `mielizna/s2.py: reflectance_offset, check_harmonized` |
| R8 | Deduplikacja po (satelita, kafel, data), wygrywa najwyższa wersja przetwarzania, potem najwyższy `_N`; jedna scena na datę, bez sklejania satelitów | ten sam obraz bywa wielokrotnie w katalogu | utrata kilku duplikatów z tej samej doby | `mielizna/s2.py: dedupe_items, group_acquisitions` |
| R9 | `task-4-decisions.md` ważniejsze niż `task-4-brief.md` | brief miał błędne założenia o offsecie i progu chmur (max_tile_cloud 60) | – | `config.yaml: scene_filter` |
| R10 | Strażnik offsetu: 5. percentyl SWIR16 nad wodą > 900 DN → odrzuć; trafia do `scenes_pass2_rejected.csv`; pass 2 próbuje następnej akwizycji tej daty | mediana dawała fałszywy alarm na 2019-06-15 (p5 ≈ 430) | jedna jasna/mglista scena wchodzi do puli | `mielizna/s2.py: check_harmonized`, `01_fetch_s2.py` |
| R11 | Pass 2 usuwa `{date}.tif` dla dat z `exclude_dates`; dalej sceny wybiera się z CSV + exclude_dates, nigdy przez glob katalogu `s2/` | wykluczone pliki nie mogą wrócić jako „pliki w katalogu" | brak | `01_fetch_s2.py`, `mielizna/s2.py: usable_dates` |
| R12 | Akceptujemy stratę 2022-01-07 | tylko stara kopia jp2 bez COG, data zimowa | jedna scena | – (decyzja o danych) |
| R13 | Otsu = `skimage.filters.threshold_otsu` (zamiast własnej implementacji); testy z nakładającymi się modami | standardowa implementacja łatwiej do obrony; różnica < 0,004 progu | brak mierzalnego | `mielizna/otsu.py` |
| R14 | Jedna lista scen: `s2.usable_dates(cfg)` = CSV is_usable + exclude − odrzucone z pass 2; brak COG dla daty z listy = błąd | trzy skrypty (6/7/8) nie mogą mieć różnych list | brak | `mielizna/s2.py: usable_dates` |
| R15 | Trening ludzki: `source == "human"` i etykieta ∈ {water, land}; `skip` to osobna etykieta; ≥150 liczy tak samo | „pomiń" to niepewność, nie klasa | zmiana filtra w Task 7 | `mielizna/labels.py: human_class_labels, CLASS_LABELS` |
| R16 | Wśród komunikatów tej samej doby: czas odczytu najbliższy 10:00 UTC (remis → wcześniejszy); parser godziny; kolumna `reading_utc` | zdjęcie jest ok. 10:00 UTC | kilka cm w ~3 scenach powodziowych | `mielizna/bulletins.py: choose_bulletin` |
| R17 | Przegląd 24 podejrzanych etykiet „w ciemno": stara etykieta w `label_v1`, nowa kolejka bez starej; potem 100 punktów `shore_low` | sprawdzić, czy to błąd etykiet | brak (stare etykiety zachowane) | `mielizna/labels.py: mark_suspect, sample_extra`, `tools/label_server.py`, `04a_label_candidates.py --mark-suspect/--append-low` |
| R18 | Próg wody t* ∈ {0,50..0,90}, jednostronny, maksymalizuje BA, wybierany zagnieżdżonym CV; wynik główny zostaje przy 0,5 | błąd „ląd jako woda" jest groźny (płycizna wygląda na bezpieczną) | strefy bardziej zachowawcze | `mielizna/rf.py: _choose_threshold, _nested_threshold, final_threshold` |
| R19 | Zapis P(woda) jako uint8 do estymatora z minimalizacją błędu — **zastąpione** (decyzja Task 11: nie używamy `proba/`) | estymator zostaje liczący | tylko miejsce na dysku | `04_classify.py` (zapis `proba/`) |
| R20 | Strażnik radiometrii: p99 któregokolwiek pasma < 0,01 (≥1000 ważnych px) = scena uszkodzona; 2024-09-01 wykluczona | scena miała DN = 1 w czerwonym/NIR/SWIR | 1 scena + retrening (godziny, ok. 550 dopasowań RF) | `mielizna/s2.py: check_radiometry`, `config.yaml` |
| R21 | QC sceny bez etykiet: rdzeń (brzeg o 200 m) znany ≥50%, woda w rdzeniu ≥95%, RF/Otsu ≥ 0,90; flagi, bez retreningu | wykryć sceny, gdzie RF się wysypał | ±3% obserwacji | `mielizna/classify.py: scene_qc` |
| R22 | t* z uśrednionej krzywej BA(t) po 10 powtórzeniach OOF (nie z jednego losowania); poprawia R18 | pojedynczy argmax skakał 0,60–0,85 na tych samych danych | ±0,05 t*, 10× czasu | `mielizna/rf.py: THRESHOLD_REPEATS, _mean_threshold_curve` |
| R23 | „Luka 0,44 m" to nie układ wysokości: 8 letnich scen 2020 + rozcieńczenie regresji; bez korekty; krzywa z powierzchni **Otsu** zamiast RF; σ(C) = RMSE LOYO | RF nasyca powierzchnię przy niskiej wodzie (błoto = woda) | C zbyt niskie przy niskim poziomie Otsu (groźne), mała ekspozycja | `mielizna/levels.py: curve_areas, AreaLevelCurve`, `06_water_levels.py` |
| R24 | Obserwacje **wody** scen C = 255 (nieznane) wszędzie; ląd C zostaje; flaga 8 informacyjna. **Zastępuje** wcześniejszą regułę „C nie ustala z_max, jeśli jest woda nie-C" | stara reguła zmieniła 67 px, a C nadal obniżało z_max >5 cm na 38,6% px pasma 195–196 m | piksele widziane jako woda tylko przez C tracą górną granicę → „niebezpieczne" | `mielizna/bottom.py: compute_bounds, FLAG_C_WATER_IGNORED` |
| R25 | `combine_evidence`: woda tylko gdy RF=1 **i** Otsu=1; ląd gdy RF=0 **lub** Otsu=0 (nawet gdy druga maska to 255); reszta = 255. Doprecyzowuje U1 | wcześniej Otsu=255 wymazywało ląd z RF (0,2% px miało z_max niżej niż RF-only); teraz dowodliwie 0 | nieco więcej lądu przy odciętych zatokach (konserwatywnie) | `mielizna/bottom.py: combine_evidence`, asercja w `07_bottom_model.py` |
| **U1** | **Decyzja użytkownika**: „możemy podejść ostrożniej — listopad to już poza sezonem". Za wodę w modelu dna: RF ∧ Otsu; ląd = RF=ląd lub Otsu=ląd | RF uznaje jasne błoto za wodę (psuje bezpieczną stronę) | strefy bardziej zachowawcze, szersze przedziały (z_max wyżej o >5 cm na 22,4% px; nigdy niżej niż RF-only, R25) | `mielizna/bottom.py: combine_evidence`, `model_meta.json: evidence` |

Uwagi do U1: sezonowość (listopad, poza sezonem) wpływa na domyślny zakres poziomów w aplikacji, **nie** na to, które sceny wchodzą do modelu — sceny
pozasezonowe niosą niskie poziomy, które mierzą płycizny. R22 zostaje (ostrożność wprowadza RF∧Otsu, nie wyższy próg).

## 1a. Decyzje planu 2 (backend)

Źródło: `.superpowers/sdd/2026-10-27-plan2-backend-api/progress.md` (rozstrzygnięcia R1–R12 tego planu; numeracja niezależna od planu 1).

- **B-R1** `create_app(settings=None, products=None, *, search_fn=None, load_fn=None)`: testy muszą wstrzykiwać wyszukiwanie i wczytanie scen, żeby nie łączyć się z siecią.
- **B-R2** Praca na gałęzi `feat/backend` bez osobnego worktree: `data/processed` (3,2 GB, poza git) jest potrzebne do testów `real`.
- **B-R3** Maski i statystyki odtwarzają się dokładnie, `proba` nie co do bitu: backend jej nie używa (R19 planu 1 zastąpione), więc nie ma skutku.
- **B-R4** Stopka commitu zadania 1 mówi „Sonnet 5.5", nie „Opus 5.5": nie przepisujemy historii dla jednej stopki.
- **B-R5** Asercja `reference_grid()` jest w `SceneContext.build` (ścieżka na żywo), nie w `load_products`: fixture 20×30 złamałby asercję przy starcie, a strefy i punkt czytają siatkę z rastra.
- **B-R6** Wszystkie `*_pct` to (klasa ∧ akwen) / akwen × 100, więc suma = 100 (przy pustym akwenie 0); `*_km2` bez zmian, `danger_km2` wlicza ląd — to wynika z tekstu planu „udział w akwenie".
- **B-R7** Uproszczenie osobno na strefę (wymóg planu) zostawia szwy 12–21 tys. m² (~0,08%): zostaje, do rozważenia `coverage_simplify` na 3 geometriach, jeśli będzie widoczne na mapie (plan 3).
- **B-R8** Backend nie zmienia `os.environ`: funkcje pojemności dostają opcjonalny argument `table=`, tabela ładowana raz — bezpieczeństwo wątkowe przy odświeżaniu w tle.
- **B-R9** PNG niepewności: skala 2× z kropką 1 px na komórkę 2×2, nie 4×: po dekodowaniu ≈ 26 MB zamiast ≈ 100 MB (pamięć telefonu).
- **B-R10** Do pliku trafiają tylko werdykty danych (przyjęta, `not_usable`, radiometria, brak wody, `qc:*`); wyjątki przejściowe (sieć, brak modelu) idą do `last_error` i są ponawiane, `refresh()` nigdy nie rzuca — chwilowa awaria S3 nie może na stałe wyłączyć poziomu na żywo.
- **B-R11** Fallback z pipeline'u ma `ice_unverified = False`: sceny pipeline'u przeszły przegląd lodu (`exclude_dates`).
- **B-R12** `/api/zones` nie jest przycinane do obrysu jeziora OSM: AOI modelu (obrys + bufor) to misa zbiornika, a woda wychodzi poza obrys OSM (ok. 995 px bezpiecznych przy h 195,5, m 0) — niezwiązane z żadną rozbieżnością liczb (API = plan 1: 128 901 px przy m 0,3; 129 880 px przy m 0).

Wynik kontroli `real` (zadanie 11): ledger planu 1 liczył `safe_km2` z zapasem m = 0,3 w całym modelu; po R25 128 901 px = 12,890 km², API daje to samo, a przy m = 0 129 880 px = 12,988 km² — patrz `M5-backend.md` §6.

## 1b. Decyzje planu 3 (frontend)

- **F-R1** Warstwy komponent → VM → Query → klient wymuszone testem architektury i ESLintem (`no-restricted-imports`, `fetch`): reguła, której nikt nie pilnuje, znika po trzecim PR.
- **F-R2** `src/theme.ts` jest jedynym źródłem kolorów stref i skali poziomów (`levelColor`); test dryfu porównuje go z `tokens.css`, więc CSS i mapa nie rozjadą się po cichu.
- **F-R3** Popup kotwiczony przez `maplibregl.Marker` + portal Reacta, nie `maplibregl.Popup`: treść to zwykły komponent React z `role="dialog"`, fokusem i Esc.
- **F-R4** W trybie pojemności poziom `h` jest wyprowadzany (pojemność → `/api/capacity`), nie przechowywany osobno: mapa i panel zawsze pokazują ten sam poziom.
- **F-R5** Ruch suwaka w trybie pojemności przełącza tryb na rzędną; przycisk „Wróć do rzędnej" przywraca spójność, zamiast po cichu przeliczać pojemność.
- **F-R6** Teksty źródeł na `/metoda` są dosłownie z BRIEF §16 (z poprawkami §16.9) i dają się wskazać w briefie; liczby tylko z API.
- **F-R7** e2e (Playwright) w `frontend/e2e/`, poza Vitestem i `tsc`; pomijane bez `data/processed/model/all/`; zrzuty tylko z `SCREENSHOTS=1`. `@playwright/test` 1.63.0 przypięte pod Chromium 1243 już obecny w cache.
- **F-R8** `fitBounds` mapy uwzględnia panel (desktop) i dolny arkusz (mobile); wykryte dopiero na zrzucie z prawdziwej przeglądarki, jsdom tego nie pokaże.
- **F-R9** B-R7 (szwy stref) sprawdzone przy zoomie 15–16: niewidoczne, zostaje bez zmian.

## 2. Znane ograniczenia / do zrobienia (z listy „minor (deferred)" w ledgerze)

**Dane i pobieranie (Task 1–4)**
- `affine` importowane bezpośrednio, nie zadeklarowane w `pyproject.toml`.
- `data_path` czyta `config.yaml` przy każdym wywołaniu; `cfg or load_config()` traktuje `{}` jak brak.
- Ostrzeżenie CRLF→LF dla CSV w `data/raw/check` (brak `.gitattributes`).
- `capacity_to_level` czyta konfigurację i CSV przy każdym wywołaniu (przydałby się `lru_cache`); test monotoniczności dopuszcza remisy; brak testu NaN powyżej zakresu.
- Overpass: odpowiedź 200 z polem `remark` mogłaby trafić do cache; goły `StopIteration` przy braku relacji; adnotacja `-> Polygon` za wąska; brak testów MultiPolygon.
- 220 COG-ów ma uśrednione przeglądy SCL (tylko do wyświetlania; przed kontrolą jakości z przeglądów odbudować); `rasterio.shutil.copy` ma złe wcięcie; stary format CSV odrzuconych → `KeyError`.
- Task 5: prywatne funkcje `_nd`, `_window_stats` mają jednowierszowe docstringi.

**Etykietowanie (Task 6–7a)**
- `Backspace`: `preventDefault` po zwrocie z powtórzenia; odrzucony `fetch` zostawia stan zajętości (pomaga przeładowanie); `/api/unlabel` przyjmuje id automatyczne.
- Przegląd 24 podejrzanych był tylko częściowo „w ciemno" (pozycja w kolejce sugeruje wodę); wspomnieć przy szumie etykiet.
- Brak testów CLI strażników; nieużywany parametr `lake`; plik `.swp` w repo (ignorowany w `pipeline/.gitignore`).

**Komunikaty (Task 9)**
- `_READ_RZGW` nie łapie lokalnego wariantu „na godz. HH:MM"; RED tylko przez `ImportError`; `_candidates` nie ma testu grupowania.

**Klasyfikacja (Task 7–8)**
- Docstringi: `grouped_cv` ("3–6 ląd na fold" nieaktualne), `predict_water` ("identyczne z predict" nieprawdziwe przy P = 0,5 dokładnie), `_human_mask` bez docstringu, `scene_qc` ("7 flagged"); zdublowana linia `max_features`; za długie linie.
- Wilson wypisuje `-0.000`; `by_scene` w JSON ma niepodpisane dodatkowe dopasowania progu; wewnętrzne OOF grupowane po bloku.
- Ostrzeżenia joblib (84 tys. w pełnym zestawie testów — `filterwarnings` lub usunięcie przyczyny); ok. 550 dopasowań RF w `04b` (godziny, stąd Makefile nie retrenuje przy braku zmian); goły `assert` w `05`; `05` z `keep_default_na`.
- Uwaga systemowa: zatoka W/SW (P(woda) ≈ 0,55–0,75) daje plamistość (fałszywy ląd przy t* = 0,70), z bias w górę — porównać z głębokościami KŻ w planie 4; nie obniżać t*.

**Poziomy (Task 10)**
- `save_area_level_curve` zapisuje `NaN` dla `rmse_loyo` bez grup (powinno `null`); w logu reszta względem krzywej RF nieporównywalna; `curve_areas` milczy przy zdublowanych datach.

**Model dna (Task 11)**
- Porównanie z mapą KŻ (głębokości) i georeferencja K1 → plan 4.
- Warstwa ostrzeżeń o żwirowniach (obrys z mapy KŻ) → plan 4 (backend dodaje okno ostrzeżenia w planie 2).
- Plan 2: backend ma karmić krzywą powierzchnią Otsu (`area_source`), flaga 8 jest informacyjna (nie ostrzeżenie), frontend musi komunikować „dno poniżej 192,9 m nie obserwowano".
- Kontrola QGIS nałożenia `bottom_z.tif` na ortofotomapę jest ręczna; płat roślinny SW (z_max 196–197 m) do sprawdzenia w planie 4.
