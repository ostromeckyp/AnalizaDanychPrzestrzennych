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
- **F-R4** W trybie pojemności poziom `h` jest wyprowadzany (pojemność → `/api/capacity-to-level`), nie przechowywany osobno: mapa i panel zawsze pokazują ten sam poziom.
- **F-R5** Ruch suwaka w trybie pojemności przełącza tryb na rzędną; przycisk „Wróć do rzędnej" przywraca spójność, zamiast po cichu przeliczać pojemność.
- **F-R6** Teksty źródeł na `/metoda` są dosłownie z BRIEF §16 (z poprawkami §16.9) i dają się wskazać w briefie; liczby tylko z API.
- **F-R7** e2e (Playwright) w `frontend/e2e/`, poza Vitestem i `tsc`; pomijane bez `data/processed/model/all/`; zrzuty tylko z `SCREENSHOTS=1`. `@playwright/test` 1.63.0 przypięte pod Chromium 1243 już obecny w cache.
- **F-R8** `fitBounds` mapy uwzględnia panel (desktop) i dolny arkusz (mobile); wykryte dopiero na zrzucie z prawdziwej przeglądarki, jsdom tego nie pokaże.
- **F-R9** B-R7 (szwy stref) sprawdzone przy zoomie 15–16: niewidoczne, zostaje bez zmian.

## 1d. Decyzje planu 4 (LiDAR, mapa KŻ, ocena dokładności)

Źródło: `.superpowers/sdd/2026-10-28-plan4-lidar-kz-evaluation/progress.md` (rozstrzygnięcia R1–R32 tego planu, numeracja niezależna od planów 1–3; tu z prefiksem P4).
Liczby i skutki: `docs/raport.md`, `docs/nauka/M7-lidar-kz.md`. Gdy dwie decyzje się różnią, wygrywa późniejsza (P4-R32 cofa P4-R31).

**Kolejność i kontrakty między zadaniami**
- **P4-R1** `kz.load_qc_spots(ocr, qc)` powstaje w zadaniu wariantu D (Task 7), a porównanie K5 (Task 9) go używa; działa bez pliku kontroli (wtedy tylko punkty z kolorem zgodnym i pewnością OCR ≥ 80): zależność kolejności zadań. Koszt: brak.
- **P4-R2** Wariant D zapisuje `kz/levels_d.csv`, a do `scenes.json` (`h_t_d`, `h_diff_d`) wpisuje go dopiero `06_water_levels.py`: inaczej każde ponowne uruchomienie 06 gubiłoby D. Koszt: mały.
- **P4-R27** Zadanie 9 (K5) czekało na kontrolę punktów przez autora, więc zadania 10 i 11 (API, Docker) poszły wcześniej. Koszt: brak.

**LiDAR i układy wysokości**
- **P4-R3** Test przeliczenia KRON86 → EVRF2007 używa siatek PROJ GUGiK, gdy są lokalnie, inaczej jest pomijany z powodem; wartość poprawki (+0,199 m) jest zapisana w `epochs.csv`. Koszt: brak.
- **P4-R4** Epoka 2017 zostaje jedną epoką mimo dwóch dni nalotu (27.02 i 25.03, rozstęp 26 dni): poziomy arkuszy są zgodne (193,37–193,40 m), a NMT to jeden produkt; `date` = pierwszy dzień, `date_span_days` = 26, a przy remisie epok wygrywa mniejszy rozstęp. Koszt: dopasowanie scen do epoki 2017 z błędem daty ≤ 26 dni.
- **P4-R5** Data 2011 z jednego z 4 arkuszy (pozostałe mają „GPS week time” bez daty); poziom = mediana wszystkich arkuszy (194,44 m). Koszt: data może być zła, jeśli ten arkusz pochodzi z innego nalotu.
- **P4-R6** Stałe 18 s sekund przestępnych przy dekodowaniu czasu GPS (jak w briefie); datę zmieniłyby tylko naloty tuż przed północą. Koszt: pomijalny dla nalotów dziennych.
- **P4-R7** NMT 2011 i 2017 przeliczany z KRON86 do EVRF2007 przed liczeniem wariantu A; poziom wody nalotu = `h_water_evrf`. Spójność z `h_datum` w `scenes.json`. Koszt: brak.

**Wariant A i pierwszeństwo poziomów**
- **P4-R8** Pierwszeństwo **R > B > A > C**: A tylko uzupełnia luki B (specyfikacja §5 pkt 7), zamiast wygrywać z B (wcześniejsze brzmienie planu i spec §6a). Powód: A ma obciążenie zależne od epoki (mediana A − B: 2017 −0,28, 2024 +0,62 m — wartości z chwili decyzji; po ocenie w Task 8 bias 2017 −0,35, 2024 +0,59 m) i pogarszał krzywą C. Gdy są A i B, `h_t` = B, a `h_t_a`, `h_t_b`, `h_diff_ab` zostają jako diagnostyka. Koszt pomyłki: A niewykorzystane w dniach z B; zmiana jedną stałą (`levels.PRECEDENCE`).
- **P4-R9** Bramka `h_sigma` < 0,3 m (kryterium M3) dla wariantu A. Koszt: mniej scen A (bez niej 54 sceny z rozrzutem do 0,73 m).
- **P4-R10** Testy backendu na prawdziwych danych (hash wersji modelu, pole strefy bezpiecznej) przepięte na nowy stan danych po P4-R8: przypięte wartości śledzą dane, a dane zmieniły się zasadnie. Koszt: brak.
- **P4-R11** Krzywa powierzchnia → rzędna (wariant C) dopasowana tylko na R i B; A wyłączone z dopasowania (LOO 0,466 m bez A wobec 0,508 m z A). C nie dziedziczy obciążenia A. Koszt: brak.
- **P4-R12** Bez korekty obciążenia A per epoka: korekta „pod B” byłaby nową, niezrecenzowaną metodą. Obciążenie raportujemy. Koszt: ok. 37 poziomów A w lukach B (głównie 2017) prawdopodobnie ok. 0,3 m za nisko.

**Mapa KŻ: OCR, poziomice, żwirownia**
- **P4-R13** Fikstura testu OCR to prawdziwy wycinek mapy z co najmniej 3 odczytanymi rzędnymi (albo syntetyczny w stylu mapy, gdyby licencja nie pozwalała). Koszt: brak.
- **P4-R14** Kotwica rzędnej = najbliższa izolowana kropka z dowolnej strony (promień ∝ wysokość tekstu, jedna kropka na jedną liczbę, niejednoznaczne odrzucane, strona zapisana w `anchor_side`): reguła „kropka po lewej” z briefu była za ostra dla prawdziwej mapy (tylko 94 przyjęte punkty). Koszt: część fałszywych kotwic, łapanych przez kontrolę.
- **P4-R15** Jeden dodatkowy przebieg OCR (powiększenie 2×), zostawiony, bo pomógł. Koszt: czas działania.
- **P4-R16** Cel kontroli ręcznej = min(200, liczba punktów): mapa ma mniej niż 200 rozpoznanych rzędnych (ostatecznie 149, wszystkie ocenione). Koszt: słabsze oszacowanie błędu OCR niż wymaga brief (próba < 200).
- **P4-R17** Wiersze kontroli przypisywane do punktów po kotwicy (≤ 3 px) i odczycie, nie po numerze `id`: ponowny OCR zmienia numerację, a 20 minut pracy autora musi przetrwać zmiany kodu. Koszt: brak.
- **P4-R18** Rzędna poziomicy z sąsiedniego wypełnienia (biały pas 192,5–195,0 m, błękit głębiej, ląd powyżej), bo mapa rysuje wszystkie poziomice jednym kolorem (brief zakładał dwa). Koszt: niska kompletność 192,5 m.
- **P4-R19** Żwirownia = obrys „REJON EKSPLOATACJI KRUSZYWA (2023)” w jeziorze (zagrożenie dla żeglugi, warstwa `/api/gravel`); wyrobisko na lądzie pominięte. Koszt: brak.
- **P4-R20** Poziomice KŻ to próbka „najpierw precyzja” (49 linii 195,0 m zamiast fałszywych 173): porównanie poziomic raportuje pokrycie (km porównane / km poziomicy modelu) i jest orientacyjne. Koszt: słabszy dowód z K3.
- **P4-R30** Dwa punkty z ewidentnie złą kotwicą (id QC 107: przecinek „.195,1”; id QC 98: kropka napisu „193,6 bet.”) wykluczone jawną listą `config.yaml: kz.spot_position_reject` z powodem przy każdym wpisie; plik ocen autora zostaje nietknięty. Powód: kontrola ręczna ocenia rzędną, nie przesuwa kropki. Koszt: 2 punkty mniej (autor poinformowany).

**Wariant D**
- **P4-R21** D ważny tylko poniżej sufitu powierzchni KŻ (`h_max_valid`); dopasowania nasycone (poziomica „przyklejona” do górnej granicy powierzchni) nie trafiają do `scenes.json` ani do metryk głównych: nasycone D niczego nie kontroluje. Koszt: D kontroluje tylko sceny o niskim poziomie.
- **P4-R22** Dziedzina D = sceny z `h_t` < `h_max_valid` (194,95 m); zbadano też dolną granicę średniej odległości brzeg–poziomica (ok. 115 m) — to ogon rozkładu, nie błąd. Koszt: D kontroluje 107 z 218 scen.
- **P4-R23** Usunięty filtr odległości (≤ 150 m) z ważności D: nie rozróżniał dobrych i złych dopasowań, a odrzucał właśnie niezgodne z `h_t` (zawyżał wynik). Populacja zapisana jawnie (`population`). Koszt: niższa, ale uczciwa zgodność.
- **P4-R31** *(cofnięte przez P4-R32)* TIN wariantu D tylko z punktów ≥ 192,5 m (zastrzeżenie „orientacyjne” samej mapy), wybrane po analizie ablacyjnej. Okazało się, że kontroler źle odczytał ablację: filtr pogorszył zgodność do 13,8 %.
- **P4-R32** Cofnięcie P4-R31: D liczony na pełnym zbiorze punktów po kontroli (145; zgodność w ±0,2 m 27,1 %); ablacja zostaje jako analiza czułości (±0,3–0,6 m zależnie od zbioru punktów); D to tylko zgrubna kontrola. Powód: pominięcie wyłącznie punktów dopuszczonych przez kontrolę ręczną byłoby arbitralne. Koszt: słabszy wynik główny D, ale uczciwy.

**Ocena dokładności i wybór modelu**
- **P4-R24** Ocena dna vs NMT pomija wodę w NMT: komórki ≤ powierzchnia wody arkusza (dominanta histogramu) + 0,1 m, piksele płaskie (odchylenie < 0,03 m) i żwirownię. Powód: arkusze niosą płaską wodę na różnych rzędnych (do ok. 1 m różnicy), a jeden poziom na epokę liczył wodę jako ląd (37–86 % pikseli). Koszt: mniejsze n; stałe niewalidowane.
- **P4-R25** Udział istotnej zmiany dna liczony względem **akwenu wspólnego** (ograniczenie globalne planu wiąże bardziej niż brief): 1,5 % < 5 %, więc aplikacja serwuje `all`. Stary mianownik (piksele z `z` w obu modelach, 44,4 %) zostaje jako `share_significant_overlap`. Koszt pomyłki: aplikacja nie przechodzi na model po powodzi, gdyby zmiana jednak była istotna.
- **P4-R26** NMT 2024 (06.09.2024) jest sprzed powodzi, więc porównujemy go z `pre_flood` i `all`; `post_flood` vs 2024 tylko informacyjnie. Koszt: brak.
- **P4-R34** Aplikacja nadal serwuje `all` (bez zmiany reguły wyboru). Powód: przewaga `pre_flood` względem NMT (+0,20 vs +1,16 m) to efekt populacji pikseli — na pikselach wspólnych `all` daje bias +0,15 m, RMSE 1,03 m, a rastry różnią się medianą 0,00 m; cała różnica to pierścień 196–198 m, który ma tylko `all` (bias +1,43 m względem NMT). Zmiana na `pre_flood` nie poprawiłaby dna poniżej 196 m, a usunęłaby informację z powodzi 2024 i piętrzenia 2025. Koszt: pierścień ≥ 196 m pokazywany z obciążeniem ok. +1,4 m (płycej niż w rzeczywistości, kierunek ostrożny); maskowanie/oznaczanie go — pytanie otwarte do autora (raport §8 pkt 12).
- **P4-R28** Brakujący zbiorczy `share_in_bounds` w `bottom_vs_nmt.json` uzupełniony w rundzie zadania 10 (API go potrzebowało). Koszt: małe przekroczenie zakresu zadania.

**Uruchomienie (Docker)**
- **P4-R29** Cache poziomu na żywo w osobnym wolumenie poza `data/processed` (`MIELIZNA_CURRENT_DIR`): wolumen zagnieżdżony w montowaniu tylko do odczytu nie działał, gdy `data/processed/current` nie istniało. Koszt: po aktualizacji ze starszego układu jednorazowo `docker compose down -v`.

**Odłożone ustalenia planu 4** (bez poprawki; opis w raporcie §8):
- model `all` ok. +1,2 m powyżej NMT na lądzie (2022: −0,21 m przy n = 65, więc nie „stała”), skupione w pierścieniu ≥ 196 m (+1,43 m; poniżej 196 m ok. 0, P4-R34), przedziały przeufne; hipotezy: maska lądu w zarośniętych marginesach, osiągalność wody vs wysokość, nieznany udział przesunięcia RZGW ↔ EVRF2007;
- epoki LiDAR mieszają naloty (wody arkuszy 2011: 194,43–194,69 m, 2024: 194,89 vs 195,95 m); wariant A 0,48 m za nisko w dniu własnego nalotu 2024;
- łańcuch `make levels` ma nieaktualne daty (`config.yaml`, `labels.gpkg`) i może wymusić retrening RF; kroki oceny zależą tylko od kodu;
- stałe oceny (dominanta 2 %, płaskość 0,03 m, zapas 0,1 m) niewalidowane;
- drobne: kolumna bajtów w inwentarzu, brak `try` per plik przy pobieraniu, niespójna precyzja pikseli GCP, brak ostrzeżenia o niedopasowanych wpisach `spot_position_reject`, import wewnątrz `load_qc_spots`, `uv run` przepisuje `backend/uv.lock`.

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
