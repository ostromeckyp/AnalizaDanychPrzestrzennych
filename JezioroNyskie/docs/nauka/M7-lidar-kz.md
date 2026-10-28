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
