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
- **Krzywa powierzchnia–rzędna, błąd LOO (pomiar, Otsu):** bez A 0,466 m (LOYO 0,488, n_obs=131); z A w dopasowaniu 0,508 m (LOYO 0,583, n_obs=164). A pogarsza krzywą, ale dotyczy tylko scen C; zostawione bez zmian (do decyzji).
- **Obciążenie zależne od epoki (A − B, 92 dni z oboma):** mediana −0,16 m, std 0,57, |różnica| > 0,2 m w 70 z 92.

| epoka NMT | n | mediana A−B [m] | std | min | maks |
|---|---|---|---|---|---|
| 2017 | 54 | −0,28 | 0,48 | −1,45 | +0,58 |
| 2022 | 12 | −0,26 | 0,26 | −0,95 | −0,04 |
| 2024 | 26 | +0,62 | 0,17 | +0,02 | +0,76 |

  Znak różnicy zależy od epoki (2024 powyżej B, 2017 i 2022 poniżej), więc to raczej obciążenie metody/pokrycia NMT (2017 i 2022: tylko wschodni nasyp, ≥ 3 z 8 sektorów; stromy profil; położenie linii brzegowej ±10 m) niż jedno stałe przesunięcie układu RZGW. Wniosek do Task 8: A traktować jako uzupełnienie z niepewnością większą niż deklarowane `h_sigma`.
- **Pokrycie NMT:** epoki 2017 i 2022 mają NMT tylko dla 2 arkuszy; 7 (2017) i 10 (2022) scen odpadło na sektorach.
- **M3 (2024-09-06, cel 194,70 ± 0,3):** h_t = B = 194,61 m (A = 194,41 m, epoka 2017).
