# M1 — Dane: skąd bierzemy zdjęcia, jak je czyścimy i skąd wiemy, ile wody było w jeziorze

Jak to czytać: najpierw „po ludzku", potem w nawiasie nazwa techniczna. Wszystkie liczby pochodzą
z plików w `data/processed/` (nazwa pliku podana przy liczbie). Stan: pipeline z gałęzi `feat/pipeline`.

## 1. Co powstało (pliki)

| plik | co to jest |
|---|---|
| `data/processed/lake.gpkg`, `marinas.gpkg` | obrys jeziora i bufor 500 m (AOI) z OpenStreetMap; przystanie/pomosty |
| `data/processed/scenes_candidates.csv` | 679 wierszy: każda *akwizycja* Sentinel-2 (data + satelita) z jakością (chmury, braki, lód) |
| `data/processed/s2/{data}.tif` | 221 zdjęć („scen") przycięte do jednej siatki 10 m (EPSG:2180), 6 pasm + SCL |
| `data/processed/scenes_pass2_rejected.csv` | sceny odrzucone po pobraniu (1 wiersz: 2022-02-14) |
| `data/processed/bulletins.csv` | 158 komunikatów RZGW o pojemności zbiornika Nysa (z nich liczymy poziom wody) |
| `pipeline/config.yaml` | siatka, okresy, filtr scen, lista 15 wykluczonych dat |

Skrypty: `03_fetch_osm.py` (obrys), `01_fetch_s2.py` (Sentinel-2), `06a_fetch_bulletins.py` (komunikaty).

## 2. Liczby z tego przebiegu

- **Sceny użyteczne: 221** (`scenes.json`, `classify_stats.csv`). W CSV jest 679 wierszy akwizycji = 650 różnych dat;
  po filtrach i deduplikacji zostaje 221 dat, każda z jednego zdjęcia.
- **Rozkład po miesiącach** (`scenes.json`): sty 5, lut 4, mar 14, kwi 31, maj 20, cze 25, lip 22, sie 35, wrz 26,
  paź 24, lis 12, gru 3. Zimy są ubogie (lód, chmury), lato dobrze pokryte.
- **Rozkład po latach**: 2017: 7, 2018: 26, 2019: 21, 2020: 29, 2021: 17, 2022: 21, 2023: 23, 2024: 21, 2025: 29, 2026: 27.
- **Wykluczone ręcznie (lód/śnieg/uszkodzone): 15 dat** w `config.yaml` (14 z przeglądu lodu + 2024-09-01 uszkodzona).
  Dodatkowo 2022-02-14 odrzucona automatycznie (`scenes_pass2_rejected.csv`).
- **Komunikaty RZGW: 158 wierszy** w `bulletins.csv` (86 z archiwum Wayback, 72 z listy gov.pl). Log
  `06a_fetch_bulletins.log`: „pokrycie: 158 / 222 scen" (stan sprzed usunięcia 2024-09-01; po nim jest 221 scen).
  Żadna z 54 scen z lat 2017–2019 nie ma komunikatu (`bulletins.csv` zaczyna się w 2020; najwcześniejszy komunikat to 2019-12-31): Wayback
  zaczyna się 2019-11-04. Wszystkie 53 sceny sprzed tej daty dostały poziom z krzywej (wariant C), 0 z nich ekstrapolowanych (`06_water_levels.log`).
  Lista gov.pl sięga tylko 2024-02-26..2026-10-26 (719 komunikatów, log 06a).
- **Godzina odczytu** (`reading_utc`): 156 komunikatów z odczytem 06:00 UTC, 2 z 12:00 UTC.
- **Stan magazynowy „v_npp"** (pojemność przy normalnym poziomie piętrzenia): 66,3 mln m³ w 2020-01..2021-11 (45 komunikatów),
  65,7 od 2022-04 (113 komunikatów po zaokrągleniu do 0,1). To zmiana instrukcji zbiornika, istotna dla M3.

## 3. Dlaczego tak (po ludzku, potem technicznie)

**Skąd zdjęcia.** Satelity Sentinel-2 (Unia Europejska) robią zdjęcie jeziora co kilka dni, za darmo. Bierzemy je z katalogu
*Earth Search* (format STAC, pliki COG w chmurze AWS), nie pobierając całych 100-megabajtowych kafli: odczytujemy tylko
wycinek wokół jeziora (`odc-stac`).

**Jedna siatka dla wszystkiego** (`grid:` w `config.yaml`: EPSG:2180, piksel 10 m, 900×700). Wszystkie pasma i warstwy mają
ten sam piksel, więc można je dodawać piksel po pikselu bez przeliczeń.

**Dwa przebiegi pobierania.** Przebieg 1 czyta tylko tanią warstwę SCL (klasyfikacja chmur ESA) dla wszystkich dat i liczy, które
dni są czyste. Przebieg 2 pobiera pełne 6 pasm tylko dla dni użytecznych. Dzięki temu nie ściągamy zdjęć, których i tak nie użyjemy.
Skrypt jest wznawialny: gotowy plik/wiersz CSV jest pomijany.

**Przesunięcie radiometryczne (R7, R10).** ESA od baseline 04.00 (styczeń 2022) dodaje do liczb +1000 („offset"). Zmierzyliśmy,
że Earth Search ma to już odjęte we *wszystkich* produktach, a metadane (`raster:bands.offset = -0.1`) kłamią. Gdybyśmy zastosowali
offset z metadanych, czysta woda miałaby ujemne odbicie. Dlatego `reflectance_offset()` zawsze zwraca 0.0, a *zabezpieczenie*
`check_harmonized` odrzuca scenę, jeśli 5. percentyl SWIR16 nad wodą > 900 DN (woda w SWIR ma ~10–60 DN). Złapało to 2022-02-14.

**Deduplikacja (R8).** Ta sama data bywa dostępna jako kilka produktów (różne wersje przetwarzania, różni satelity A/B/C).
Klucz = (satelita, kafel, data); zostaje najwyższa wersja przetwarzania. Nigdy nie sklejamy różnych satelitów.
Gdy data ma dwa kafle (33UXR i 33UXS), sklejamy je „pierwszy ważny wygrywa", ale wszystkie pasma z tego samego kafla.

**Lód (14 dat wykluczonych).** Zimą jezioro bywa zamarznięte, a lód wygląda dla algorytmu jak ląd. Sprawdziliśmy 40 zimowych miniatur
*oglądając je* i wykluczyliśmy 14 (`task-4-ice-decisions`). Dlaczego nie automat: SCL klasy 11 (śnieg/lód) = 0% na jeziorze w każdej
dacie, czyli nie wykrywa lodu na wodzie; prosty próg jasności (blue>0,10 i green>0,10) łapie tylko kilka dat z marca 2026 i 2021-03-03,
a cienki szary lód z 2017-02 i 2019-02 ma odbicie podobne do mętnej wody. Zasada: lód na >5% jeziora, lub gdziekolwiek na linii
brzegu, lub śnieg przy brzegu przy niejednoznacznej linii → wyklucz; w razie wątpliwości wyklucz. Koszt błędu: zła scena zimowa psuje
linię brzegową (lód = „ląd" → poziom wody pozornie niski).

**Uszkodzona scena 2024-09-01 (R20).** Wszystkie pasma czerwone/NIR/SWIR miały wartość 1 DN. Strażnik `check_radiometry`: jeśli
99. percentyl dowolnego pasma < 0,01 (przy ≥1000 ważnych pikseli) → scena uszkodzona. Ta miała 0,0001, a najgorsza dobra 0,0413 (4× zapasu).

**Poziom wody z komunikatów (wariant B).** Na zdjęciu nie widać rzędnej wody. Ale RZGW publikuje komunikaty z *pojemnością*
zbiornika Nysa (mln m³), a z mapy KŻ mamy tabelę pojemność ↔ rzędna (66 wierszy, od 18,0 mln m³ = 192,4 m do 122,0 mln m³ = 198,9 m,
`data/reference/kz_pojemnosc_rzedna.csv`). Interpolacja daje rzędną h_t. Szczegóły: M3.

**Reguła czasu odczytu (R16).** Tego samego dnia bywają dwa komunikaty (odczyt 06:00 i 12:00 UTC). Zdjęcie jest o ~10:00 UTC,
więc wybieramy komunikat z odczytem najbliższym 10:00 (remis → wcześniejszy). W danych z tego przebiegu reguła faktycznie rozstrzyga tylko 2 komunikaty z odczytem 12:00 UTC (`bulletins.csv`); przy wprowadzeniu reguły żaden wiersz nie zmienił wartości (raport 9c25957), ale 2024-09-18 dostało komunikat 12 UTC (2 h od zdjęcia) zamiast 06 UTC (4 h).
Jeśli godzina nie da się sparsować, komunikat nie wygrywa z takim, który się da.

**Znalezisko o głębokości gov.pl.** Lista komunikatów na gov.pl sięga zaledwie do 2024-02-26; starsze są tylko w archiwum Wayback
(od 2019-11-04). Dla 2017–2019 nie istnieje żaden komunikat, dlatego te sceny dostają poziom z krzywej (wariant C), a nie z danych.

## 4. Pytania, które może zadać prowadzący

**1. Skąd wiesz, że zdjęcie jest czyste, a nie zachmurzone?**
Dwa sita: kafel ma <60% chmur (tylko wstępny filtr), a lokalnie (nad jeziorem + AOI) chmury ≤5%, braki ≤5% (valid ≥95%) i lód ≤1%
(`scene_filter` w `config.yaml`). Chmury rozpoznaje SCL; maska chmur jest poszerzona o 2 piksele (cienie, mgiełka na krawędzi).

**2. Dlaczego 221, a nie 679 scen?**
679 to akwizycje (kafel × satelita × data), z duplikatami przetwarzania i zimowymi zdjęciami. Po deduplikacji zostaje 650 dat,
po filtrach jakości 221 (15 jeszcze usunęliśmy ręcznie jako lód/uszkodzone).

**3. Czy offset +1000 nie zepsuł Ci wyników po 2022?**
Nie: zmierzyliśmy ciemną wodę w SWIR (11–58 DN w każdym okresie, także w parach tej samej akwizycji ze starym i nowym przetwarzaniem)
i dodaliśmy test, który *przerywa*, gdyby offset wrócił. Złapał jedną scenę (2022-02-14).

**4. Co jeśli komunikat jest z innej godziny niż zdjęcie?**
Poziom zbiornika zmienia się powoli (cm/dzień), więc 4 godziny to zwykle <1 cm. Ale ustaliliśmy regułę (R16): z dwóch komunikatów
z tej samej doby bierzemy ten bliższy 10:00 UTC. Przy ±1 dzień dopuszczamy komunikat z sąsiedniej doby, a niepewność B ustawiamy na 0,15 m,
co to obejmuje. Koszt pomyłki: kilka centymetrów w ~3 scenach powodziowych, gdzie poziom zmieniał się szybko.

**5. Dlaczego nie zinterpolować poziomu dla scen bez komunikatu?**
Interpolacja w czasie zmyślałaby dane w czasie powodzi (poziom skacze o metry w kilka dni). Zamiast tego zdjęcie samo jest czujnikiem:
powierzchnia wody → poziom (wariant C, M3), z uczciwie większą niepewnością (0,49 m).

**6. Dlaczego akurat te 14 dat lodowych? Czy nie subiektywne?**
Tak, to ocena wzrokowa (zapisana w `config.yaml` z powodem każdej daty). Automat zawodzi (SCL i jasność), więc zasadą było „w razie
wątpliwości wyklucz". Koszt wykluczenia dobrej sceny zimowej: mniej danych o płytkim dnie; koszt zostawienia lodu: błędna linia brzegowa.
Wątpliwe daty są w configu oznaczone słowem „uncertain".

**7. Czy komunikaty RZGW dotyczą tego samego poziomu, co jezioro Nyskie?**
Zbiornik Nysa to Jezioro Nyskie; komunikaty podają pojemność, nie rzędną, a tabela pojemność↔rzędna pochodzi z mapy KŻ (źródło i warunki
w `data/reference/KZ_ZRODLO_I_WARUNKI.md`; autorzy zastrzegają „sposób amatorski"). Układ wysokościowy komunikatów jest niepewny
(`h_datum: unknown, prawdopodobnie KRON86`), co zapisujemy w `scenes.json`.

**8. Dlaczego nie sklejacie zdjęć z różnych satelitów tego samego dnia?**
Bo różne satelity mają inne czasy zdjęcia i drobne różnice kalibracji; jedna scena = jedno zdjęcie (R8), by nie mieszać dwóch momentów.
