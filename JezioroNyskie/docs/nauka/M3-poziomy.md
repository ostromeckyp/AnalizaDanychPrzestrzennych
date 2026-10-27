# M3 — Poziomy wody: jaką rzędną miało jezioro w dniu każdego zdjęcia

Po ludzku: zdjęcie satelitarne pokazuje *ile* jest wody, ale nie *na jakiej wysokości* jest jej lustro. A do modelu dna
potrzebujemy właśnie wysokości (rzędna, m n.p.m.). Ten krok przypisuje każdej scenie liczbę h_t i jej niepewność.
Liczby: `data/processed/scenes.json`, `model/area_level_curve.json`, `logs/06_water_levels.log`, `logs/04_classify.log`.

## 1. Co powstało (pliki)

| plik | zawartość |
|---|---|
| `data/processed/scenes.json` | 221 obiektów: `date, h_t, h_sigma, h_method, h_source, h_datum, area_km2, qc_ok, qc_reason, capacity_mln_m3…` |
| `data/processed/model/area_level_curve.json` | krzywa powierzchnia → poziom (7 węzłów, izotoniczna + PCHIP) |
| `data/processed/qc/area_vs_level.png` | wykres: punkty (scena = powierzchnia i poziom) + krzywa |
| `data/reference/kz_pojemnosc_rzedna.csv` | tabela KŻ pojemność ↔ rzędna (66 wierszy) |
| `data/reference/known_levels.csv` | ręczne poziomy (wariant R): 2025-04-28..2025-05-12 = 197,92 m |
| `shorelines.gpkg` | te same h_t i metoda dopisane do linii brzegowych |

Skrypt: `06_water_levels.py`; logika w `mielizna/levels.py`, `capacity.py`.

## 2. Cztery warianty poziomu (od najpewniejszego)

Kolejność pierwszeństwa: **A > R > B > C**.

| wariant | skąd h_t | niepewność σ | liczba scen (`scenes.json`) |
|---|---|---|---|
| **A** | własny pomiar/wodowskaz (plan 4, jeszcze brak) | – | 0 |
| **R** | znany poziom z `known_levels.csv` (piętrzenie 2025, 197,92 m) | 0,08 m | 2 (2025-04-28, 2025-05-01) |
| **B** | komunikat RZGW: pojemność → rzędna z tabeli KŻ | 0,15 m | 155 |
| **C** | z krzywej powierzchnia–poziom (zdjęcie jako czujnik) | 0,49 m | 63 |
| qc_excluded | scena odrzucona przez QC, brak komunikatu → bez h_t | – | 1 (2019-06-15) |

Razem 221 scen; h_t od **192,90** do **197,92 m**.

**B (komunikat).** Komunikat RZGW podaje pojemność zbiornika Nysa w mln m³. Interpolujemy liniowo w tabeli KŻ (np. 25,0 mln m³ = 193,0 m,
38,5 mln = 194,0 m, 47,5 mln = 194,7 m, 52,0 mln = 195,0 m, 67,0 mln = 196,0 m, 84,0 mln = 197,0 m, 122,0 mln = 198,9 m;
`kz_pojemnosc_rzedna.csv`, 66 wierszy, 18,0 mln m³ = 192,4 m na początku). σ = 0,15 m to założenie robocze: rozbieżność interpolacji
względem tabeli ≈ 0,13 m, zmiana krzywej pojemności 2021→2024 ≈ 0,04 m, komunikat ±1 dzień.

**C (krzywa z powierzchni).** Sceny bez komunikatu (głównie 2017–2019 — 53 sceny sprzed 2019-11-04) dostają poziom z powierzchni wody.
Krzywa jest dopasowana do scen B/R, które mają i powierzchnię, i poziom: **131 obserwacji, 7 węzłów**, powierzchnia Otsu **10,58–14,40 km²**
(`area_level_curve.json`):

| powierzchnia (km²) | 10,58 | 11,81 | 12,40 | 12,99 | 13,31 | 13,75 | 14,40 |
|---|---|---|---|---|---|---|---|
| poziom (m) | 192,90 | 193,30 | 193,70 | 194,52 | 195,26 | 195,97 | 197,14 |

Metoda: *izotoniczna* (krzywa nie może maleć — więcej wody = wyżej) + *PCHIP* (gładka, bez przeskoków i bez „falowania"); poza zakresem
liniowo po 3 ostatnich punktach (ekstrapolowanych scen: 0). Błąd krzywej: **LOO RMSE = 0,466 m** (usuń jedną scenę, przewiduj ją z reszty) i
**LOYO RMSE = 0,488 m** (usuń cały rok). C dostaje σ = LOYO = 0,49, bo w jednym roku błędy są skorelowane (cały rok bez komunikatu), więc
LOO byłoby zbyt optymistyczne. 7 scen C ma `area_biased` (>1% jeziora bez danych).

## 3. Historia D3 / R23: „luka 0,44 m" i dlaczego to nie układ wysokości

Pierwszy przebieg (zapisany w ledgerze, nie jest już plikiem): sceny B z okresu v_npp = 66,3 leżały średnio **+0,28 m** nad krzywą, a z v_npp ≤ 65,7
**−0,16 m** pod nią (luka ≈ 0,44 m ≫ 0,04 m spodziewane z samej zmiany krzywej pojemności). Podejrzewaliśmy błąd układu wysokościowego/tabeli.

Rozstrzygnięcie (R23): to **nie** układ odniesienia. Zmiana pojemności ogranicza możliwą różnicę do ≤ 0,05 m, a komunikaty Nysa nie niosą rzędnej.
Przyczyną było **8 scen z lipca–września 2020** przy wysokim poziomie, gdzie powierzchnia jest o 0,17–0,60 km² mniejsza niż wynikałoby z poziomu —
**ten sam efekt widać w Otsu**, więc to zjawisko powierzchniowe (np. rozlana roślinność, zakwit), a nie błąd poziomu. Plus rozcieńczenie regresji
(punkty z szumem po osi powierzchni spłaszczają krzywą). Nie korygujemy; σ B zostaje 0,15.

Wynik końcowy (`06_water_levels.log`, powierzchnia Otsu): reszta B − krzywa w reżimie v_npp = 65,7: n = 90, mediana **−0,035 m**; v_npp = 66,3:
n = 39, mediana +0,112 m, a **bez lipca–września 2020 n = 28, mediana −0,014 m** (jednak reszty obu reżimów zbiegają się).

**Powierzchnia RF się nasyca.** Przy poziomach poniżej ~194 m powierzchnia RF stoi na ok. 12,9 km², bo RF uznaje błoto za wodę (M2). Na tej krzywej
reszta B = −0,68 m (65,7) — bez sensu. Dlatego krzywą budujemy z powierzchni **Otsu** (`area_source: area_otsu_km2`): LOO RMSE spadło z 0,657 → 0,466 m,
LOYO z 0,701 → 0,488 m. Konsekwencja dla planu 2: backend ma karmić krzywą powierzchnią Otsu, nie RF.

**Test M3.** Cel: 05–12.09.2024 powinno być ≈ 194,70 ± 0,3 m (okres pomiaru). `scenes.json`: 2024-09-06 h_t = **194,61 m, B ✓**; sąsiednia 2024-09-03 = 194,63.
Powódź (Boris): 2024-09-18 = 196,74; 2024-09-21 = 197,06. Nie strojono do M3, tylko sprawdzono.

**Jesień 2018 (kontrola sensu C).** C 2018-09-20..11-17: 194,58 → 192,95 → 193,33 m (obniżanie, potem wzrost), czyli zachowuje się jak spuszczany zbiornik.

## 4. Pytania, które może zadać prowadzący

**1. Skąd wiesz, jaką rzędną miało jezioro w dniu zdjęcia?**
Dla 157 scen (B+R) z komunikatu RZGW (pojemność) i tabeli KŻ albo ze znanego piętrzenia; dla 63 scen (C) z krzywej powierzchnia–poziom
dopasowanej do scen B. Każda ma jawnie zapisaną niepewność i źródło (`h_source`) w `scenes.json`.

**2. Dlaczego niepewność C to aż 0,49 m?**
Bo tyle wynosi błąd przewidywania, gdy krzywą trzeba zastosować do zupełnie nowego roku (LOYO = 0,488 m). LOO (0,466 m) jest zbyt optymistyczne,
bo sąsiednie sceny tego samego roku mają skorelowany błąd. Model dna uwzględnia to: sceny C nigdy same nie ustalają górnej granicy dna (M4).

**3. Czy luka 0,44 m między okresami nie zepsuła wyników?**
Zbadaliśmy: wynika z 8–11 letnich scen 2020 (zjawisko powierzchniowe widoczne też w Otsu), nie z układu wysokości. Po wykluczeniu
lipca–września 2020 mediany reszt obu reżimów to −0,014 i −0,035 m. Nie wprowadziliśmy korekty, bo żadna nie byłaby poparta danymi.

**4. Dlaczego krzywa z Otsu, skoro Otsu jest „gorsze" od RF w M2?**
Do krzywej liczy się *stabilność* powierzchni w funkcji poziomu, a RF przy niskiej wodzie uznaje błoto za wodę i powierzchnia przestaje maleć (nasycenie
~12,9 km²). Otsu zachowuje monotoniczność; błąd LOO spadł z 0,657 do 0,466 m. To dobór z wyniku, ale mierzony na danych krzywej, nie na etykietach M2.

**5. Dlaczego izotoniczna + PCHIP, a nie zwykła regresja?**
Prosta/wielomian dałyby przeregulowanie na końcach i mogły malejąco przewidywać. Izotoniczna gwarantuje monotoniczność (więcej wody = wyżej), PCHIP daje gładkość bez przeskoków.

**6. Co z poziomem w układzie wysokościowym?**
`h_datum: unknown (RZGW, prawdopodobnie KRON86)`. Zapisujemy to wprost w `scenes.json`. Porównanie z mapą KŻ (głębokości) zostaje na plan 4.

**7. Skąd wiesz, że M3 (194,70 ± 0,3) nie był „dopasowany"?**
Żaden parametr nie był stroją pod tę liczbę; M3 sprawdzono po fakcie. Wynik 194,61 m dla 2024-09-06 leży w tolerancji. Jest to jednak jedna scena.

**8. Co się dzieje przy poziomie powyżej ~197,1 m (koniec krzywej)?**
Dla C ekstrapolacja liniowa z σ + 0,1; w danych nie ma takiej sceny C (0 ekstrapolowanych). Powyżej 197 m mamy sceny B/R (max B 197,49; R 197,92).
