# Jak czytać kod: skąd bierze się głębokość

Ten przewodnik mówi, w jakiej kolejności czytać pliki, żeby zrozumieć, jak z zdjęć satelitarnych
dostajemy głębokość wody i strefę (bezpieczna / ryzykowna / zbyt płytka). Opisuje część satelitarną.
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
- **A**: rzędna odczytana z NMT wzdłuż brzegu. Uzupełnia tylko dni, w których nie ma B ani R.
- **C**: rzędna z krzywej „powierzchnia jeziora → poziom" (`variant_c`), dla scen bez komunikatu.
  Niepewność jest większa (błąd z walidacji rok po roku, `rmse_loyo`), więc takim scenom ufamy mniej.

Wynik tego kroku: dla każdej sceny para `h_t`, `h_sigma` i litera metody.

### Krok 2. Granice dna z serii scen: `pipeline/mielizna/bottom.py`, funkcja `compute_bounds`

Najpierw `combine_evidence` łączy dwie maski wody (RF i Otsu) w jedną obserwację na scenę:
1 = woda (obie metody zgodne), 0 = ląd (choć jedna mówi „ląd"), 255 = nieznane.
Potem `compute_bounds` (praca w `_bounds_strip`) robi dla każdego piksela to:

1. Układa sceny według poziomu `h_t`.
2. Szuka progu dna, który zgadza się z jak największą liczbą scen (woda poniżej progu, ląd powyżej).
   Pojedyncza pomyłka klasyfikatora nie psuje wyniku. Liczba sprzecznych scen trafia do `n_conflict`.
3. `z_max_raw` to najniższy poziom, przy którym piksel jest wodą spójną z progiem (dno jest najwyżej tak wysoko).
   `z_min_raw` to najwyższy poziom, przy którym piksel jest lądem spójnym z progiem (dno jest co najmniej tak wysoko).
4. Poszerza przedział o niepewność poziomu: `z_min = z_min_raw − k_sigma · h_sigma` (przy lądzie, który wyznaczył
   dolną granicę) oraz `z_max = z_max_raw + k_sigma · h_sigma` (przy wodzie, która wyznaczyła górną granicę).
   Domyślnie `k_sigma = 1`. Dokładniej: dla granicy bierze się maksimum (dół) albo minimum (góra) z wartości
   `h ∓ k_sigma · h_sigma` po wszystkich scenach spójnych z progiem, nie samo σ jednej sceny.
5. Reguła R24: woda ze sceny typu C jest traktowana jak „nieznane" przy wyznaczaniu progu i `z_max`
   (poziom C bywa zaniżony, a zaniżony poziom wody obniżałby `z_max` w niebezpiecznym kierunku).
   Ląd ze sceny C zostaje. Piksel, któremu pominięto wodę z C, dostaje flagę 8 (informacyjną).
6. Brak spójnego lądu → `z_min = NaN`, czyli −∞ (zawsze woda, flaga 1). Brak spójnej wody → `z_max = NaN`,
   czyli +∞ (zawsze ląd, flaga 2).

Niezmiennik: `z_min ≤ z_min_raw < z_max_raw ≤ z_max`. Wynik zapisuje `write_model` jako rastry `bottom_zmin.tif`,
`bottom_zmax.tif`, `obs_count`, `flags` (katalog `data/processed/model/<okres>/`).

### Krok 3. Wczytanie do backendu: `backend/app/data.py`, funkcja `load_products`, potem `depth.satellite_bounds`

`load_products` czyta rastry z kroku 2 (`bottom.read_model`) i wywołuje `satellite_bounds` z
`backend/app/depth.py`. Ta funkcja zamienia puste wartości na nieskończoności, żeby dalej nie trzeba było
obsługiwać przypadków szczególnych:

- piksel jest poza modelem, gdy `obs_count` to 0 lub 65535, albo `flags` to 255 (obie granice = NaN),
- `z_min = NaN` w modelu → `z_lo = −∞` (zawsze woda),
- `z_max = NaN` w modelu → `z_hi = +∞` (zawsze ląd).

Wynik to obiekt `Bounds` (`z_lo`, `z_hi`, `in_model`, plus `source` i `kz_conflict`, które dla satelity
są stałe: 0 i False).

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
w okienku: strefa, głębokość od–do i rezerwa pod stępką.

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
