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

Wyniki (221 scen):
- **Wariant A dostało 129 scen** (2017: 90, 2022: 13, 2024: 26; epoka 2011 nie została wybrana ani razu). Odpadło 92: 56 przez h_sigma ≥ 0,3 m, 17 przez pokrycie < 3 sektorów, 20 bez epoki z niższą wodą (szacunek sceny < ok. 193,8 m, a najniższa epoka to 2017: 193,59 m), 1 bez szacunku (qc_excluded).
- **h_sigma** (1,4826·MAD) przyjętych scen: mediana 0,22 m, 90. percentyl 0,27 m, maks. 0,30 m (po zaokrągleniu; 125 z 129 ma ściśle < 0,3). Bez bramki: 183 sceny, mediana 0,24 m, maks. 0,73 m — w ok. 1/3 przypadków rozrzut rzędnych wzdłuż brzegu jest zbyt duży (nachylony brzeg + błąd położenia linii ~10 m), więc taki „poziom” nie jest wiarygodny.
- **Pokrycie NMT:** epoki 2017 i 2022 mają NMT tylko dla 2 arkuszy (wschodni brzeg, zapora), więc przechodzą bramkę sektorów ledwo (3 z 8) albo wcale (2 sektory: 2017: 7, 2022: 10 scen odpadło przed bramką sigma).
- **A vs B** (92 sceny z oboma): `h_diff_ab = A − B` ma medianę −0,16 m, rozrzut (odch. std.) 0,57 m, zakres −1,45…+0,76 m; |różnica| > 0,2 m w 70 z 92. Wg epok: 2017 mediana −0,28 m (n=54, std 0,48), 2022 −0,26 m (n=12, std 0,26), 2024 +0,63 m (n=26, std 0,17). To tylko raport. Znak różnicy zależy od epoki (2024 powyżej B, 2017 i 2022 poniżej), więc nie wygląda na jedno stałe przesunięcie układu RZGW; skłania raczej ku błędowi samej metody (mało pokrywających NMT arkuszy, nasyp zapory o stromym profilu, położenie linii brzegowej ±10 m) niż ku datum. Do rozstrzygnięcia przy ocenie (Task 8).
- **M3 (2024-09-06, cel 194,70 ± 0,3):** A = 194,41 m (epoka 2017, n=659), B = 194,61 m; różnica do celu −0,29 m, czyli na granicy.
- Skutek uboczny: A zastąpiło B w 92 scenach i wchodzi do dopasowania krzywej powierzchnia–rzędna (stare zachowanie `assign_levels`); RMSE LOO krzywej wynosi teraz 0,64 m (Otsu; przed A ok. 0,47 m wg opisu w `levels.py`, nie mierzone ponownie), co jest sygnałem ostrzegawczym dla jakości A.
