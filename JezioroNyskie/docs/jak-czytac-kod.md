# Jak czytać kod: skąd bierze się głębokość

Ten przewodnik mówi, w jakiej kolejności czytać pliki, żeby zrozumieć, jak ze zdjęć satelitarnych
dostajemy głębokość wody i strefę (bezpieczna / ryzykowna / zbyt płytka). Kroki 1–5 opisują część satelitarną,
kroki 6–7 dwie poprawki robione w pipeline'ie: poszerzenie przedziałów (kalibrację) i dno z mapy KŻ tam, gdzie satelita
dna nie widzi.
Każdy krok to jeden plik i jedna myśl. Nie musisz znać Pythona, żeby iść za opisem: w każdym pliku
na górze jest komentarz „Co robi / Dlaczego tak / Wejście → wyjście".

## Pomysł w jednym akapicie

Satelita Sentinel-2 przelatuje nad jeziorem co kilka dni. Na każdym zdjęciu widać, czy dany piksel
(kwadracik 10 × 10 m) jest wodą, czy lądem. Znamy też, jak wysoko stała woda w dniu zdjęcia.
Jeśli piksel był wodą, gdy poziom wynosił 195 m, to dno leży poniżej 195 m. Jeśli był lądem przy
194 m, to dno leży powyżej 194 m. Z wielu zdjęć o różnych poziomach wychodzi dla piksela
przedział: dno jest między `z_min` a `z_max` (metry nad poziomem morza). Reszta to arytmetyka:
głębokość to poziom wody minus dno.

## Ścieżka czytania

### Krok 1. Poziom wody w dniu zdjęcia: `pipeline/06_water_levels.py` i `pipeline/mielizna/levels.py`

Zdjęcie samo nie mówi, jaki był poziom wody. Ten krok przypisuje każdej scenie rzędną `h_t`
(w metrach n.p.m.) i niepewność `h_sigma`. Robi to funkcja `assign_levels` w `levels.py`,
a skrypt `06_water_levels.py` ją uruchamia i zapisuje `scenes.json`. Źródła, od najlepszego:

- **R**: znany pomiar z wodowskazu (`known_levels.csv`).
- **B**: pojemność zbiornika z komunikatu RZGW, zamieniona tabelą KŻ na rzędną (`variant_b`).
  Niepewność to stałe 0,15 m (`B_SIGMA`).
- **A**: rzędna odczytana z NMT wzdłuż brzegu. Pochodzi z opcjonalnego pliku `levels_a.csv` (robi go skrypt 06b;
  bez niego skrypt 06 liczy tylko R, B i C). Uzupełnia tylko dni, w których nie ma B ani R.
- **C**: rzędna z krzywej „powierzchnia jeziora → poziom" (`variant_c`), dla scen, które nie mają ani R, ani B,
  ani A i przeszły kontrolę jakości (QC). Niepewność jest większa (błąd z walidacji rok po roku, `rmse_loyo`;
  przy ekstrapolacji krzywej jeszcze +0,1 m), więc takim scenom ufamy mniej. Scena, która nie przeszła QC,
  a nie ma R/B/A, dostaje metodę `qc_excluded` i bez poziomu nie bierze udziału w modelu.

Wynik tego kroku: dla każdej sceny para `h_t`, `h_sigma` i litera metody.

### Krok 2. Granice dna z serii scen: `pipeline/mielizna/bottom.py`, funkcja `compute_bounds`

Najpierw `combine_evidence` łączy dwie maski wody (RF i Otsu) w jedną obserwację na scenę:
1 = woda (obie metody zgodne), 0 = ląd (choć jedna mówi „ląd"), 255 = nieznane.
Potem `compute_bounds` (praca w `_bounds_strip`) robi dla każdego piksela to:

1. Układa sceny według poziomu `h_t`.
2. Szuka progu dna, który zgadza się z jak największą liczbą scen: woda przy poziomach powyżej progu, ląd przy
   poziomach poniżej progu. Pojedyncza pomyłka klasyfikatora zwykle nie przesuwa progu; przy remisie między
   progami bierzemy obwiednię (przedział szerszy, nigdy węższy). Liczba scen sprzecznych z progiem trafia do `n_conflict`.
3. `z_max_raw` to najniższy poziom, przy którym piksel jest wodą spójną z progiem (dno jest najwyżej tak wysoko).
   `z_min_raw` to najwyższy poziom, przy którym piksel jest lądem spójnym z progiem (dno jest co najmniej tak wysoko).
4. Poszerza przedział o niepewność poziomu dokładnie tak: `z_min` to maksimum z `h − k_sigma · h_sigma` po scenach
   lądu spójnych z progiem, a `z_max` to minimum z `h + k_sigma · h_sigma` po scenach wody (nie-C) spójnych z progiem.
   Domyślnie `k_sigma = 1`. Każda scena liczy się osobno, nie tylko ta o skrajnym `h`.
5. Reguła R24: woda ze sceny typu C jest traktowana jak „nieznane" przy wyznaczaniu progu i `z_max`
   (poziom C bywa zaniżony, a zaniżony poziom wody obniżałby `z_max` w niebezpiecznym kierunku).
   Ląd ze sceny C zostaje. Piksel, któremu pominięto wodę z C, dostaje flagę 8 (informacyjną).
6. Brak spójnego lądu → `z_min = NaN`, czyli −∞ (zawsze woda, flaga 1). Brak spójnej wody → `z_max = NaN`,
   czyli +∞ (zawsze ląd, flaga 2). Flaga 4 (CONFLICT) znaczy, że część scen przeczy progowi (`n_conflict > 0`).
   Flaga 16 (UNRESOLVED) znaczy, że piksel ma obserwacje, ale obie granice są puste (remis na jednym poziomie albo
   sprzeczne obserwacje na różnych poziomach). Taki piksel zostaje w modelu z przedziałem od −∞ do +∞, więc
   w kroku 4 zawsze wychodzi RISK.

Niezmiennik: `z_min ≤ z_min_raw < z_max_raw ≤ z_max`. Wynik zapisuje `write_model` jako rastry `bottom_zmin.tif`,
`bottom_zmax.tif`, `obs_count.tif`, `bottom_flags.tif` (katalog `data/processed/model/<okres>/`).

### Krok 3. Wczytanie do backendu: `backend/app/data.py`, funkcja `load_products`, potem `depth.satellite_bounds`

`load_products` czyta rastry z kroku 2 (`bottom.read_model`) i wywołuje `satellite_bounds` z
`backend/app/depth.py`. Ta funkcja zamienia puste wartości na nieskończoności, żeby dalej nie trzeba było
obsługiwać przypadków szczególnych:

- piksel jest poza modelem, gdy `obs_count` to 0 lub 65535, albo `flags` to 255 → obie granice NaN,
- `z_min = NaN` w modelu → `z_lo = −∞` (zawsze woda),
- `z_max = NaN` w modelu → `z_hi = +∞` (zawsze ląd).

Wynik to obiekt `Bounds` (`z_lo`, `z_hi`, `in_model`, plus `source` i `kz_conflict`, które dla satelity
są stałe: 0 i False).

Zaraz potem `load_products` wywołuje `combined_bounds` (ten sam plik `depth.py`). Jeśli istnieje katalog
`data/processed/model/<okres>_kz/`, granice z satelity są **zastępowane** granicami z tego katalogu: po kalibracji
i z dnem z mapy KŻ (kroki 6–7). Maska „w modelu” zostaje satelitarna. Bez tego katalogu (albo ze zmienną
`MIELIZNA_NO_KZ`) backend liczy na samych granicach satelitarnych. Ostrzeżenie „dno poniżej obserwacji”
(`z_max_floor`) zawsze pochodzi z surowych granic satelity; surową górną granicę (`Products.z_hi_sat`) backend trzyma też
dla popupu. Flaga `Products.combined` (w `/api/meta` jako `accuracy.combined_bounds`) mówi, czy granice łączone są
wczytane; tylko wtedy `/api/meta` podaje pokrycie kalibracji (`calibration_coverage`), a strona „O metodzie” akapit o KŻ
i kalibracji. Wersja modelu dostaje wtedy przyrostek `-kz<sha>` z odcisku bajtów rastrów łączonych, `meta.json`,
`kz_spots.csv`, `kz_loo.json` i `calibration.json` (`data.kz_version_suffix`), więc każda zmiana tych plików zmienia ETagi.

### Krok 4. Głębokość i strefa: `depth.depth_range`, potem `depth.classify`

Przy poziomie wody `h` (wybranym przez użytkownika albo bieżącym):

- `depth_range`: najpłycej `D_lo = h − z_hi`, najgłębiej `D_hi = h − z_lo`.
- `classify` z zanurzeniem `d` i zapasem `m`:
  - **DANGER** (zbyt płytko), gdy `D_hi < d`. Nawet w najgłębszym wariancie dna łódź by siadła.
  - **SAFE**, gdy `D_lo ≥ d + m`. Nawet w najpłytszym wariancie jest zapas.
  - **RISK** w pozostałych przypadkach. Przy sprzeczności wygrywa DANGER. Poza modelem jest NONE.

Funkcje `zones.py` tylko wywołują te dwie funkcje, bez własnej reguły.

### Krok 5. Jeden punkt na mapie: `backend/app/point.py`, funkcja `point_info`

Po kliknięciu w mapę `point_info` znajduje piksel, składa z jego `z_lo`, `z_hi` jednoelementowy `Bounds`
i wywołuje po kolei `classify`, `depth_range` i `point_kind`. `point_kind` rozróżnia: `land` (gdy `h ≤ z_lo`,
dno nad wodą), `always_water` (gdy `z_lo = −∞`) i `model` (zwykły piksel). Z tego powstaje to, co widzisz
w okienku: strefa, głębokość od–do i rezerwa pod stępką. Piksel z dnem z mapy KŻ ma skończone `z_lo`, więc
dostaje `model`, a pole `bottom_source = "kz"` mówi, skąd jest dno (okienko pisze wtedy „Dno: mapa KŻ 2023 (orientacyjne):
dno do P95 m głębiej albo do |P5| m płycej niż na mapie (błąd interpolacji)”). `z_max_sat` to surowa górna granica satelity
(przed kalibracją), obok skalibrowanej `z_max`. Dla piksela „zawsze woda” bez dna z KŻ, którego skalibrowana górna granica
sięga `h − d` albo wyżej, okienko (`frontend/src/vm/usePointVm.ts`, funkcja `unassessedAlwaysWater`) pisze „Głębokość
nieoceniona” i podaje obie granice; strefa się nie zmienia. Poza żwirownią i bez sprzeczności z KŻ backend dokłada
`kz_nearest`: najbliższy punkt mapy KŻ (`kz_spots.csv`) z odległością. To tylko informacja, strefy go nie używają.

### Krok 6. Kalibracja przedziałów: `pipeline/mielizna/calibration.py`, uruchamiana w `pipeline/14_kz_deep.py`

Przedział z kroku 2 jest za wąski: w rocznym hold-oucie (model bez danego roku sprawdzany na liniach wody z tego
roku) prawdziwe dno mieści się w `[z_min, z_max]` tylko w ok. 17 % przypadków. Dlatego go poszerzamy.

- Skąd poszerzenie: skrypt `12_holdout.py` zbiera, o ile prawdziwe dno wyszło poza przedział (osobno w dół
  i w górę), na pikselach brzegowych z **obiema** granicami. Funkcja `deltas` bierze z tych reszt 95. percentyl,
  osobno dla każdego pasma wysokości (192,9–194,8 m i ≥ 194,8 m). Wynik: `data/processed/eval/calibration.json`.
- Jak poszerzamy: funkcja `apply` odejmuje `δ_lo` od `z_min` i dodaje `δ_hi` do `z_max`. Pasmo piksela wybiera
  `pixel_band`: środek przedziału, a gdy jedna granica jest nieskończona, ta druga. Poniżej 192,9 m używamy
  poszerzeń pasma 192,9–194,8 m (hold-out nie ma tam danych).
- Granice nieskończone (±∞) zostają nieskończone. Ale piksel „zawsze woda” ma skończone `z_max`, więc też jest
  poszerzany w górę, choć poszerzenie zmierzono tylko na pikselach z obiema granicami. To świadoma decyzja
  (ekstrapolacja), opisana w raporcie.

`14_kz_deep.py` czyta surowe granice (tą samą regułą co `satellite_bounds`) i wywołuje `calibration.apply`.

### Krok 7. Dno z mapy KŻ w głębokiej części: `pipeline/mielizna/kz_deep.py`, potem `pipeline/mielizna/combine.py`, funkcja `merge_kz`

Piksel „zawsze woda” ma tylko górną granicę dna (ok. 193,05 m, a po kalibracji wyżej), więc satelita nie mówi,
jak głęboko jest. Tam bierzemy dno z amatorskiej mapy KŻ Nysa (2023).

1. `kz_deep.deep_surface` rozpina powierzchnię (siatka trójkątów, TIN) na punktach rzędnych KŻ i poziomicy 192,5 m.
   Poziomicy 195,0 m celowo nie używa: bez niej sprzeczności z obrazami satelitarnymi jest mniej więcej o połowę mniej.
2. `kz_deep.loo` sprawdza tę powierzchnię: usuwa po kolei jeden punkt, buduje powierzchnię z pozostałych i patrzy,
   o ile chybia w miejscu usuniętego punktu (błąd = odczyt − rzędna punktu; dodatni = powierzchnia płycej).
   Z tych błędów bierze P5 (ok. −2,0 m) i P95 (ok. +3,0 m). To **błąd interpolacji mapy KŻ**, nie całkowity błąd:
   nie widzi błędów samego pomiaru KŻ. Wynik: `eval/kz_loo.json`.
3. `combine.merge_kz` dla piksela z `z_lo = −∞`, w którym powierzchnia ma wartość `kz`:
   - dolna granica: `z_lo = kz − P95`,
   - górna granica: `z_hi = min(z_hi, kz − P5)` (nie wyżej niż skalibrowana granica satelity),
   - źródło 1 (KŻ).
   Jeśli nawet `kz − P95` wychodzi wyżej niż `z_hi` satelity, mapa przeczy satelicie: piksel zostaje satelitarny
   i dostaje znacznik sprzeczności (`kz_conflict`). Pozostałe piksele są bez zmian.

Wynik zapisuje `14_kz_deep.py` w `data/processed/model/<okres>_kz/` (`bottom_zlo.tif`, `bottom_zhi.tif`,
`bottom_source.tif`: bit 0 = KŻ, bit 1 = sprzeczność; `meta.json` z P5/P95; `kz_spots.csv`: punkty KŻ użyte do powierzchni,
dla popupu). Te rastry wczytuje backend w kroku 3
(`depth.combined_bounds`). Kontrole modelu (hold-out, LiDAR, KŻ, budżet) ich **nie** czytają, żeby mapa KŻ nie
oceniała modelu, którego jest częścią.

## Przykład A: jeden piksel, cztery sceny

Liczby poniżej policzył prawdziwy kod (test `backend/tests/test_guide_example.py` liczy je od nowa
i pilnuje, żeby ten tekst się z nimi zgadzał). Piksel ma cztery obserwacje:

| Scena | `h_t` [m] | `h_sigma` [m] | Metoda | Obserwacja |
|---|---|---|---|---|
| 1 | 194,9 | 0,15 | B | woda |
| 2 | 194,2 | 0,15 | B | ląd |
| 3 | 195,6 | 0,40 | C | woda |
| 4 | 193,8 | 0,15 | B | ląd |

**Krok 2 (`compute_bounds`, `k_sigma = 1`).** Obserwacje są spójne (woda wyżej niż ląd), więc `n_conflict = 0`.
Najwyższy ląd to 194,2 m, a najniższa woda, której wolno ufać, to 194,9 m. Woda ze sceny 3 pochodzi z metody C,
więc reguła R24 ją pomija (flaga 8). Dostajemy surowy przedział `z_min_raw = 194,2` i `z_max_raw = 194,9`.
Po poszerzeniu o `1 · 0,15 m`: `z_min = 194,2 − 0,15 = 194,05` i `z_max = 194,9 + 0,15 = 195,05`.
Dno leży więc między 194,05 a 195,05 m n.p.m.

**Krok 3.** `satellite_bounds` daje `z_lo = 194,05`, `z_hi = 195,05` (skończone, piksel w modelu).

**Krok 4** dla `h = 195,5` m, zanurzenia `d = 0,5` m i zapasu `m = 0,3` m:
`D_lo = 195,5 − 195,05 = 0,45` m i `D_hi = 195,5 − 194,05 = 1,45` m, czyli głębokość 0,45 do 1,45 m.
Zbyt płytko nie jest (`D_hi = 1,45 ≥ 0,5`), ale bezpiecznie też nie (`D_lo = 0,45 < 0,5 + 0,3 = 0,8`).
Strefa: **RISK**.

**Krok 5.** `h = 195,5 > z_lo = 194,05`, więc `point_kind` zwraca `model`.

## Przykład B: piksel „zawsze woda” z dnem z mapy KŻ

Też policzony prawdziwym kodem (ten sam test). Piksel był wodą na każdej scenie, więc `z_min = NaN`
(flaga 1), a `z_max = 193,05` m (typowa wartość w tej strefie). Liczby kalibracji i KŻ to wartości z plików
`calibration.json` i `model/all_kz/meta.json` zaokrąglone do 0,01 m: dla pasma 192,9–194,8 m `δ_hi = 2,23` m,
a z LOO `P5 = −2,00` m i `P95 = +3,02` m. Rzędną mapy KŻ w tym pikselu przyjmujemy dla przykładu `kz = 190,0` m.

**Krok 3 (`satellite_bounds`).** `z_lo = −∞`, `z_hi = 193,05`.

**Krok 6 (`calibration.apply`).** Jedyna skończona granica to 193,05 m, więc pasmo 192,9–194,8 m.
`z_lo` zostaje −∞, a `z_hi = 193,05 + 2,23 = 195,28`.

**Krok 7 (`combine.merge_kz`).** `z_lo = 190,0 − 3,02 = 186,98` i `z_hi = min(195,28; 190,0 + 2,00) = 192,00`.
Sprzeczności nie ma (186,98 nie leży wyżej niż 195,28), więc źródło to KŻ. Dno leży między 186,98 a 192,00 m n.p.m.

**Krok 4** dla `h = 194,5` m (najczęstszy poziom), `d = 0,5` m i `m = 0,3` m:
`D_lo = 194,5 − 192,00 = 2,50` m i `D_hi = 194,5 − 186,98 = 7,52` m. `D_lo = 2,50 ≥ 0,8`, więc strefa **SAFE**.

**Krok 5.** `z_lo = 186,98` jest skończone, więc `point_kind` zwraca `model`; okienko pokazuje głębokość
2,50–7,52 m i wiersz „Dno: mapa KŻ 2023 (orientacyjne; …)” z ostrzeżeniem, że mapa jest amatorska.

**Ten sam piksel bez mapy KŻ** (powierzchnia KŻ go nie obejmuje): po kroku 6 zostaje `z_lo = −∞`, `z_hi = 195,28`.
Wtedy `D_lo = 194,5 − 195,28 = −0,78` m (granica dna może leżeć nad wodą), a `D_hi = +∞`. Ani bezpiecznie, ani na
pewno za płytko: strefa **RISK**, a `point_kind` zwraca `always_water`. Okienko pisze wtedy „Głębokość nieoceniona”:
dno poniżej 193,05 m n.p.m. według satelity, a górna granica po poszerzeniu to 195,28 m. Bez kalibracji (`z_hi = 193,05`) ten piksel
byłby bezpieczny (`D_lo = 1,45` m). Tak działa ekstrapolacja kalibracji na granice jednostronne (krok 6).

