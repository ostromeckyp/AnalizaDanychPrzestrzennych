# M7 — LiDAR i mapa KŻ (SZKIC, w trakcie)

Po ludzku: chmury punktów LiDAR z GUGiK są jak „zdjęcia” jeziora zrobione laserem w konkretny dzień. Skoro woda odbija laser, to mediana wysokości punktów wody mówi, jaki był poziom jeziora w dniu nalotu. To nasz najlepszy pomiar poziomu (wariant A) — o ile znamy datę i układ wysokości.

## 1. Epoki LiDAR (`06b_lidar_levels.py` → `data/processed/lidar/epochs.csv`)

| epoka | data nalotu | rozstęp [dni] | h wody [m] | układ | poprawka → EVRF2007 [m] | h w EVRF2007 [m] | IQR [m] | punkty wody |
|---|---|---|---|---|---|---|---|---|
| 2011 | 2011-03-20 (tylko 1 z 4 arkuszy ma datę) | 1 | 194,44 | KRON86 | +0,199 | 194,64 | 0,03 | 1 714 415 |
| 2017 | 2017-02-27 i 2017-03-25 | 26 | 193,39 | KRON86 | +0,199 | 193,59 | 0,04 | 6 146 178 |
| 2022 | 2022-03-23 | 0 | 195,69 | EVRF2007 | 0 | 195,69 | 0,03 | 85 208 |
| 2024 | 2024-09-06 | 0 | 194,89 | EVRF2007 | 0 | 194,89 | 0,04 | 6 422 522 |

Co z tego wynika i na co uważać:
- **Klasa wody to 9** (ASPRS), nie 8 jak w briefie; zdecydowały dane (kolumna `water_class`).
- **Czas GPS:** arkusze 2011 (3 z 4) mają „GPS week time” — nie da się z nich odczytać daty, więc nie zgadujemy (data 2011 pochodzi z jednego arkusza; poziomy ze wszystkich arkuszy zgadzają się co do 1 cm, poza małą próbką 1 894 punktów: 194,68 m).
- **2017 ma dwa dni nalotu** nad wodą (27.02 i 25.03), rozstęp 26 dni > progu 14 dni. Poziomy wszystkich arkuszy są zgodne (193,37–193,40 m), ale epoka nie ma jednej daty — do dalszej decyzji.
- **Poprawka układu** pochodzi z siatek quasi-geoidy GUGiK (`pl_gugik_geoid2011-PL-KRON86-NH` i `pl_gugik_geoid2021-PL-EVRF2007-NH`, `mielizna/datum.py`), nie ze stałej; zmienia się o ok. 1 cm wzdłuż jeziora.
- Poziomy 2011 i 2017 w KRON86 przed porównaniem z 2022 i 2024 trzeba sprowadzić do EVRF2007 (kolumna `h_water_evrf`).

## 2. Wariant A per scena (`06b_lidar_levels.py --scenes-only` → `data/processed/levels_a.csv`, `levels_a_detail.csv`)

Po ludzku: brzeg widoczny na zdjęciu satelitarnym leży dokładnie na poziomie wody z dnia zdjęcia. Skoro NMT z LiDAR-u mówi, ile metrów n.p.m. ma ziemia w każdym punkcie brzegu, to mediana tych wysokości jest poziomem wody tej sceny.

Jak liczone: linia brzegowa sceny co 5 m, bez bloków „valid” (szachownica 500 m), bez bufora 150 m wokół zapory (OSM, warstwa `dam` w `lake.gpkg`; dopisane do `03_fetch_osm.py`) i bez pikseli bez danych NMT; epoka = ta z wodą co najmniej 0,2 m niższą niż szacunek sceny z B/R/C, najbliższa w czasie (remis: mniejszy rozstęp dat); do mediany tylko punkty > poziom wody nalotu + 0,10 m; bramki: n ≥ 50, ≥ 3 z 8 sektorów wokół środka jeziora, h_sigma < 0,3 m (kryterium M3). Układ: NMT z KRON86 (2011, 2017) dostaje stałą +0,199 m z `epochs.csv` (jedna poprawka w środku jeziora; zmienność ~1 cm), poziom wody nalotu to `h_water_evrf`; wynik w PL-EVRF2007-NH.

Pierwszeństwo (spec §7): **R > B > A > C**. Wariant A uzupełnia luki B i nie nadpisuje B ani R. Gdy A i B istnieją tego samego dnia, `h_t` = B, a w `scenes.json` zostają `h_t_a`, `h_t_b` i `h_diff_ab = h_t_a − h_t_b` (diagnostyka). Dla dnia tylko z A: `h_t` = `h_t_a`, a `h_t_b` i `h_diff_ab` są puste.

Bramka `h_sigma` < 0,3 m to kryterium M3 (`MAX_SIGMA` w `06b_lidar_levels.py`, opis w jego docstringu): bez niej 54 sceny z rozrzutem brzegu do 0,73 m dostałyby „poziom" A.

Wyniki (221 scen):
- **A ma 129 scen** (2017: 90, 2022: 13, 2024: 26). Odpadło 92: 56 przez h_sigma ≥ 0,3 m, 17 przez pokrycie < 3 sektorów (2 przez oba), 20 bez epoki z niższą wodą (szacunek sceny < ok. 193,8 m, najniższa epoka to 2017: 193,59 m), 1 bez szacunku (qc_excluded).
- **Realnie uzupełnia luki w 37 scenach** (2017: 36, 2022: 1) z 63 scen bez B/R; w `scenes.json`: B 155, A 37, C 26, R 2, qc_excluded 1. h_sigma tych 37: mediana 0,22, maks. 0,30 m. Pozostałe 92 sceny z A mają B, więc A jest tylko diagnostyką.
- **Krzywa powierzchnia–rzędna dopasowana tylko na R i B (A wyłączone z dopasowania, R11):** błąd LOO 0,466 m, LOYO 0,488 m (n_obs=131; Otsu). Dla porównania, gdy A było w dopasowaniu: LOO 0,508 m, LOYO 0,583 m (n_obs=164). A nadal uzupełnia luki w `scenes.json`, ale nie wpływa na wariant C.
- **Obciążenie zależne od epoki (A − B, 92 dni z oboma):** mediana −0,16 m, std 0,57, |różnica| > 0,2 m w 70 z 92.

| epoka NMT | n | mediana A−B [m] | std | min | maks |
|---|---|---|---|---|---|
| 2017 | 54 | −0,28 | 0,48 | −1,45 | +0,58 |
| 2022 | 12 | −0,26 | 0,26 | −0,95 | −0,04 |
| 2024 | 26 | +0,62 | 0,17 | +0,02 | +0,76 |

  Znak różnicy zależy od epoki (2024 powyżej B, 2017 i 2022 poniżej), więc to raczej obciążenie metody/pokrycia NMT (2017 i 2022: tylko wschodni nasyp, ≥ 3 z 8 sektorów; stromy profil; położenie linii brzegowej ±10 m) niż jedno stałe przesunięcie układu RZGW. **Uwaga (R12): poziomy A wypełniające luki B (głównie epoka 2017, 36 z 37 scen) są prawdopodobnie ok. 0,3 m za niskie względem B (mediana A−B dla 2017: −0,28 m); nie robimy korekty epokowej.** Wniosek do Task 8: A traktować jako uzupełnienie z niepewnością większą niż deklarowane `h_sigma`.
- **Pokrycie NMT:** epoki 2017 i 2022 mają NMT tylko dla 2 arkuszy; 7 (2017) i 10 (2022) scen odpadło na sektorach.
- **M3 (2024-09-06, cel 194,70 ± 0,3):** h_t = B = 194,61 m (A = 194,41 m, epoka 2017).

## 3. Mapa KŻ — georeferencja (`09_kz_digitize.py georef` → `data/processed/kz/kz_meta.json`, `qc_georef.png`)

Po ludzku: mapa KŻ to skan z siatką linii co pół minuty kątowej (WGS84, stopnie i minuty, opis na krawędziach: 17°10′–17°18′, 50°28′–50°26′). Przecięcia tych linii mają znane współrzędne, więc przypinamy do nich skan; kilka przecięć zostawiamy „na boku” i sprawdzamy na nich, czy dopasowanie jest uczciwe.

- Obraz: największy obraz strony PDF, 9867 × 4791 px; linie siatki narysowane cyfrowo (poziomo co 560 px, pionowo co ok. 873,7 px), położenia mierzone medianą po wielu odcinkach linii, nie „na oko”.
- GCP (`data/reference/kz_gcp.csv`): 19 `fit` i 10 `check`, rozłożone po całej mapie poza legendą (lewy dolny róg).
- RMSE (m): afiniczna fit 0,93 / check 0,77; wielomian 2. st. fit 0,12 / check 0,13. Wybrany: **poly2** (mniejszy RMSE na punktach wstrzymanych). Wielomian jest potrzebny, bo siatka stopni jest „prostokątna”, a EPSG:2180 to odwzorowanie Gaussa-Krügera.
- **Werdykt: `good`** (próg ≤ 5 m). Uwaga: RMSE mierzy zgodność skanu z jego siatką, nie błąd rysowania treści mapy; kontrolą niezależną jest zapora.
- Zapora (kontrola zewnętrzna, `dam_offset_m`): warstwa `dam` w `lake.gpkg` to 5 zamkniętych pierścieni (obrysy obszarów zapory z OSM), nie linie korony, więc jako odniesienie bierzemy tylko krawędź od strony wody: części brzegów pierścieni w 50 m od obrysu jeziora (`kz.lake_facing_edges`). Wzdłuż 281 normalnych (co 25 m) środek pasa zapory na mapie (szablon szerokości 46 m, `kz.band_centre`) porównano z tą krawędzią; znak dodatni = dalej od jeziora. Wynik: **mediana −2,0 m, rozrzut 1,4826·MAD = 11,9 m, n = 281**. Rozrzut > 10 m, więc `dam_offset_note: "qualitative"`; liczby nie pozwalają na twierdzenie o dokładności lepszej niż rzędu kilkunastu metrów. (Wcześniejsze wersje tej kontroli — „najciemniejszy piksel” i pełne pierścienie — są zastąpione.)
- `rmse_scope: "graticule-internal"`: punkty `check` leżą na tych samych liniach siatki co `fit`, więc RMSE 0,13 m mierzy spójność skanu z siatką, nie błąd treści mapy.

## 4. Mapa KŻ — rzędne punktowe z OCR (`09_kz_digitize.py spots` → `kz_spot_ocr.gpkg`, `kz_spot_ocr_stats.json`; narzędzie `make kz-qc-ui`)

Po ludzku: na mapie KŻ są setki małych liczb („188,5” = dno na rzędnej 188,5 m n.p.m.), każda z kropką, która pokazuje punkt pomiaru. Czytamy je programem `tesseract` (kafle 1200 px), georeferujemy kropkę tą samą transformacją co resztę mapy i sprawdzamy kolor: niebieskie liczby to woda (< 195,0 m), czarne to ląd i wyspy (≥ 195,0 m). OCR myli cyfry, więc nic stąd nie wchodzi do metryk bez ręcznej kontroli próby.

- Przebieg (po poprawkach R14/R15 i rundzie 2): OCR w dwóch przebiegach (kafle 1× i 2×, scalane po IoU ramek) → 5773 słowa → **331** pasuje do wzorca `.?ddd,d` w zakresie 185–200 m → **162** odrzuconych (brak kropki w promieniu 1,5 × wysokość ramki, kropka niejednoznaczna albo zajęta przez bliższą liczbę) → **20** poza obrysem jeziora + 100 m (legenda i opisy, odcięte przez `kz.in_lake_zone`, wyspy zostają) → **149 punktów przyjętych** (142 niebieskie, 7 czarnych).
- Kotwica = najbliższa izolowana kropka z dowolnej strony: lewa 125, pod liczbą 11, po prawej 9, nad liczbą 4 (`anchor_side` w gpkg). Reguły: promień 1,5 × wysokość ramki; dwie kropki o stosunku odległości < 1,3 = odrzut; jedna kropka kotwiczy tylko jedną liczbę (bliższa wygrywa, przy remisie odpadają obie; kropki to składowe całego obrazu, więc ta sama kropka ma to samo `id` w oknach różnych liczb); kropka ma 2 px czystego tła, kolor niebieski/czarny (czerwone i różowe krzyżyki komunikatów odpadają), nie leży w ramce innego słowa z cyfrą, a ogonek własnego przecinka wystający pod ramkę (do 0,3 × wysokość) nie jest kropką.
- **`color_ok` = 96,6 %**, udział „podejrzanych” (kolor niezgodny albo pewność < 80) 28 %. Pewność OCR: mediana 89,7; kwartyle 78,9 / 92,0; 41 punktów z pewnością < 80.
- Historia liczby przyjętych: kropka tylko z lewej 94 → dowolna strona 123 → plus przebieg 2× 200 → po usunięciu ogonków przecinków, podwójnych kotwic, legendy i krzyżyków 149. Wcześniejsze „200” zawierało fałszywe kotwice (ogonki przecinków, legenda), więc nie było realną liczbą punktów.
- Znane fałszywe kotwice: kilka etykiet komunikatów („193,9 bet.”, czarne, podkreślone) dostaje kropkę z kropki po „bet”; mają kolor niezgodny z regułą (czarne < 195,0), więc trafiają do warstwy „podejrzane” w kontroli; `rejected` je wyłapie.
- Zapis z kropką dziesiętną („194.3”) w tekście OCR to 10 słów; na mapie to błędnie odczytane przecinki albo legenda, więc **nie są akceptowane**.
- Kontrola ręczna: `make kz-qc-ui` → http://localhost:8765/kz, cel = min(200, liczba punktów) = 149 (autor ocenia wszystkie 149); wynik `data/reference/kz_spot_qc.csv` (kolumny `id, ocr_z, qc, z_qc, px, py`; wiersze są przypisywane do punktów po kotwicy ≤ 3 px i tej samej rzędnej, `kz.match_qc`, bo numery `id` zmieniają się po ponownym OCR). Błąd OCR = `kz.ocr_error_rate` z wagami warstw (udział warstwy w populacji ÷ udział w próbie).

## 5. Mapa KŻ — poziomice 192,5 i 195,0 m oraz obrys żwirowni (`09_kz_digitize.py contours | gravel` → `kz_contours.gpkg`, `qc_contours.png`, `data/reference/zwirownia.gpkg`)

Po ludzku: poziomice na mapie mają wszystkie ten sam granatowy kolor (mierzone: rdzeń ok. RGB 15,30,140, 2–3 px; cienkie i wypłowiałe fragmenty jaśniejsze), więc po samym kolorze nie odróżnimy 192,5 od 195,0 ani od 190,0. Odróżnia je tło: pas wody między 192,5 a 195,0 m jest biały, głębiej jest błękit, a brzeg 195,0 graniczy z lądem. Najpierw maska koloru linii (`kz.color_mask`), potem poziom z sąsiednich wypełnień (`kz.contour_level_masks`, promień 8 px, ziarna rosną po masce granatu do 10 px, żeby zasklepić przerwy), na końcu szkielet → linie (`kz.mask_to_lines`: ucięcie ogonków < 12 px, podział w rozwidleniach, odrzucenie < 80 px, więc linie przerywane „orientacyjne” i litery odpadają) → EPSG:2180 tą samą transformacją poly2.

- Po poprawce (runda 1 recenzji): maska linii wymaga też „niebieskości” (b − r ≥ 40), więc szara siatka i szare drogi nie są poziomicami. Linia 195,0 jest ostatecznie sprawdzana **większością próbek wzdłuż linii** (`kz.line_side_votes`): co 6 px biorę piksele 8 px po obu stronach, klasa „woda” (biel albo błękit) kontra „ląd”; zostaje, gdy ≥ 50 % ważnych próbek ma jedną stronę wodną, a drugą lądową. Odpadają też linie osiowe (siatka), niemal proste (cięciwa/długość ≥ 0,985, drogi i wały) i zewnętrzna linia z pary równoległych (≤ 12 m, > 50 % długości): zostaje ta bliżej obrysu jeziora, bo niższa poziomica przy wodzie to 195,0. Jeden wpis w `contour_drop` (wzgórek 198,7 m, z uzasadnieniem), wskazywany środkiem i długością, nie numerem.
- Wynik (`kz_contours_stats.json`): **192,5 m: 19 linii, 2,40 km; 195,0 m: 49 linii, 7,01 km**. Pierwsza wersja (26 + 173 linie, 3,5 + 25,7 km) zawierała głównie fałszywe linie (siatka, drogi, poziomice > 195, ciemna zieleń), więc nie jest podstawą żadnych liczb.
- **Granice precyzji 195,0 m:** na mapie poziomice nie różnią się kolorem, a wypełnienie lądu przy brzegu bywa niemal identyczne po obu stronach (jasna zieleń „zieleń niska” = dno z roślinnością, odcień różni się o kilka jednostek RGB). Takich odcinków (głównie południe, wschód i zachód brzegu) nie rozstrzygamy, więc **większość brzegu 195,0 m jest pominięta** (precyzja kosztem kompletności: zostają brzegi wysp i półwyspów z wyraźną wodą po jednej stronie). Wśród zachowanych linii są wiązki 2–3 równoległych poziomic; wybór „bliższej wody” jest regułą, nie pomiarem, więc pojedyncze linie mogą być poziomicą 195,5–196 m. Nie używać 195,0 m do metryk bez ręcznego przeglądu; 192,5 m to próbka tam, gdzie z jednej strony jest biały pas.
- Żwirownia: na mapie to różowy prostokąt „REJON EKSPLOATACJI KRUSZYWA (2023)”, z przekątną po południowo-wschodniej stronie. 5 wierzchołków wskazanych ręcznie (`data/reference/zwirownia_vertices.csv`, dokładność kilka–kilkanaście px = 5–15 m), lewa krawędź nie jest narysowana, więc zamykamy ją prostą. **Pole 176 ha, 99 % w obrysie jeziora OSM.** Atrybuty `source`, `licence_ref`.

## 6. Wariant D — kontrola poziomów wody z powierzchni KŻ (`10_kz_compare.py variant-d` → `kz/levels_d.csv`, `kz/kz_surface.tif`, `eval/variant_d.json`)

Po ludzku: z rzędnych punktowych i poziomic mapy KŻ budujemy powierzchnię dna (siatka trójkątów, interpolacja liniowa na siatce 10 m). Potem dla każdej sceny pytamy: przy jakiej rzędnej wody poziomica tej powierzchni najlepiej pokrywa się z linią brzegową widoczną na zdjęciu? Odpowiedź (`h_t_d`) jest **kontrolą** `h_t` (innym źródłem niż komunikaty, LiDAR i krzywa), nigdy jego źródłem. `scenes.json` dostaje `h_t_d` i `h_diff_d = h_t_d − h_t` dopiero z `06_water_levels.py` (czyta `kz/levels_d.csv`).

- Wejście: punkty KŻ — **107 z 149** (wszystkie `ocr_ok`: kolor zgodny z rzędną i pewność OCR ≥ 80; kontroli ręcznej `kz_spot_qc.csv` jeszcze nie było, `kz.load_qc_spots` po jej pojawieniu użyje ocen `ok`/`corrected`), poziomice 192,5 (19 linii, 2,40 km) i 195,0 m (49 linii, 7,01 km; próbka precyzyjna, nie komplet brzegu), siatka poziomów 192,5–198,0 co 0,05 m, punkty brzegu co 10 m, minimum 50 punktów z powierzchnią na scenę. Powierzchnia jest NaN poza otoczką wypukłą danych i w żwirowni; brzeg w żwirowni jest pomijany.
- **Pokrycie powierzchni: 79,2 % obszaru jeziora** ma wartość.
- Dopasowano 218 scen (pominięto 3 odrzucone przez QC; żadna nie padła na minimum punktów). Mediana średniej odległości brzeg–poziomica: 122 m (10./90. percentyl 115/147 m), czyli dopasowanie jest luźne.
- **Zakres ważności:** `h_max_valid` = najwyższa rzędna, do której długość poziomicy powierzchni ≥ 50 % jej długości na 194,0 m (`variant_d.h_max_valid`). Wynik: **194,95 m** (poziomica 195,0 ma 6 km wobec 20,6 km na 194,0; 195,25 już 0,7 km). Fit jest ważny (`d_valid`, kolumna w `levels_d.csv`) gdy: poziom odniesienia sceny `h_t` < `h_max_valid` (dziedzina metody: powierzchnia opisuje tylko niskie poziomy; `h_t` bierzemy ze `scenes.json` z chwili uruchomienia), h fitu < `h_max_valid` − 0,05 m i nie leży na brzegu siatki poziomów. Średnia odległość brzeg–poziomica (`dist_m`) jest tylko kolumną informacyjną: wcześniejszy próg 150 m usunięto, bo nie rozróżnia fitów (poniżej) i zawyżał wynik, odrzucając fity niezgodne z `h_t`. W `scenes.json` `h_t_d`/`h_diff_d` trafiają wyłącznie dla fitów ważnych (inaczej null). `variant_d.json`: `population` = „h_t < h_max_valid and d_valid”, `n_fitted` 218, **`n_valid` 107** (= wszystkie sceny w dziedzinie), `n_out_of_domain` 111 (`h_t` ≥ 194,95 m).
- **Zdolność rozdzielcza fitu jest rzędu tolerancji 0,2 m:** profil średniej odległości po rzędnych jest płaski (2017-04-01: 120,3 / 118,2 / 121,3 m dla 194,25 / 194,50 / 194,75 m), więc różnica 0,2–0,3 m w `h` zmienia średnią o kilka metrów przy rozrzucie rzędu 100 m. D nie potrafi więc poświadczyć `h_t` dokładniej niż mniej więcej ±0,2–0,3 m, a „zgodność ≤ 0,2 m” jest zarazem jego granicą rozdzielczości.
- **Zgodność z `h_t` (sceny w dziedzinie, fity ważne): n = 107, udział |D − h_t| ≤ 0,2 m = 46,7 %, mediana |D − h_t| = 0,25 m, mediana D − h_t = +0,04 m.** Wszystkie 218 fitów bez filtrów: 22,9 % i 0,68 m (klucz `all_fits_unfiltered`).

| metoda `h_t` | n | udział ≤ 0,2 m | mediana abs. [m] | mediana D − h_t [m] |
|---|---|---|---|---|
| A | 36 | 91,7 % | 0,06 | +0,05 |
| B | 61 | 26,2 % | 0,36 | −0,09 |
| R | 0 | n/d | n/d | n/d |
| C | 10 | 10,0 % | 0,85 | +0,85 |

  Przed powodzią (do 31.08.2024, n = 76): 52,6 %, mediana abs. 0,14 m. Sceny A zgadzają się najlepiej, B gorzej, C (poziom z krzywej, sigma ok. 0,5 m) słabo. Poprzednia wersja z filtrem odległości (n = 94) dawała 50,0 % i 0,20 m: różnicę robiło 13 fitów w dziedzinie, które odpadały wyłącznie na `dist_m`, w tym wyraźne niezgodności (np. 2017-10-20 sceny A: D 192,65 m wobec `h_t` 194,30 m; 2026-06-20 sceny B: 193,05 wobec 194,87 m).
- **Dlaczego średnia odległość brzeg–poziomica nigdy nie schodzi poniżej ok. 115 m (mediana 122 m)? Zbadane: to nie błąd jednostek ani odległości, tylko ogon rozkładu.** Dla sceny A z 2017-04-01 (h_t_d = 194,45 m, najlepszy typ fitu): rozkład odległości punktów brzegu od poziomicy 194,45 m (pct. 5/25/50/75/95/100) = 6 / 26 / 70 / 155 / 385 / 901 m, a 28 % punktów leży bliżej niż 30 m; druga scena A (2017-07-12) daje 6 / 30 / 76 / 176 / 407 / 897 m. Czyli w dużej części brzegu poziomica i brzeg pokrywają się co do kilku–kilkudziesięciu metrów (zgodnie z dokładnością georeferencji i linii brzegowej), ale średnia jest windowana przez odcinki, gdzie powierzchnia KŻ nie opisuje brzegu: rzędna powierzchni na punktach brzegu ma pct. 5/25/50/75/95 = 190,3 / 193,4 / 194,4 / 195,0 / 195,0 m (a powinna być ≈ h), bo trójkąty TIN przy krawędzi otoczki łączą odległe punkty, a odcinki brzegu bez poziomic KŻ w pobliżu mają najbliższy wierzchołek setki metrów dalej. Średnia (wg specyfikacji) jest więc wskaźnikiem pokrycia danych, nie jakości samego fitu, i nie rozróżnia dobrych fitów od złych (dlatego nie jest kryterium ważności). Medianę zamiast średniej pozostawiam jako możliwą zmianę metody po kontroli ręcznej punktów (nie strojone tu).
- **Wniosek:** w swojej dziedzinie (`h_t` < 194,95 m, 107 scen) D zgadza się z `h_t` w ±0,2 m dla 47 % scen (sceny A: 92 %, B: 26 %, C: 10 %). Potwierdza niskie poziomy typu A, a dla B i C jest zbyt zgrubny albo ich poziomy są niepewne; nie potrafimy tego rozstrzygnąć. Dla wysokiej wody (poza dziedziną, 111 scen) nic nie kontroluje. Nie jest podstawą żadnej korekty `h_t`. Stan wejść: 107 punktów bez kontroli ręcznej i część poziomicy 195,0. Po kontroli: `uv run python 10_kz_compare.py variant-d` i `06_water_levels.py`.
- **Po kontroli ręcznej (149 punktów ocenionych: 138 `ok`, 9 `corrected`, 2 `rejected`) i wykluczeniu 2 punktów o błędnej kotwicy: wariant D na punktach ≥ 192,5 m.** Trzy zmiany wejścia, każda zmierzona (ablacja na tych samych 218 liniach brzegowych, `h_t` tylko do wyznaczenia dziedziny; wiersze 1-4 liczone przed filtrem ≥ 192,5 m i przed wykluczeniem kotwic):

  | wejście TIN (poziomice 192,5 i 195,0 m zawsze) | punkty | n_valid | ±0,2 m | mediana abs. | mediana D − h_t | metoda A: ±0,2 m / mediana D − h_t |
  |---|---|---|---|---|---|---|
  | 1. bez kontroli (filtr koloru i pewności) | 107 | 107 | 46,7 % | 0,25 m | +0,04 m | 91,7 % / +0,05 m |
  | 2. pełna kontrola ręczna | 147 | 107 | 27,1 % | 0,28 m | −0,19 m | 58,3 % / −0,19 m |
  | 3. pełna kontrola bez 23 nowo dopuszczonych punktów < 192,5 m | 124 | 107 | 48,6 % | 0,21 m | +0,12 m | 80,6 % / +0,13 m |
  | 4. pełna kontrola bez 18 nowo dopuszczonych punktów ≥ 192,5 m | 129 | 107 | 12,1 % | 0,45 m | −0,42 m | 0 % / −0,42 m |
  | **5. obecne: punkty tylko ≥ 192,5 m (wszystkie sprawdzone), bez 2 kotwic** | 145 → 50 ≥ 192,5 m w TIN | 109 | **13,8 %** | **0,58 m** | **+0,58 m** | 2,8 % / +0,59 m |

  (Wiersze 1-4: ablacja recenzenta, skrypt `ablate.py`; wiersze 1-2 odtworzone tym samym kodem i zgodne z poprzednimi liczbami 46,7 % i 27,1 %; wiersz 5 policzony w zadaniu 9, naprawa 1.) **Wniosek z ablacji:** cały spadek z 46,7 % do 27,1 % (wiersz 2) tłumaczy 23 nowo dopuszczonych głębokich punktów < 192,5 m (po ich usunięciu: 48,6 % i mediana +0,12 m), a nie punkty ≥ 192,5 m. **Filtr ≥ 192,5 m dla punktów wybrałem PO zobaczeniu tej ablacji.** Uzasadnia go zastrzeżenie samej mapy KŻ (blok UWAGA: dno poniżej 192,5 m odwzorowano orientacyjnie), a nie dopasowanie do wyniku; stała `variant_d.MIN_SPOT_Z`. **Uczciwe zastrzeżenie: filtr stosowany do WSZYSTKICH punktów < 192,5 m (także tych, które były już bez kontroli) wcale nie poprawia zgodności (wiersz 5: 13,8 %, mediana +0,58 m).** Przy tym wejściu TIN poniżej 192,5 m nie ma żadnych rzędnych poza poziomicą 192,5 m (pokrycie jeziora 67,0 % wobec 81,9 %, mediana średniej odległości brzeg-poziomica 165 m wobec 103 m), więc dno głębsze jest wyciągane z tej poziomicy i poziomice D lądują o ok. 0,6 m za wysoko. **Kluczowe zastrzeżenie: wynik D zmienia się o ±0,3-0,6 m w zależności od wyboru zbioru punktów (wiersze 1-5: mediana D − h_t od −0,42 do +0,58 m), czyli czułość D na dobór punktów jest większa niż rozdzielczość, której szukamy (±0,2 m).** D nie jest więc podstawą żadnej korekty `h_t` ani oceną poziomów; „większość scen ±0,2 m” nie jest spełnione w żadnym wariancie z kontrolą ręczną. Liczba punktów po kontroli i filtrach: `spots_source` w `variant_d.json` (138 `qc_ok`, 7 `qc_corrected`).
- **Kontrola ręczna nie przesuwa kotwic, a lokalizator kotwicy bywa mylony.** Wiersz QC ocenia rzędną, nie położenie punktu; szukacz kotwicy czasem trafia w przecinek lub kropkę zamiast w kropkę sondażu, więc część punktów `ok` może mieć błąd położenia rzędu dziesiątek metrów. Dwa takie przypadki wykryto i wykluczono listą `kz.spot_position_reject` w `config.yaml` (dopasowanie po kotwicy ≤ 3 px i `ocr_z`, jak `match_qc`, z powodem przy każdym wpisie): id QC 107 (kotwica na przecinku „.195,1”, prawdziwa kropka 195,1 leży ok. 47 px na lewo, na wyspie) i id QC 98 (kotwica na kropce napisu „193,6 bet.”, etykieta obiektu, nie sondaż). `data/reference/kz_spot_qc.csv` pozostaje bez zmian (oceny autora).

## 7. Ocena dokładności (`08_evaluate.py` → `data/processed/eval/{bottom_vs_nmt,levels,bottom_change,model_choice,mask}.json`, `docs/img/eval-*.png`)

Metoda: dno modelu (`z`) vs NMT uśredniony do 10 m (średnia komórek 1 m, wymóg ≥ 50 % pokrycia piksela), wyłącznie bloki „valid" (bez przecieku z wariantu A). NMT KRON86 (2011, 2017) sprowadzony do EVRF2007 (+0,199 m) raz. Poziomy modelu pochodzą głównie z układu RZGW (nieznany), więc bias zawiera też ewentualne przesunięcie RZGW↔EVRF2007; nic nie jest korygowane.

**Woda w NMT (poprawka po przeglądzie).** Arkusze NMT niosą jezioro jako płaską powierzchnię o rzędnej różnej dla arkusza i często innej niż poziom wody epoki z `epochs.csv` (np. 2024: dwa arkusze płasko na 195,95 m przy 194,89 m epoki). Jeden `h_water` na epokę zaliczał więc wodę jako ląd (37–86 % ocenianych pikseli). Teraz: dla każdego arkusza powierzchnia wody = dominanta histogramu NMT (zaokrąglenie 0,01 m; uznana, gdy ≥ 2 % komórek), komórki ≤ woda + 0,1 m pomijane, piksele 10 m o odchyleniu komórek 1 m < 0,03 m (płaskie) pomijane, żwirownia (`zwirownia.gpkg`) wyłączona; dodatkowo piksel > `h_water_evrf` epoki + 0,1 m. Powierzchnie wody arkuszy (diagnostyka):

| Epoka | arkusz | powierzchnia wody (rzędna natywna, m) |
|---|---|---|
| 2011 | M-33-59-C-b-2-3 | brak dominanty (ląd) |
| 2011 | M-33-59-C-b-2-4 | brak dominanty (ląd) |
| 2011 | M-33-59-C-b-4-1 | brak dominanty (ląd) |
| 2011 | M-33-59-C-b-4-2 | 194.69 |
| 2011 | M-33-59-C-b-4-4 | brak dominanty (ląd) |
| 2011 | M-33-59-D-a-1-3 | 194.44 |
| 2011 | M-33-59-D-a-1-4 | 194.52 |
| 2011 | M-33-59-D-a-3-1 | 194.43 |
| 2011 | M-33-59-D-a-3-2 | 194.65 |
| 2011 | M-33-59-D-a-3-3 | brak dominanty (ląd) |
| 2017 | M-33-59-D-a-1-4 | 193.38 |
| 2017 | M-33-59-D-a-3-2 | 193.39 |
| 2022 | M-33-59-D-a-1-4 | 195.66 |
| 2022 | M-33-59-D-a-3-2 | 195.72 |
| 2024 | M-33-59-C-b-2-3 | brak dominanty (ląd) |
| 2024 | M-33-59-C-b-2-4 | brak dominanty (ląd) |
| 2024 | M-33-59-C-b-4-1 | brak dominanty (ląd) |
| 2024 | M-33-59-C-b-4-2 | 194.89 |
| 2024 | M-33-59-C-b-4-4 | brak dominanty (ląd) |
| 2024 | M-33-59-D-a-1-3 | 194.88 |
| 2024 | M-33-59-D-a-1-4 | 195.95 |
| 2024 | M-33-59-D-a-3-1 | 194.89 |
| 2024 | M-33-59-D-a-3-2 | 195.96 |
| 2024 | M-33-59-D-a-3-3 | brak dominanty (ląd) |

- **Dno vs NMT: model `all` ma stałe obciążenie ok. +1,2 m (model wyżej niż NMT).** MAE 1,35 / 1,40 / 0,92 / 1,20 m, RMSE 1,53 / 1,64 / 1,15 / 1,41 m, bias +1,16 / +1,19 / −0,21 / +1,16 m (epoki 2011 / 2017 / 2022 / 2024; n = 4 154 / 1 466 / 65 / 2 792); NMT w [z_min, z_max] tylko 5,8 / 7,1 / 4,6 / 7,1 %. Razem 8 477 pikseli: bias +1,16, RMSE 1,51 m, NMT w granicach 6,4 % (blok zbiorczy `all` w `bottom_vs_nmt.json`; `pre_flood` zbiorczo po epokach 2011–2024: n = 1 781, RMSE 0,96, bias +0,20 m, w granicach 12,3 %). Rozrzut NMT na ocenianych pikselach to 0,11–0,69 m, korelacja 0,31 / 0,86 / −0,18 / 0,21. Przedziały są więc przeufne (w granicach 5–7 % zamiast oczekiwanych kilkudziesięciu).
- **`pre_flood` jest modelem właściwym dla wszystkich epok, bo NMT 2024 pochodzi z 06.09.2024, czyli sprzed powodzi z połowy września:** vs 2017: MAE 0,64, RMSE 0,82, bias +0,30 m, korelacja 0,76, w granicach 25 % (n = 700); vs 2011: RMSE 1,08, bias +0,14 (n = 834; epoka sprzed serii S-2, część różnic to realne zmiany dna); vs 2022: RMSE 1,05, bias −0,67 (n = 43, rozrzut NMT 0,09 m); vs 2024: RMSE 0,86, bias +0,31 (n = 204). `post_flood` vs 2024 jest tylko informacyjne (NMT sprzed powodzi vs model po): RMSE 1,46, bias +1,29 m.
- **Otwarte ustalenie (bez poprawki modelu):** resztkowe +1,2 m dla `all`. Hipotezy: maska lądu w zarośniętych i zalewanych marginesach brzegu (piksele 10 m mieszane woda/ląd/roślinność), a także różnica „osiągalności" wody vs wysokość terenu (woda dochodzi do piksela przy poziomie wyższym niż jego wysokość NMT). Do zbadania osobno.
- **Poziomy wody:** A vs B (n = 92 dni z obiema wartościami): MAE 0,47, RMSE 0,58, bias −0,08 m (A − B); wg epoki LiDAR: 2017 −0,35, 2022 −0,33, 2024 +0,59 m (mieszanka układu EVRF2007 vs RZGW i błędu metod; niekorygowane). Punkt kontrolny R 2025 (197,92 m, 28.04 i 01.05): B −0,13 m (n = 2), C −0,61 m (krzywa refitowana bez R, sigma LOYO 0,48 m), A brak. Punkt 12.09.2024 (194,70 m; brak sceny tego dnia, sceny 03 i 06.09): B −0,07 / −0,09, A −0,30 / −0,29, C +0,59 / +0,47 m. `h_sigma` mediana: A 0,22 (0,04–0,30), B 0,15, C 0,49, R 0,08 m; próg M3 (A < 0,3 m) spełniony.
- **Ustalenie (bez poprawki):** w dniu własnego nalotu, 2024-09-06, wariant A daje 194,41 m, a powierzchnia wody w NMT/LiDAR tego dnia to 194,88–194,89 m na większości arkuszy, czyli A jest ok. 0,48 m za niski w dniu własnego nalotu.
- **Zmiana dna po powodzi:** pre_flood vs post_flood: oba modele mają `z` na 8 438 pikselach (3,4 % akwenu wspólnego, 250 292 px obserwowanych w obu okresach); |Δz| > unc_pre + unc_post dla 3 743 px = **1,5 % akwenu wspólnego** (wg ograniczenia projektu; poniżej progu 5 %), więc `model_choice.json` = **`all`**. Dla porównania udział liczony względem pikseli z `z` w obu modelach (`share_significant_overlap`) to 44,4 %, ale to wąski pas przedziałów, a część Δz to różne zakresy poziomów obu okresów (pre 192,9–196,8 m, post 193,8–197,9 m), nie realna zmiana dna. Kryterium |Δz| > suma niepewności jest słabym dowodem, bo przedziały są przeufne (w granicach 5–7 %).
- **Maski** (`mask.json`, z `rf_metrics.json`, wg scen): RF OA 0,924, kappa 0,837, F1 wody 0,939, BA 0,923; RF z progiem 0,7 OA 0,890; Otsu OA 0,853; SCL OA 0,864.
- `make evaluate` zależy tylko od kodu oceny (wejścia mają reguły o nieaktualnych datach: `make -n` z nimi uruchamiał 01/04b/04 przed 08); po zmianie modelu: `rm data/processed/eval/model_choice.json && make evaluate`.

## 7b. Porównanie z mapą KŻ (`10_kz_compare.py points | contours | overlay | compare` → `eval/{kz_points,kz_contours,kz_compare}.json`, `docs/img/kz-overlay.png`; `make kz-compare kz-overlay`)

Po ludzku: mapa KŻ jest niezależnym źródłem dna (amatorskim, aktualizacja 23.05.2023). Zestawiamy z nią model `pre_flood` na trzy sposoby: rzędne punktowe (model w pikselu 10 m pod punktem; georeferencja „good”; RMSE kontroli 0,13 m jest wewnętrzne dla siatki współrzędnych (`rmse_scope: graticule-internal`), a rozrzut przesunięcia przy zaporze to 11,9 m (`dam_offset_spread_m`), więc dokładność położenia punktu względem terenu to rząd kilku–kilkunastu metrów, nie 0,13 m), poziomice 192,5 i 195,0 m (poziomica `z` modelu vs linie KŻ) oraz rysunek `docs/img/kz-overlay.png`. Bias = model − KŻ. Metryki główne to pasma ≥ 192,5 m; poniżej mapa KŻ jest orientacyjna. Wyniki są **orientacyjne**: KŻ to dane amatorskie, poziomice KŻ to próbka „precision-first”, a układ wysokości KŻ jest nieznany. Warunki mapy (blok „UWAGA”) są na rysunku i w `data/reference/KZ_ZRODLO_I_WARUNKI.md`.

- **Błąd OCR** (`kz.ocr_error_rate`, ważony warstwami podejrzane/pewne): **7,4 %** (9 poprawionych + 2 odrzucone ze 149 ocenionych, cała populacja; surowo 11/149 = 7,4 %). Próg roboczy ≤ 10 % spełniony, ale próba 149 < 200 wymaganych w briefie, bo tyle punktów w ogóle zaakceptował OCR.
- **Punkty:** 145 użytych (wszystkie sprawdzone ręcznie; 147 po kontroli minus 2 wykluczone kotwice z `kz.spot_position_reject`, patrz §6), 3 w żwirowni wykluczone; z modelem w pikselu pod punktem są tylko te, gdzie `pre_flood` ma `z`. Model pre_flood ma `z` w zakresie 192,94–196,67 m (nic poniżej, bo model powstaje z linii brzegowych scen, a najniższy zaobserwowany poziom wody to 192,9 m), więc pasmo < 192,5 (95 punktów KŻ) ma n = 0 i nie da się go ocenić; to fakt o modelu, nie wynik porównania.

| pasmo KŻ | punktów KŻ | n z modelem | bias [m] | MAE [m] | RMSE [m] | KŻ w [z_min, z_max] |
|---|---|---|---|---|---|---|
| [192,5; 195,0) | 41 | 31 | +0,30 | 0,60 | 0,85 | 32 % |
| [195,0; NPP = 195,91) | 3 | 1 | +0,64 | 0,64 | 0,64 | 0 % |
| ≥ NPP | 3 | 0 | n/d | n/d | n/d | n/d |
| < 192,5 (orientacyjne) | 95 | 0 | n/d | n/d | n/d | n/d |
| **łącznie ≥ 192,5 (n = 32)** | 47 | 32 | **+0,31** | **0,60** | **0,84** | **31 %** |

  NPP = 195,91 m liczone jak w backendzie (`capacity_to_level(65,69 mln m³)` z `kz_pojemnosc_rzedna.csv`). Poza pierwszym pasmem n jest za małe na wnioski (n = 1).
- **Poziomice (`kz_contours.json`, orientacyjnie):** **195,0 m:** KŻ 49 linii, 7,01 km; poziomica modelu ma w całości 19,28 km, z czego 8,84 km leży w buforze 150 m wokół linii KŻ (porównywane); odległość od linii KŻ do poziomicy modelu: średnia 36,6 m, 90. percentyl 77,8 m; średnia symetryczna (KŻ vs model w buforze) 47,2 m, Hausdorff 257,5 m (na próbkach co 10 m) (nadmiar modelu w buforze podnosi średnią symetryczną, więc bliższa prawdzie jest odległość KŻ→model). **192,5 m:** KŻ 19 linii, 2,40 km, a model **nie ma poziomicy 192,5 m** (długość 0; `z` modelu zaczyna się od 192,94 m), więc porównanie niemożliwe. Dla 195,0 m linie KŻ to próbka brzegów wysp i półwyspów; wiązki równoległych poziomic mogą być poziomicą 195,5–196 m (sekcja 5).
- **Go/no-go: `go`** (|bias| = 0,31 m < 0,5 m; próg roboczy z briefu). Sprawdzone przyczyny w `go_no_go.notes`: (1) układ wysokości: bias względem KŻ +0,313 m, przesunięcie KRON86→EVRF2007 +0,199 m, różnica +0,11 m; bias dna względem LiDAR (Task 8) wynosi +1,16 m (model `all`, wszystkie epoki) i +0,20 m (`pre_flood` zbiorczo), czyli bias KŻ (+0,31 m) jest bliższy biasowi pre_flood–LiDAR (różnica +0,11 m) niż `all`–LiDAR (różnica −0,84 m). Układ wysokości KŻ jest nieznany i nic nie jest korygowane; zgodność z `datum_offset` może być przypadkowa. (2) dno z 2023: mapa KŻ opisuje dno sprzed września 2024, model `pre_flood` sceny do 31.08.2024, więc różnica dat nie tłumaczy biasu przed powodzią, ale nie jest zerowa. (3) sposób pomiaru: mapa KŻ deklaruje pozyskanie „sposobem amatorskim” bez podanej niepewności.
- **Wnioski:** po wykluczeniu żwirowni i pasma < 192,5 bias dodatni oznacza, że rzędna dna modelu `pre_flood` jest **wyższa** niż KŻ, czyli model jest średnio o 0,31 m **płytszy** niż KŻ (RMSE 0,84 m); tylko 31 % punktów KŻ mieści się w przedziale [z_min, z_max] modelu (podobnie źle jak przy LiDAR: 12 % pre_flood). Próba jest mała (n = 32 z 145) i skoncentrowana w pasie 192,5–195,0 m; model nie obejmuje dna głębszego niż ok. 193 m, więc porównanie nie dotyczy najgłębszej części jeziora. Przedziały modelu są za wąskie względem tego błędu, tak samo jak w ocenie z LiDAR.
- Rysunek `docs/img/kz-overlay.png`: mapa KŻ półprzezroczysta pod strefami modelu przy NPP (ilustracja, parametry zanurzenie 0,5 m i zapas 0,3 m), poziomica 195,0 m modelu (ciągła) i KŻ (kropkowana), poziomica 192,5 m tylko KŻ (model jej nie ma), punkty KŻ; strefy tylko tam, gdzie model jest wodą przy NPP (maska jak w backendzie: `obs_count`, `flags`, NaN w `z_min` = zawsze woda).

## 8. Uruchomienie w Dockerze (`docker compose up --build`, `scripts/compose_smoke.sh`)

- **Co:** dwa kontenery: `backend` (python:3.12-slim, uv 0.13.6 przypięty, `uv sync --frozen --no-dev`, uvicorn :8000) i `frontend` (build `node:22` → `nginx:1.27-alpine`, :8080, proxy `/api/` do backendu, fallback SPA). Dane są montowane tylko do odczytu (`data/processed`, `data/reference`), a katalog `processed/current` (cache poziomu na żywo, backend go zapisuje) jest osobnym wolumenem Dockera. Test dymny: `bash scripts/compose_smoke.sh` (PASS: `/`, `/api/meta`, `/historia`).
- **Pomiar `/api/zones` przez nginx** (localhost:8080, `draft=1.2&margin=0.3`, 7 różnych `h` 194,00–197,30, każde pierwsze żądanie bez cache backendu): mediana 0,092 s, maksimum 0,134 s (rozmiar odpowiedzi 143–251 kB). Powtórzone żądanie (cache backendu): ok. 3 ms. Kryterium M5 (< 1 s) i §11 (≤ 2 s) spełnione z dużym zapasem.
- **Obrazy:** backend 2,41 GB (pakiet `mielizna` ciągnie scikit-learn, matplotlib, laspy itd.), frontend 77 MB.
- **Pułapki:** slim wymaga `libexpat1` dla rasterio; kontekst budowania backendu to katalog `JezioroNyskie/` (zależność `../pipeline`), stąd `.dockerignore` w korzeniu, który wyklucza `data/`.
