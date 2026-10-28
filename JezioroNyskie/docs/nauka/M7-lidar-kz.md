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
