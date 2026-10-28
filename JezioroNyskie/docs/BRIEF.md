> Zmiany stacku po 26.10.2026: frontend React + TanStack Query, patrz `docs/superpowers/specs/2026-10-26-mielizna-design.md` §3.

# Brief projektu: Satelitarna mapa płycizn Jeziora Nyskiego

> **Pełny tytuł:** System wyznaczania stref bezpiecznej żeglugi na zbiorniku retencyjnym o zmiennym poziomie wody na podstawie zobrazowań Sentinel-2, na przykładzie Jeziora Nyskiego
> **Przedmiot:** Analiza Danych Przestrzennych (MSc, Politechnika Opolska, Moodle 32247)
> **Autor:** Paweł Ostromecki
> **Wersja briefu:** 1.5 (2026-10-25; v1.5: poprawiony BBOX według obrysu jeziora z OSM, §5.1 zweryfikowane źródła danych z adresami i lukami, LiDAR w czterech epokach w §6.3; v1.4: §8.1 biblioteki rasterio i geopandas, §15 brief dla Claude Design, §16 makiety UI do implementacji, §6.6 porównanie z mapą KŻ Nysa, poprawione rzędne NPP / Max PP). To dokument wejściowy do implementacji: opisuje co, z czego i jak budujemy oraz kiedy uznajemy etap za skończony.

---

## 1. Problem i cel

Jezioro Nyskie to zbiornik retencyjny, którego poziom wody zmienia się o kilka metrów w ciągu roku (gospodarka przeciwpowodziowa RZGW Wrocław). Te same miejsca bywają raz żeglowne, raz płytkie, a raz całkiem suche. Dostępne mapy pokazują jedną linię brzegową i nie mówią, gdzie przy danym stanie wody jacht o danym zanurzeniu osiądzie na dnie.

**Cel:** aplikacja, która dla zadanego **poziomu wody** i **zanurzenia jachtu** pokazuje na mapie trzy strefy:

| Strefa | Warunek (szczegóły w §6.4) | Kolor |
|---|---|---|
| Bezpieczna | głębokość pewnie ≥ zanurzenie + zapas | zielony (paleta w §15.5) |
| Ryzykowna | niepewność modelu nie pozwala rozstrzygnąć | żółty + kreskowanie |
| Zbyt płytka / ląd | głębokość pewnie < zanurzenie | czerwony |

**Główna idea naukowa (waterline method):** każda bezchmurna scena Sentinel-2 to „zdjęcie” linii brzegowej przy pewnym poziomie wody. Linia brzegowa jest poziomicą dna na wysokości lustra wody. Wiele scen przy różnych poziomach daje zbiór poziomic, czyli model dna w strefie wahań zbiornika.

## 2. Wymagania przedmiotu (twarde)

- Architektura: **frontend + backend + model wnioskujący**.
- Ocena dotyczy głównie **wiedzy z analizy danych przestrzennych**: rastry, wektory, układy współrzędnych, interpolacja, ocena dokładności.
- Model ma być **prosty i wytłumaczalny**. Każdy krok autor musi umieć obronić ustnie, bo prace zrobione przez AI bez zrozumienia nie są zaliczane.
- Kod w **otwartym repozytorium** (link wymagany w zadaniu na Moodle; pierwszy termin: 17.10.2026).
- Bez QGIS w samym rozwiązaniu. QGIS wolno użyć do podglądu i kontroli wyników.

## 3. Zakres

### W zakresie
1. **Raster:** seria scen Sentinel-2 L2A z lat 2017–2026, wskaźniki wody, klasyfikacja woda/ląd.
2. **Wektor:** linia brzegowa z każdej sceny z przypisaną wysokością (m n.p.m.), przystanie i slipy z OpenStreetMap.
3. **Model:** (a) klasyfikator woda/ląd, (b) model dna z przedziałem niepewności, (c) przeliczenie stref.
4. **Aplikacja:** mapa, suwak poziomu wody, pole zanurzenia i zapasu, warstwy, legenda, info o punkcie.
5. **Ocena dokładności:** klasyfikacji i modelu dna (§7).
6. *(Opcjonalnie)* mapa zmian dna (zamulenie) z porównania dwóch okresów.

### Poza zakresem
- Głębokości w części **zawsze zalanej**. Tam podajemy tylko dolne ograniczenie głębokości (§6.3).
- Pojedyncze przeszkody podwodne (pnie, kamienie, ruiny), bo są poniżej rozdzielczości 10 m.
- Zastosowanie nawigacyjne. Aplikacja ma charakter naukowo-poglądowy, a disclaimer jest stale widoczny w UI.

## 4. Obszar i układy odniesienia

| Parametr | Wartość |
|---|---|
| Obszar | Jezioro Nyskie (zbiornik Nysa), rzeka Nysa Kłodzka, woj. opolskie |
| Obrys jeziora (OSM relation 2908769, bounds) | lon 17.2142–17.3063, lat 50.4345–50.4733 (ok. 6,6 × 4,2 km) |
| BBOX roboczy (WGS84, obrys + ok. 1 km zapasu) | **lon 17.20–17.32, lat 50.425–50.485** |
| BBOX roboczy (EPSG:2180) | E 372 000–381 000, N 285 500–292 500 |
| CRS obliczeń | **EPSG:2180** (PUWG 1992), metryczny, zgodny z danymi GUGiK |
| CRS sceny S2 | EPSG:32633 (UTM 33N), przeliczamy do 2180 |
| CRS frontendu | EPSG:3857 (web mercator), dane serwowane w 4326/3857 |
| Wysokości | m n.p.m., układ **PL-EVRF2007-NH** (NMT GUGiK). Sprawdzić, w jakim układzie podaje rzędne RZGW (możliwy Kronsztad 86); różnica rzędu kilkunastu cm |
| Rozdzielczość siatki modelu | 10 m (natywna B03/B08) |

**Znane punkty zaczepienia (z odpowiedzi na interpelację, wrzesień 2024):**
- 12.09.2024: poziom **194,70 m n.p.m.** przy pojemności **45,62 mln m³**.
- Próg zrzutu wyprzedzającego w instrukcji: **196,0 m n.p.m.**
- Pojemność przy NPP **65,69 mln m³**, przy Max PP **121,70 mln m³**.
- Rzędne NPP i Max PP: według tabeli pojemność ↔ rzędna z mapy KŻ Nysa (§6.6) **NPP ≈ 195,9 m n.p.m.** (65,69 mln m³), **Max PP ≈ 198,9 m n.p.m.** (121,70 mln m³). **Do potwierdzenia** w instrukcji gospodarowania wodą / operacie wodnoprawnym / RZGW. Wcześniejsze założenie z makiet (NPP 195,00, Max PP 195,70) było błędne.
- **Wcześniejszy BBOX (lon 17.25–17.45, lat 50.42–50.50) był błędny:** ucinał zachodnie ok. 40% jeziora i obejmował miasto Nysa na wschód od zapory. Poprawiony według obrysu z OSM (25.10.2026).
- Komunikat RZGW Wrocław (2025): przewyższenie 1,84–2,00 m ponad NPP odpowiada rzędnej 197,84–198,00 m n.p.m., więc **NPP = 196,00 m n.p.m.** Zgadza się to z tabelą KŻ (≈ 195,9 m) z dokładnością do 0,1 m.
- **Znany poziom 197,84–198,00 m n.p.m. od ok. 28.04 do 12.05.2025** (badania szczelności zapór, IMGW-PIB). Bezchmurna scena S2 z 28.04.2025 (zachmurzenie kafla 0,25%) i scena z 01.05.2025 (ok. 16%) dają linie brzegowe o znanej rzędnej (±8 cm). To najlepszy punkt kontrolny dla `h_t` (§6.3).
- Komunikaty podają pojemność przy NPP / Max PP: 66,3 / 122,1 mln m³ (2021) oraz 65,7 / 121,7 mln m³ (2024–2026). Prawdopodobnie zmieniła się instrukcja albo krzywa pojemności. Przy przeliczaniu V → h trzeba to uwzględnić (§13).
- Rozbieżność do wyjaśnienia (§13): interpelacja podaje 194,70 m przy 45,62 mln m³, a tabela KŻ daje 194,6 m przy 46,0 mln m³ i 194,7 m przy 47,5 mln m³ (różnica ok. 0,1–0,15 m albo ok. 1,9 mln m³).

## 5. Dane

| # | Dane | Źródło | Dostęp | Użycie | Status |
|---|---|---|---|---|---|
| D1 | Sentinel-2 L2A (B03, B04, B08, B11, SCL) | **Earth Search (AWS, główne)**, Planetary Computer (zapasowe), CDSE (awaryjne, wymaga konta) | `pystac-client` + `stackstac`/`odc-stac` | klasyfikacja woda/ląd | **pobranie potwierdzone** (§5.1) |
| D2 | NMT 1 m i chmura punktów LiDAR (LAZ) | GUGiK / Geoportal: arkusze `opendata.geoportal.gov.pl` ze skorowidzów WFS, NMT także przez WCS | `rasterio`, `laspy` | referencja dna w strefie odsłoniętej; kalibracja `h_t` (wariant A) | **potwierdzone:** 4 epoki skaningu nad jeziorem (§5.1); datę nalotu odczytujemy z GPS time punktów |
| D3 | Ortofotomapa | Geoportal WMS/WMTS (podkład), arkusze GeoTIFF ze skorowidza WFS | podgląd + ręczne etykiety | walidacja klasyfikacji, etykiety RF | **potwierdzone:** roczniki 2016, 2018–2025 nad jeziorem |
| D4 | Komunikaty o pojemności zbiornika Nysa (mln m³, dziennie) | RZGW Wrocław: **Wayback Machine** (11.2019–03.2024); Wody Polskie gov.pl: komunikaty krajowe (co najmniej 06.2025–dziś) i komunikaty z powodzi 2024 | scraping PDF (`pypdf`, tekst się wyciąga) | `h_t` z tabeli V ↔ h (wariant B) | **potwierdzone z lukami** (§5.1) |
| D5 | Przystanie, slipy, pomosty | OpenStreetMap (Overpass API: `leisure=marina`, `leisure=slipway`, `man_made=pier`) | HTTP | warstwa wektorowa w aplikacji | **potwierdzone:** 1 przystań i 2 slipy, plus obrys jeziora |
| D6 | Archiwalne mapy topo sprzed budowy zbiornika (1971) | Geoportal / CODGiK, WIG | ręcznie | opcjonalna referencja dla strefy zawsze zalanej | do sprawdzenia (opcjonalne) |
| D7 | Stan wody i przepływ IMGW, **stacja rzeczna NYSA (150170060)** | IMGW-PIB danepubliczne, archiwum dobowe ZIP/CSV od 1951 r. | HTTP | tylko kontekst (stany rzeki, nie poziom jeziora) | **potwierdzone; stacji zbiornika nie ma** |
| D8 | Mapa KŻ Nysa „Jezioro Nyskie (amatorska mapka dla wodniaków)”, aktualizacja 23.05.2023: rzędne dna (m n.p.m.), poziomice dna, przeszkody, tabela pojemność ↔ rzędna | Wiktor Wróblewski, KŻ Nysa; plik `docs/JN_2023_05_23__KZ.pdf` (obecnie `JN_2023_05_23__KZ (1).pdf`, zmienić nazwę) | raster 9867×4791 px bez warstwy tekstowej; georeferencja i digitalizacja (§6.6) | walidacja modelu dna i `h_t`; tabela V ↔ h do wariantu B | **amatorska, możliwe błędy; dno poniżej 192,5 m „orientacyjne”; użycie niekomercyjne zgodne z warunkami autora (źródło i warunki dołączone do kopii)** |

Wszystkie surowe dane trafiają do `data/raw/` (poza gitem, z `README` i skryptem pobierającym). Wyniki pośrednie do `data/processed/`.

### 5.1 Weryfikacja źródeł (25.10.2026)

Wszystkie źródła sprawdzono z komputera autora skryptami `scripts/check_sources.py` i `scripts/check_sources_2.py` (tylko biblioteka standardowa). Wyniki są w `data/raw/check/`: `s2_scenes_earthsearch.csv`, `wfs_skorowidze.json`, `rzgw_wayback_index.csv`, `osm_objects.json`, próbki NMT, ortofotomapy i komunikatów. Te pliki to punkt startowy pipeline'u.

**Sentinel-2 (D1)**

| Katalog | Adres | Dostęp | Wynik testu |
|---|---|---|---|
| Earth Search (główny) | `https://earth-search.aws.element84.com/v1`, kolekcja `sentinel-2-l2a`, assety `green`, `red`, `nir`, `swir16`, `scl` | bez konta, COG na S3 / HTTPS | wyszukiwanie OK, pobranie przez HTTP Range OK |
| Planetary Computer (zapasowy) | `https://planetarycomputer.microsoft.com/api/stac/v1`, assety `B03`, `B04`, `B08`, `B11`, `SCL` | bez konta, URL podpisany tokenem SAS (`planetary_computer.sign_inplace`) | wyszukiwanie OK, pobranie OK |
| CDSE (awaryjny) | `https://stac.dataspace.copernicus.eu/v1` | wyszukiwanie bez konta, pobranie wymaga konta i kluczy S3 | wyszukiwanie OK |

- Lista scen 2017–2026 z zachmurzeniem kafla < 60%: 1564 sceny na kaflach `33UXS` (804) i `33UXR` (760). Jezioro leży przy granicy kafli, więc dla każdej daty wybieramy kafel z pełnym pokryciem albo robimy mozaikę. Unikalnych dni z zachmurzeniem kafla < 20%: **324**. Na rok (wszystkie/<20%): 2017: 40/19, 2018: 171/82, 2019: 240/92, 2020: 233/120, 2021: 245/100, 2022: 112/53, 2023: 97/40, 2024: 102/40, 2025: 167/67, 2026: 157/75. Lista powstała dla starego BBOX, ale kafle obejmują jezioro, więc w pipeline wystarczy ją odświeżyć z nowym BBOX.
- **Pułapka (Planetary Computer, issue #513):** od 17.04.2026 pliki COG nie mają tagu `nodata=0`. Zawsze maskujemy DN = 0 sami, niezależnie od katalogu.

**LiDAR i NMT (D2)**

Skorowidze WFS (pola: `godlo`, `akt_rok`, `char_przestrz`, `blad_sr_wys`, `uklad_h`, `format`, `url_do_pobrania`, …):
- chmura punktów: `https://mapy.geoportal.gov.pl/wss/service/PZGIK/DanePomiaroweLidarEVRF2007/WFS/Skorowidze` i `.../DanePomiaroweLidarKRON86/WFS/Skorowidze`
- NMT: `https://mapy.geoportal.gov.pl/wss/service/PZGIK/NumerycznyModelTerenuEVRF2007/WFS/Skorowidze` i `.../NumerycznyModelTerenuKRON86/WFS/Skorowidze`
- NMT przez WCS 2.0.1: `https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModelFormatTIFF`, coverage `DTM_PL-KRON86-NH_TIFF` (GeoTIFF; wersja EVRF2007 tylko jako ASCII grid). Testowy wycinek pobrany poprawnie.

**Epoki skaningu laserowego nad jeziorem.** Arkusze odfiltrowano po godle do obrysu jeziora. Pokrycie podane dla odpowiedzi WFS uciętej do 200 obiektów, więc prawdziwe może być większe.

| Rok | Układ h | Gęstość | Błąd śr. wys. | Uwagi |
|---|---|---|---|---|
| 2011 | PL-KRON86-NH | 6–12 p/m² | 0,10–0,15 m | LAS; NMT 1 m pokrywa ~całe jezioro |
| 2017 | PL-KRON86-NH | 12 p/m² | 0,10 m | część jeziora |
| 2022 | PL-EVRF2007-NH | 12 p/m² | 0,10 m | część jeziora |
| 2024 | PL-EVRF2007-NH | 4–12 p/m² | 0,02–0,08 m | NMT 1 m pokrywa ~całe jezioro |

Pozostałe roczniki NMT (2010, 2016, 2018, 2019, 2021, 2023, 2025) pochodzą ze zdjęć lotniczych z błędem 0,5–1,5 m, więc do kalibracji `h_t` się nie nadają.

Wnioski:
- Skorowidz podaje tylko rok. **Dokładną datę nalotu odczytujemy z GPS time punktów LAZ** (`laspy`).
- **Poziom wody w dniu nalotu** to mediana wysokości punktów klasy 8 (woda) na jeziorze. Każda epoka daje więc parę (data, h) oraz NMT odsłoniętego dna przy tym poziomie, czyli maksymalnie cztery niezależne punkty kalibracji.
- Epoki 2011 i 2017 są w KRON86, a 2022 i 2024 w EVRF2007. Przed porównaniem trzeba je sprowadzić do EVRF2007 (różnica rzędu kilkunastu cm, przeliczenie przez model GUGiK).
- Zapytania WFS: BBOX filtruje słabo (zwraca też arkusze spoza obszaru), więc arkusze trzeba odfiltrować po geometrii albo godle i stronicować (`STARTINDEX`), bo odpowiedzi ucina limit `COUNT`.

**Ortofotomapa (D3)**
- Podkład do etykiet: WMTS `https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMTS/HighResolution`; WMS `.../ORTO/WMS/StandardResolution` (warstwa `Raster`, GetMap OK).
- Arkusze GeoTIFF ze skorowidza `.../PZGIK/ORTO/WFS/Skorowidze`. Roczniki nad jeziorem: 2016, 2018–2025 (piksel 0,05–0,5 m, RGB/CIR).
- Uwaga: data ortofotomapy to nie data sceny S2. Etykiety woda/ląd z ortofotomapy nadają się tylko do pikseli stabilnych (stale woda / stale ląd) albo do scen z tego samego dnia. Etykiety brzegowe oznaczamy na samych scenach S2.

**Pojemność zbiornika (D4)**

| Źródło | Okres | Format | Pokrycie dni S2 (chmury < 20%, ±1 dzień) |
|---|---|---|---|
| RZGW Wrocław, archiwum w Wayback Machine (`web.archive.org/cdx/...`, prefiks `wroclaw.wody.gov.pl/images/Pliki_do_pobrania/Sytuacja_Hydrologiczna_Raporty/`) | 04.11.2019 – 05.03.2024 (1035 dni) | PDF z warstwą tekstową, wiersz „Nysa / Nysa Kłodzka”: odpływ, dopływ, **pojemność aktualna**, poj. przy NPP i Max PP, rezerwa | 2019: 3/38, 2020: 42/44, 2021: 36/36, 2022: 20/30, 2023: 24/24, 2024: 3/27 → **128 z 324 dni** |
| Wody Polskie, komunikaty krajowe (`https://www.gov.pl/web/wody-polskie/sytuacja-hydrologiczna`, załączniki `gov.pl/attachment/<uuid>`) | co najmniej 06.2025 – dziś, prawie codziennie | PDF, tabela „Informacja o zbiornikach”, wiersz 43 „Nysa” | do policzenia; parser listy w `check_sources_2.py` zwrócił 0 i wymaga poprawki, a ręcznie potwierdzono 31.12.2025 i 22.10.2026 |
| Wody Polskie RZGW Wrocław, komunikaty z powodzi 2024 (gov.pl) | IX 2024 (np. 15.09 i 19.09) | PDF | pojedyncze dni |
| Komunikat o piętrzeniu w 2025 r. | 22.04 – 12.05.2025 | strona www | rzędna wprost (197,84–198,00 m) |

- Stare adresy `wroclaw.wody.gov.pl` zwracają 301 na gov.pl. Oryginałów nie ma, a kopie są tylko w Wayback Machine.
- **Luki:** 2017 – 10.2019 oraz 03.2024 – ok. 06.2025. Dla tych scen `h_t` daje wariant A (LiDAR), C (hipsometria) albo D (KŻ), oznaczony jako mniej pewny.
- Pobieranie z Wayback: `https://web.archive.org/web/<timestamp>id_/<original>`, grzecznie (np. 1 zapytanie/s), z cache w `data/raw/rzgw/`.

**OSM (D5).** Overpass `https://overpass-api.de/api/interpreter`. Znalezione obiekty: przystań żeglarska (node 2638165798, 50.4675 N, 17.2766 E), slipy (node 14099067081 i 2287182937) oraz obrys jeziora (relation 2908769). Pomosty (`man_made=pier`) nie były w zapytaniu testowym.

## 6. Metoda

Pipeline jest wsadowy (offline) i liczy model raz. Backend jedynie wczytuje gotowe rastry i przelicza strefy dla parametrów z UI.

```
S2 L2A ──► maska chmur (SCL) ──► MNDWI/NDWI ──► klasyfikacja woda/ląd ──► maska wody per scena
                                                                         │
NMT LiDAR ─────────────────────────────► poziom wody per scena (h_t) ◄───┘  (+ opcjonalnie RZGW)
                                                                         │
                         maski + h_t ──► model dna z_min / z_max per piksel ──► raster dna + niepewność
                                                                         │
                     UI: h, zanurzenie, zapas ──► backend: głębokość, strefy ──► GeoJSON / PNG tiles
```

### 6.1 Wybór i przygotowanie scen
- Filtr: obszar zbiornika, `eo:cloud_cover < 30%` dla całej sceny, potem **lokalnie**: odsetek pikseli SCL ∈ {3 cień, 8, 9 chmury, 10 cirrus} w buforze 500 m wokół zbiornika < 5%.
- Wycięcie do BBOX, reprojekcja do EPSG:2180, siatka 10 m (B11 z 20 m resampling bilinear).
- Wykluczyć sceny z pokrywą lodową (SCL = 11 snow/ice, miesiące XII–III do ręcznej weryfikacji).
- Oczekiwana liczba: kilkadziesiąt do ~150 użytecznych scen. Liczbę zapisujemy w raporcie.

### 6.2 Klasyfikator woda/ląd (model wnioskujący #1)
Wskaźniki (uwaga na poprawne pasma, bo w notatkach z 11.10 oba wzory miały B08):
- **NDWI** (McFeeters) = (B03 − B08) / (B03 + B08)
- **MNDWI** (Xu) = (B03 − B11) / (B03 + B11), lepiej tłumi zabudowę i mokrą glebę, ale ma 20 m.

Wariant bazowy (wytłumaczalny): **próg Otsu liczony per scena** na histogramie MNDWI w buforze wokół zbiornika. Próg zapisujemy w metadanych sceny.
Wariant porównawczy: **Random Forest** (`scikit-learn`, ~50 drzew) na cechach [B03, B04, B08, B11, NDWI, MNDWI], uczony na ręcznie oznaczonych punktach z ortofotomapy (≥ 300 punktów, zbalansowane klasy).
Postprocessing: usunięcie obiektów wodnych < 5 pikseli niepołączonych ze zbiornikiem (analiza spójności, `scipy.ndimage.label`), zostawiamy tylko największy komponent i jego przyległości.

Wynik: maska `water_t` (0/1) dla każdej sceny `t` + linia brzegowa jako wektor (`rasterio.features.shapes` → granica poligonu, wygładzenie, zapis do GeoPackage z atrybutami `date`, `h_t`, `threshold`, `area_km2`).

### 6.3 Poziom wody w dniu sceny, czyli kluczowe ryzyko
Potrzebujemy `h_t` w m n.p.m. dla każdej sceny. Warianty w kolejności preferencji:

**A. Kalibracja z NMT (preferowany, niezależny od RZGW).**
Dla linii brzegowej sceny `t` próbkujemy NMT w pikselach brzegowych, które w NMT są **lądem** (powyżej poziomu wody w dniu nalotu LiDAR). `h_t` = mediana tych wysokości (odporna na błędy klasyfikacji). Działa dla scen, w których poziom ≥ poziom w dniu nalotu.
Mamy cztery epoki skaningu (2011, 2017, 2022, 2024; §5.1). Dla każdej odczytujemy datę nalotu z GPS time i poziom wody z punktów klasy 8. Najniżej położona epoka wyznacza dolną granicę wariantu A. Jako kontrolę bierzemy też okno 28.04–12.05.2025 ze znaną rzędną 197,84–198,00 m (§4).

**B. Krzywa pojemność → poziom.**
Dla scen poniżej poziomu z NMT: z komunikatów RZGW znamy pojemność `V_t`, a z klasyfikacji powierzchnię `A_t`. Skoro dV = A·dh, to
`h(V) = h₀ + ∫_{V₀}^{V} dV / A(V)`, z punktem zaczepienia (194,70 m ↔ 45,62 mln m³) lub punktem z wariantu A. Krzywą A(V) wygładzamy (spline monotoniczny).
Gotową krzywą V ↔ h daje tabela z mapy KŻ (66 wierszy: od 18,0 mln m³ ↔ 192,4 m do 122,0 mln m³ ↔ 198,9 m, krok 0,1 m w rzędnej), interpolowana liniowo. Używamy jej w pierwszej kolejności, a krzywą całkową jako kontrolę. Zgodność z interpelacją jest otwartą kwestią (§13).

**C. Hipsometria (awaryjny).** Zależność powierzchnia ↔ poziom dopasowana na scenach z wariantu A i ekstrapolowana w dół. Wynik zawsze oznaczamy jako mniej pewny.

**D. Dopasowanie do poziomic z mapy KŻ (kontrola, §6.6).** Dla sceny szukamy rzędnej, przy której poziomica dna z mapy KŻ najlepiej pokrywa się z linią brzegową sceny (minimum średniej odległości). Używane jako niezależna kontrola wariantów A i B, a nie jako główne źródło.

Każda scena dostaje `h_t`, `h_method ∈ {A,B,C,D}` i `h_sigma` (rozrzut wysokości wzdłuż brzegu w wariancie A).

### 6.4 Model dna (model wnioskujący #2)
**Podstawowy: przedziały zalania per piksel.** Dla każdego piksela `p` z serii scen:
- `z_max(p)` = min{ h_t : p jest wodą w scenie t }, bo dno leży niżej niż każde lustro, które je zalało
- `z_min(p)` = max{ h_t : p jest lądem w scenie t }, bo dno leży wyżej niż każde lustro, które go nie zalało
- estymata `z(p)` = (z_min + z_max) / 2, niepewność = (z_max − z_min) / 2 (+ `h_sigma`)

Sprzeczności (z_min > z_max, wynikające z błędów klasyfikacji/fal/roślinności) rozwiązujemy przez odrzucenie skrajnych 5% scen dla piksela albo dopasowanie progu minimalizującego liczbę błędnych obserwacji. Liczbę takich pikseli raportujemy.
Piksele **zawsze zalane**: `z_max = h_min_obs`, `z_min` nieznane, więc głębokość ≥ h − h_min_obs (dolne ograniczenie).
Piksele **zawsze suche**: poza modelem (ląd).

**Porównawczy: interpolacja poziomic.** Linie brzegowe z `h_t` traktujemy jako poziomice i interpolujemy powierzchnię (TIN, `scipy.interpolate.griddata` linear, oraz IDW). Pokazuje klasyczne podejście GIS i pozwala porównać metody.

**Strefy żeglugi** dla parametrów h, zanurzenie `d`, zapas `m` (domyślnie 0,3 m):
- głębokość min `D_lo = h − z_max`, max `D_hi = h − z_min`
- **bezpieczna:** `D_lo ≥ d + m`
- **zbyt płytka:** `D_hi < d` lub piksel suchy przy h (h < z_min)
- **ryzykowna:** pozostałe

Ta reguła jest w pełni wytłumaczalna i uczciwie pokazuje niepewność modelu.

### 6.5 Opcjonalnie: zmiany dna
Model z dwóch okresów (np. 2017–2020 vs 2023–2026), różnica `z`, istotna tylko tam, gdzie |Δz| > suma niepewności. Uwaga na powódź z września 2024, bo mogła przemodelować dno.

### 6.6 Porównanie z mapą KŻ Nysa (referencja dla dna pod wodą)

**Czy to ma sens: tak, jako walidacja i kontrola, nie jako dane wejściowe modelu.** Mapa jest amatorska, o nieznanej dokładności, więc nie uczymy na niej modelu, tylko sprawdzamy, czy model ze zdjęć satelitarnych odtwarza to, co ona pokazuje. To daje referencję także poniżej linii wody, której LiDAR nie widzi.

**Źródło i zawartość** (D8): rzędne dna w m n.p.m. (niebieskie poniżej 195,0, czarne powyżej), poziomice dna (część „orientacyjna”, przerywana), przeszkody z rzędną wierzchołka, tabela pojemność ↔ rzędna, skala schodków na klubowym slipie. Układ WGS84, siatka w stopniach i minutach. Wartości są **rzędnymi**, więc nie potrzebujemy poziomu wody z dnia pomiaru, żeby je porównać z modelem.

**Trzy zastosowania** (nie mieszać ich w jednym eksperymencie, żeby uniknąć przecieku):
1. **Walidacja modelu dna:** rzędne punktowe z mapy vs `z(p)` z modelu.
2. **Odtworzenie poziomic:** czy poziomice dna z modelu (np. 192,5 i 195,0 m) pokrywają się z poziomicami KŻ.
3. **Kontrola `h_t` (wariant D):** zgodność z wariantami A i B.

**Granice porównania:**
- Wspólny zakres to rzędne od ok. **192,5 m** do najwyższego poziomu obserwowanego w scenach. Poniżej 192,5 m autor oznacza dno jako **orientacyjne** (niewystarczająca liczba danych), więc te punkty raportujemy osobno i nie wliczamy do głównych metryk.
- **Rejon eksploatacji kruszywa** (środek i wschód jeziora, zmienne głębokości, akweny systematycznie zasypywane) idzie do **maski wykluczeń**. Dno zmienia się tam w czasie, więc założenie stałego dna nie obowiązuje.
- Mapa pochodzi z 2023 r., więc porównujemy ją z modelem zbudowanym ze scen **do sierpnia 2024** (przed powodzią), a nie z całą serią do 2026 r.
- Niepewność położenia (georeferencja) jest rzędu piksela 10 m. Porównania agregujemy (komórki 30–50 m, odległość między poziomicami), a nie robimy ich piksel do piksela.
- Nie wiemy, jak powstały rzędne (sondowanie, przeliczenie wg poziomu wody w dniu pomiaru), więc możliwy jest błąd systematyczny. Zawsze raportujemy **bias**.

**Kroki:**
- **K1. Georeferencja.**
  - Obraz wyciągamy z PDF (`pdfimages -j`), wybieramy ≥ 12 przecięć siatki współrzędnych (opisy na krawędziach) rozłożonych po całej mapie.
  - Dopasowujemy transformację (afiniczną, ewentualnie wielomian 2. stopnia lub TPS) w GDAL / `rasterio` i przeliczamy do EPSG:2180.
  - Oceniamy na punktach kontrolnych **nieużytych** do dopasowania, a dodatkowo na zaporze i linii brzegowej OSM.
  - Robocze progi: RMSE ≤ 5 m dobry, ≤ 10 m akceptowalny (wtedy tylko porównania zagregowane).
- **K2. Punkty rzędnych.**
  - OCR (`tesseract`, wzorzec `\.?\d{3},\d`), pozycja punktu to kropka przed liczbą. Kolor (niebieski / czarny) służy jako kontrola spójności z rzędną 195,0.
  - Ręczna kontrola próby ≥ 200 punktów (odsetek błędów OCR). Robocze kryterium: błąd ≤ 10%, inaczej korekta ręczna lub dane od autora.
  - Zapis: `kz_spot.gpkg` (`z`, `kolor`, `qc`).
  - Alternatywa: dane cyfrowe od autora (§13), co zastępuje K1–K2.
- **K3. Poziomice.** Wektoryzacja wybranych (192,5 i 195,0 m) z koloru linii z ręczną kontrolą, bez linii przerywanych („orientacyjnych”). Zapis: `kz_contours.gpkg`.
- **K4. Tabela pojemność ↔ rzędna.** Przepisanie do `data/reference/kz_pojemnosc_rzedna.csv` (66 wierszy) z podaniem źródła; używana w wariancie B.
- **K5. Porównania:**
  - **Punkty:** `z(p)` w komórce punktu vs rzędna KŻ. Metryki: MAE, RMSE, bias, odsetek punktów w `[z_min, z_max]`, osobno dla przedziałów rzędnych 192,5–195,0, 195,0–NPP i powyżej NPP, bez rejonu żwirowni.
  - **Poziomice:** poziomica modelu vs poziomica KŻ na tej samej rzędnej. Metryki: średnia odległość i odległość Hausdorffa (m), jak dla linii brzegowej w §7.
  - **Wariant D dla `h_t`:** zgodność z A i B. Robocze kryterium: różnica ≤ 0,2 m dla większości scen.
  - **Nakładka wizualna:** zgeoreferencowana mapa KŻ jako półprzezroczysta warstwa pod strefami i poziomicami w notebooku (kontrola jakości). W aplikacji możliwa, jeśli przy warstwie widnieje źródło i warunki autora.

**Unikanie przecieku:** jeśli poziomice KŻ służą do wariantu D, to do walidacji dna (punkty) używamy wyłącznie punktów spoza bloków 500 m wokół tych poziomic, albo robimy najpierw walidację punktową z `h_t` z wariantów A/B, a wariant D traktujemy jako kontrolę zgodności.

**Kryteria go / no-go (robocze):**
- po K1: RMSE georeferencji > 10 m → tylko porównania zagregowane (poziomice, komórki 50 m);
- po K2: błąd OCR > 10% → korekta ręczna albo dane od autora;
- po K5: |bias| > 0,5 m → najpierw ustalamy przyczynę (układ wysokości, dno z 2023 r., sposób pomiaru), dopiero potem wnioski.

**Licencja i publikacja.** Warunki autora: mapa jest bezpłatna i niekomercyjna, dane mogą zawierać błędy, ryzyko ponosi użytkownik, a każda kopia musi zawierać te warunki. Projekt jest naukowy i niekomercyjny (bez przychodów, reklam i płatnych funkcji), więc mieści się w tych warunkach. Przy PDF-ie, zdigitalizowanych punktach i tabeli w repozytorium oraz przy ewentualnej nakładce w aplikacji podajemy źródło (Wiktor Wróblewski, KŻ Nysa, aktualizacja 23.05.2023) i dołączamy treść warunków. Poinformowanie autora o użyciu jest uprzejmością i dobrą okazją, żeby poprosić o dane cyfrowe, ale nie blokuje prac.

## 7. Ocena dokładności

| Co | Referencja | Metryki |
|---|---|---|
| Klasyfikacja woda/ląd | ≥ 300 punktów oznaczonych na ortofotomapie (data możliwie bliska scenie) + kilka scen ręcznie | macierz pomyłek, OA, Kappa, F1 dla wody; porównanie Otsu vs RF |
| Linia brzegowa | linie ręcznie zdigitalizowane na 2–3 scenach | średnia odległość / odległość Hausdorffa (m) |
| Poziom `h_t` | dni z poziomem z RZGW/IMGW (jeśli dostępne), punkt 12.09.2024 | MAE, RMSE (m) |
| Model dna | **NMT LiDAR w strefie odsłoniętej w dniu nalotu, ale tylko piksele NIE użyte do kalibracji `h_t`** (podział przestrzenny na bloki, np. 500 m, żeby uniknąć przecieku) | MAE, RMSE, bias (m); % pikseli, gdzie NMT ∈ [z_min, z_max] |
| Metody dna | podstawowa vs interpolacja poziomic | j.w. + mapa różnic |
| Model dna vs mapa KŻ (§6.6) | punkty rzędnych dna z mapy KŻ (2023), rzędne ≥ 192,5 m, bez rejonu żwirowni; model zbudowany ze scen do sierpnia 2024 | MAE, RMSE, bias (m); % punktów w `[z_min, z_max]`; osobno przedziały rzędnych |
| Poziomice modelu vs poziomice KŻ | poziomice KŻ na rzędnych 192,5 i 195,0 m | średnia odległość, Hausdorff (m) |
| `h_t` wariant D vs A / B | dopasowanie poziomic KŻ do linii brzegowych scen | różnica (m), odsetek scen w ±0,2 m |

Wyniki trafiają do `docs/raport.md` z wykresami (histogram błędów, wykres poziom–powierzchnia, mapa niepewności).

## 8. Architektura i stack

Proponowany podział: **Python dla danych i modelu** (najlepszy ekosystem geo), **Angular dla frontu** (najmocniejsza strona autora).

| Warstwa | Technologia | Zadanie |
|---|---|---|
| Pipeline | Python 3.12, `pystac-client`, `stackstac`/`odc-stac`, `xarray`, `rasterio`, `rioxarray`, `geopandas`, `shapely`, `scikit-image` (Otsu), `scikit-learn`, `scipy` | pobranie, klasyfikacja, `h_t`, model dna, ocena |
| Wyniki | GeoTIFF (COG): `bottom_z.tif`, `bottom_zmin.tif`, `bottom_zmax.tif`, `obs_count.tif`; GeoPackage: `shorelines.gpkg`, `marinas.gpkg`; `scenes.json` | kontrakt pipeline ↔ backend |
| Backend | **FastAPI** (Python, bo te same biblioteki co pipeline, a przeliczanie stref to operacje numpy na rastrze ~0,5 mln pikseli) | API, przeliczanie stref, wektoryzacja |
| Frontend | **Angular** + **MapLibre GL JS** (lub OpenLayers) | mapa, kontrolki, warstwy |
| Uruchomienie | `docker compose` (backend + frontend), `Makefile` / `uv` dla pipeline | powtarzalność |

Alternatywa: backend w NestJS serwujący wyłącznie wcześniej przeliczone warstwy dla siatki (h, d). Odrzucona jako domyślna, bo przenosi „model” poza backend i komplikuje dwujęzyczny stack.

### 8.1 Biblioteki geoprzestrzenne (decyzja: używamy rasterio i geopandas)

W projekcie świadomie korzystamy z **rasterio** (dane rastrowe) i **geopandas** (dane wektorowe). To one pokazują warsztat analizy danych przestrzennych oceniany na przedmiocie. Wiele kroków to przejścia raster ↔ wektor.

- **rasterio**: wszystko, co jest siatką pikseli (sceny, maski, NMT, model dna).
- **geopandas**: wszystko, co jest geometrią z atrybutami (linie brzegowe, przystanie, strefy, punkty walidacyjne).
- **rioxarray / xarray**: seria scen jako kostka `(czas, y, x)`; korzysta z rasterio pod spodem, więc liczy się do tej samej warstwy.
- **stackstac / odc-stac**: pobranie kostki z katalogu STAC.
- **shapely**: geometrie pod geopandas, używana bezpośrednio sporadycznie.

| Etap | rasterio | geopandas |
|---|---|---|
| 01–02 pobranie S2 i NMT | `rasterio.open` z `window`, `rasterio.mask.mask` (wycięcie do obszaru zbiornika bez wczytywania całych arkuszy) | poligon obszaru/bufora zbiornika jako maska wycięcia |
| 01 przygotowanie scen | `rasterio.warp.reproject`, `calculate_default_transform`: UTM 33N → EPSG:2180, B11 20 m → 10 m (pasma: bilinear; maski i SCL: nearest) | — |
| 03 OSM | — | Overpass → GeoDataFrame przystani/slipów → `to_file` (GPKG) |
| 04 klasyfikacja | `rasterio.features.rasterize` (bufor zbiornika jako maska do progu Otsu); `rasterio.sample` (wartości pasm w punktach uczących RF) | punkty uczące/testowe z ortofotomapy (GeoJSON w repo) |
| 05 linie brzegowe | `rasterio.features.shapes`: maska woda/ląd → poligony | GeoDataFrame linii z atrybutami `date`, `h_t`, `threshold`, `area_km2`; `.simplify`, `.area`, `.length`; zapis `shorelines.gpkg` |
| 06 poziomy wody | `rasterio.sample` / `dataset.index`: NMT w pikselach linii brzegowej (wariant A) | `.area` lustra wody per scena → zależność powierzchnia–poziom (wariant B/C) |
| 07 model dna | zapis `bottom_z/zmin/zmax/obs_count.tif` jako COG z poprawnym `transform`, `crs`, `nodata` | linie brzegowe jako poziomice do interpolacji porównawczej (TIN/IDW) |
| 08 ocena | `rasterio.sample` modelu i NMT w punktach kontrolnych; `rasterize` bloków walidacyjnych | siatka bloków 500 m do podziału przestrzennego, `sjoin` punktów z blokami, macierz pomyłek |
| Backend `/api/zones` | odczyt rastrów modelu, `features.shapes` na rastrze stref | GeoDataFrame stref → `.simplify` → `to_crs(4326)` → GeoJSON |
| Backend `/api/point`, `/api/marinas` | `dataset.index` + odczyt piksela | `to_crs`, opcjonalnie `sjoin` przystani ze strefami (które są płytkie przy danym h) |

Zasada: obliczenia w **EPSG:2180** (metry, poprawne `.area`/`.buffer`), konwersja do EPSG:4326 dopiero przy wysyłce do frontendu.

### 8.2 API (szkic)

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/api/meta` | zakres h (min/max obserwowany), domyślne wartości, BBOX, CRS, liczba scen, okres |
| GET | `/api/zones?h=195.2&draft=1.2&margin=0.3&format=geojson` | strefy jako GeoJSON (poligony 3 klas, uproszczone) + `stats`: udział powierzchni każdej strefy w akwenie (do podsumowania w legendzie, §16) |
| GET | `/api/zones/tiles/{z}/{x}/{y}.png?h=&draft=&margin=` | *(opcjonalnie)* strefy jako kafle rastrowe |
| GET | `/api/point?lon=&lat=&h=` | dla punktu: z, z_min, z_max, głębokość min/max, liczba obserwacji, strefa |
| GET | `/api/shorelines?date=` | linia brzegowa z wybranej sceny |
| GET | `/api/scenes` | lista scen: data, h_t, metoda, powierzchnia, próg, zachmurzenie lokalne (%) |
| GET | `/api/marinas` | przystanie/slipy z OSM |
| GET | `/api/capacity-to-level?v=` | przeliczenie pojemności z komunikatu RZGW na poziom (jeśli wariant B) |

Walidacja parametrów: `h` w zakresie obserwowanym ± 0,5 m (poza zakresem zwracamy ostrzeżenie), `draft` 0,1–3,0 m, `margin` 0–1 m.

### 8.3 Frontend (widoki i interakcje)

> Wiążący wygląd i zachowanie UI: **§16** (makiety z Claude Design). Poniższa lista to skrót.
- Mapa bazowa (OSM / ortofotomapa WMS Geoportalu jako przełączana warstwa).
- Panel: suwak **poziomu wody** (m n.p.m.) z opcją wpisania **pojemności z komunikatu RZGW**; pole **zanurzenie**; pole **zapas**; presety jachtów (np. Omega 0,9 m, Sasanka 660 z mieczem podniesionym/opuszczonym; wartości do uzupełnienia).
- Warstwy: strefy (3 kolory, półprzezroczyste), model dna (hipsometria), niepewność, linie brzegowe historyczne (wybór daty), przystanie.
- Klik w mapę wywołuje `/api/point`, a popup pokazuje głębokość z przedziałem.
- Legenda, stały disclaimer „nie do nawigacji”, sekcja „o metodzie” z linkiem do raportu.
- Debounce suwaka (~250 ms), cache odpowiedzi po (h, d, m) zaokrąglonych do 0,05 m.

## 9. Struktura repozytorium

```
jezioro-nyskie/
├── README.md                 # cel, szybki start, zrzut ekranu, link do raportu
├── docs/
│   ├── BRIEF.md              # ten dokument
│   ├── raport.md             # metoda + ocena dokładności (do oddania)
│   ├── design/               # makiety z Claude Design (*.dc.html), referencja do §16
│   └── img/
├── data/                     # poza gitem (poza README i małymi plikami referencyjnymi)
│   ├── raw/  processed/  reference/
├── pipeline/
│   ├── pyproject.toml
│   ├── config.yaml           # BBOX, CRS, okres, progi chmur, ścieżki
│   ├── 01_fetch_s2.py
│   ├── 02_fetch_nmt.py
│   ├── 03_fetch_osm.py
│   ├── 04_classify.py        # Otsu + RF
│   ├── 05_shorelines.py
│   ├── 06_water_levels.py    # warianty A/B/C/D
│   ├── 07_bottom_model.py
│   ├── 08_evaluate.py
│   ├── 09_kz_digitize.py     # georeferencja i digitalizacja mapy KŻ (K1–K4, §6.6)
│   ├── 10_kz_compare.py      # porównania z mapą KŻ (K5)
│   └── notebooks/            # eksploracja i wykresy do raportu
├── backend/                  # FastAPI
│   ├── app/main.py  app/zones.py  app/models.py
│   └── tests/
├── frontend/                 # Angular + MapLibre
└── docker-compose.yml
```

## 10. Plan prac (kamienie milowe)

| # | Etap | Rezultat | Kryterium ukończenia |
|---|---|---|---|
| M0 | Szkielet repo | publiczne repo, struktura, README, config | repo dostępne, link na Moodle |
| M1 | Dane | skrypty 01–03, lista scen | ≥ 30 użytecznych scen w różnych porach roku; NMT i OSM pobrane; **ustalona data nalotu LiDAR** |
| M1b | Mapa KŻ: georeferencja i digitalizacja (K1–K4) | `kz_spot.gpkg`, `kz_contours.gpkg`, tabela V ↔ h; **równolegle z M1–M2, nie wymaga danych satelitarnych** | RMSE georeferencji ≤ 10 m; błąd OCR ≤ 10% na próbie ≥ 200 punktów; źródło i warunki autora dołączone do plików |
| M2 | Klasyfikacja | maski + linie brzegowe | wizualna kontrola 5 scen na ortofoto; OA ≥ 95% na punktach testowych |
| M3 | Poziomy wody | `scenes.json` z `h_t` | rozrzut `h_sigma` < 0,3 m dla wariantu A; spójność z punktem 194,70 m |
| M4 | Model dna | rastry z, z_min, z_max | raport sprzeczności; RMSE vs NMT (holdout) policzone |
| M4b | Porównanie z mapą KŻ (K5) | metryki z §7, nakładki, wniosek o sensie | punkty i poziomice policzone; bias raportowany; decyzja go / no-go z §6.6 |
| M5 | Backend | API z §8.2 + testy | `/api/zones` < 1 s; testy jednostkowe reguły stref |
| M6 | Frontend | mapa z kontrolkami i warstwami | pełny scenariusz: zmiana h i zanurzenia zmienia strefy; popup punktu |
| M7 | Raport i obrona | `docs/raport.md`, zrzuty, docker compose | uruchomienie jednym poleceniem; autor potrafi wyjaśnić każdy krok |
| M8 | *(opcja)* zmiany dna | mapa Δz | tylko zmiany > niepewność |

Kolejność krytyczna: **M1 → M3**. Jeśli NMT nie pozwala skalibrować poziomów, a archiwum RZGW jest niedostępne, model dna ma tylko względne wysokości i trzeba to wcześnie wiedzieć (§12).

## 11. Kryteria akceptacji całości

1. Użytkownik ustawia poziom wody i zanurzenie, a mapa w ≤ 2 s pokazuje 3 strefy zgodne z regułą z §6.4.
2. Kliknięcie punktu zwraca głębokość z przedziałem niepewności i liczbą obserwacji.
3. Raport zawiera: opis danych i CRS, uzasadnienie wskaźnika i progu, metodę `h_t`, model dna, metryki z §7, ograniczenia.
4. Pipeline jest odtwarzalny od zera skryptami (bez ręcznych kroków poza etykietowaniem punktów walidacyjnych, które są w repo).
5. Kod publiczny, licencja (np. MIT), dane źródłowe opisane z licencjami (Copernicus, GUGiK, OSM ODbL z atrybucją na mapie).

## 12. Ryzyka i plan B

| Ryzyko | Wpływ | Mitigacja |
|---|---|---|
| Brak poziomu wody dla części scen: archiwum RZGW (Wayback) obejmuje 11.2019–03.2024, gov.pl co najmniej od 06.2025, czyli 128 z 324 dni S2 ma komunikat | średni (wcześniej: wysoki) | wariant A z 4 epok LiDAR + wariant C (hipsometria) dla luk; w ostateczności model **względny** + suwak w metrach względnych |
| Wayback Machine niedostępny lub ograniczający ruch | niski | jednorazowe pobranie z cache w `data/raw/rzgw/`; przetworzona tabela `h_t` wersjonowana w repo |
| Chmury/lód ograniczają liczbę scen | średni | szerszy zakres lat, lokalna maska chmur zamiast globalnego progu |
| Błędy klasyfikacji przy brzegu (roślinność, mokre błoto, mieszane piksele 10 m) | średni | MNDWI, odrzucanie skrajnych obserwacji, bufor niepewności ±1 piksel w raporcie |
| Fale/wiatr, dynamika poziomu w ciągu dnia | niski | `h_sigma` w niepewności |
| Zmiana dna po powodzi 2024 | średni | osobne modele przed/po; ewentualnie M8 |
| Mapa KŻ amatorska, nieznana dokładność; dno poniżej 192,5 m orientacyjne; rejon żwirowni zmienny | średni | używamy jako walidacji, nie danych wejściowych; maska wykluczeń; raportujemy bias; wnioski ostrożne |
| Warunki użycia mapy KŻ (niekomercyjna, kopie z warunkami) | niski | projekt naukowy i niekomercyjny, więc zgodny; w repo i w aplikacji podajemy źródło i warunki autora; zapytać autora o dane cyfrowe |
| Zbyt złożony model do obrony | wysoki (wymóg przedmiotu) | wariant podstawowy = progi + przedziały min/max; RF i interpolacja tylko jako porównanie |

## 13. Otwarte kwestie do ustalenia

- [ ] Rzędne NPP i Max PP w m n.p.m. (wg tabeli KŻ: NPP ≈ 195,9, Max PP ≈ 198,9) i układ wysokości stosowany przez RZGW. Potwierdzić w instrukcji gospodarowania wodą / operacie / RZGW. *Stan: nierozstrzygnięte, wskazówki w [raporcie](raport.md) §3.4.*
- [ ] Rozbieżność interpelacja vs tabela KŻ (194,70 m przy 45,62 mln m³ vs ok. 194,57 m według tabeli): zamulenie zbiornika, inny układ wysokości czy dokładność tabeli? *Stan: nierozstrzygnięte, [raport](raport.md) §3.4–3.5.*
- [ ] Kontakt z autorem mapy KŻ (Wiktor Wróblewski, KŻ Nysa): dane cyfrowe punktów, źródło tabeli pojemność ↔ rzędna, sposób pomiaru rzędnych; przy okazji poinformować o użyciu w projekcie naukowym (niekomercyjnym). *Stan: digitalizacja K1–K3 zamiast danych od autora, [raport](raport.md) §6.*
- [ ] Zakres rzędnych objęty seriami scen (najniższy zaobserwowany poziom) wobec zakresu wiarygodnych danych mapy KŻ (≥ 192,5 m). *Wynik: [raport](raport.md) §4 i §6.4.*
- [x] Źródła danych zweryfikowane pobraniem z komputera autora (25.10.2026, §5.1).
- [x] BBOX poprawiony według obrysu z OSM (§4).
- [x] Archiwum komunikatów RZGW: Wayback 11.2019–03.2024 plus gov.pl co najmniej od 06.2025 (§5.1). IMGW ma tylko stację rzeczną.
- [x] Data nalotu LiDAR dla każdej epoki (GPS time z LAZ) i poziom wody tego dnia (punkty klasy 8). Zrobić w M1. *Zrobione (klasa wody to 9): [raport](raport.md) §3.2, `data/processed/lidar/epochs.csv`.*
- [ ] Jak daleko wstecz sięga lista komunikatów krajowych gov.pl (czy obejmuje 03.2024–06.2025)? *Wynik: [raport](raport.md) §1.1.*
- [ ] Zmiana pojemności przy NPP / Max PP między 2021 (66,3 / 122,1) a 2024+ (65,7 / 121,7): która krzywa V ↔ h obowiązywała kiedy? *Stan: nierozstrzygnięte, [raport](raport.md) §3.1.*
- [x] Przeliczenie epok KRON86 (2011, 2017) do EVRF2007. *Zrobione siatkami quasi-geoidy GUGiK (+0,199 m): [raport](raport.md) §1.2.*
- [ ] Ostateczny termin oddania projektu i forma obrony (pierwszy termin, link do repo, minął 17.10.2026).
- [ ] Zanurzenia przykładowych jachtów do presetów.
- [ ] Wybór MapLibre vs OpenLayers (MapLibre prostszy dla GeoJSON + kafli; OpenLayers lepszy przy WMS/WCS i niestandardowych CRS).

## 14. Słownik

- **NPP**: normalny poziom piętrzenia; **Max PP**: maksymalny poziom piętrzenia.
- **NMT**: numeryczny model terenu (bez budynków i roślinności).
- **Waterline method**: rekonstrukcja dna z linii brzegowych zarejestrowanych przy różnych poziomach wody.
- **SCL**: Scene Classification Layer w produktach Sentinel-2 L2A.
- **COG**: Cloud Optimized GeoTIFF.

---

## 15. Brief dla Claude Design (UI)

> Sekcja samodzielna: można ją wkleić do Claude Design bez reszty dokumentu. Cel: makiety ekranów do implementacji w Angularze z MapLibre GL (§8.3).

### 15.1 Produkt w jednym zdaniu
Mapowa aplikacja webowa, która pokazuje żeglarzowi, gdzie na Jeziorze Nyskim jego jacht o danym zanurzeniu przepłynie bezpiecznie przy danym poziomie wody, a gdzie grozi mu osiadnięcie na mieliźnie.

### 15.2 Użytkownicy i sytuacje
- **Żeglarz przed wypłynięciem**, w domu (desktop) albo na pomoście (telefon, słońce, jedna ręka). Chce w 10 sekund wiedzieć, którędy płynąć. Zna swoje zanurzenie i może znać pojemność zbiornika z komunikatu RZGW, ale zwykle nie zna rzędnej w m n.p.m.
- **Prowadzący przedmiot / komisja**. Chce zobaczyć metodę: skąd są dane, jak pewny jest model, jak wyglądają historyczne linie brzegowe.

### 15.3 Ekrany do zaprojektowania
1. **Mapa główna (desktop)**: pełnoekranowa mapa jeziora z panelem parametrów (lewy, ~360 px) i legendą.
2. **Mapa główna (mobile, 390 px)**: mapa + dolny wysuwany panel (bottom sheet) z parametrami, w stanie zwiniętym widać tylko: zanurzenie, poziom, mini-legendę.
3. **Popup punktu**: po kliknięciu w wodę. Pokazuje:
   - głębokość jako przedział, np. „1,4–1,9 m”, z oceną strefy dla wybranego jachtu;
   - wysokość dna (m n.p.m.) i liczbę obserwacji satelitarnych.
   Wariant dla części zawsze zalanej: „głębiej niż 3,2 m (poniżej najniższego zaobserwowanego stanu)”.
4. **Historia linii brzegowych**: oś czasu / lista scen (data, poziom, powierzchnia) i mapa z wybraną linią brzegową; opcja nałożenia kilku linii (kolor wg poziomu).
5. **O metodzie**: krótki opis kroków (satelita → woda/ląd → linie brzegowe → model dna → strefy), wykres poziom–powierzchnia, metryki dokładności, źródła danych z licencjami, disclaimer.

### 15.4 Kontrolki (panel parametrów)
- **Zanurzenie jachtu**, główne pole:
  - liczba w metrach, krok 0,05, zakres 0,1–3,0;
  - presety jako chipy: np. „Omega 0,9 m”, „Sasanka 660 miecz w górze / w dole”, „własny”.
- **Zapas bezpieczeństwa**: domyślnie 0,3 m, schowany pod „ustawienia zaawansowane”.
- **Poziom wody**: suwak w m n.p.m. z zaznaczonymi na torze punktami: najniższy zaobserwowany stan, NPP, Max PP. Przełącznik „podaj pojemność (mln m³)” dla użytkownika, który ma komunikat RZGW, z przeliczeniem na poziom pod spodem. Przy wartości spoza zaobserwowanego zakresu: ostrzeżenie inline.
- **Warstwy**: strefy (domyślnie wł.), model dna (mapa wysokości), niepewność modelu, historyczne linie brzegowe, przystanie i slipy (OSM), podkład: mapa / ortofotomapa.
- Zmiana parametrów od razu przelicza mapę. Nie ma przycisku „Oblicz”, a podczas liczenia widać subtelny wskaźnik ładowania na mapie.

### 15.5 Legenda i kodowanie stref
- Trzy strefy: **bezpieczna**, **ryzykowna**, **zbyt płytka / ląd**. Semantyka zielony–żółty–czerwony może zostać, ale **nie wolno opierać się wyłącznie na kolorze**. Strefa ryzykowna dostaje dodatkowo kreskowanie, a legenda ma etykiety tekstowe. Paleta powinna być czytelna dla osób z deuteranopią; sprawdzić np. turkus / bursztyn / czerwień-magenta.
- Strefy półprzezroczyste (~45–55%), żeby widać było podkład i linię brzegową.
- Legenda zawsze widoczna. Pod legendą jedna linijka podsumowania, np. „Jacht 1,2 m · poziom 195,20 m n.p.m. · bezpieczne 62% akwenu”.

### 15.6 Stany do pokazania
- ładowanie stref (pierwsze i kolejne);
- poziom poza zakresem obserwacji (ostrzeżenie, wynik mniej pewny);
- punkt na lądzie / poza modelem;
- punkt w części zawsze zalanej (głębokość jako „≥ X m”);
- błąd API / brak połączenia;
- pusty stan historii (brak scen dla filtra).

### 15.7 Kierunek wizualny
- Charakter: **mapa żeglarska / mapa nawigacyjna w nowoczesnym, spokojnym wydaniu**. Dużo przestrzeni dla mapy, panele lekkie, bez ozdobników.
- Typografia czytelna w słońcu. Liczby w kroju o stałej szerokości cyfr (tabular), jednostki zawsze przy liczbie (m, m n.p.m., mln m³). Polski format liczb: przecinek dziesiętny.
- Jasny i ciemny motyw (ciemny przydatny wieczorem / na wodzie).
- Duże pola dotyku na mobile (≥ 44 px), suwak obsługiwany kciukiem.

### 15.8 Treści stałe
- Język interfejsu: **polski**.
- Disclaimer zawsze widoczny (stopka / pasek): „Projekt naukowy. Nie służy do nawigacji. Dno modelowane z obrazów satelitarnych z niepewnością.”
- Atrybucje: © OpenStreetMap contributors, Copernicus Sentinel-2, GUGiK.

### 15.9 Poza zakresem projektu UI
Logowanie i konta, zapisywanie tras, nawigacja GPS na żywo, powiadomienia, wielojęzyczność.

### 15.10 Ograniczenia implementacyjne
- Komponenty muszą dać się zbudować w Angularze (np. Angular Material lub własne komponenty) nad MapLibre GL JS.
- Panel i popup jako warstwy nad mapą, mapa zawsze pełnoekranowa.
- Strefy przychodzą z API jako GeoJSON (§8.2), a popup z `/api/point`.

---

## 16. Makiety UI do implementacji (Claude Design → Claude Code)

> **Źródło prawdy dla wyglądu:** canvas „Jezioro Nyskie — mapa głębokości” w Claude Design: https://claude.ai/code/artifact/f7842d26-5bcb-484c-ac1b-6e5162c6be2d
> **Kopia źródeł makiet w repo:** `docs/design/*.dc.html` (format Design Component: HTML z inline style + klasa `Component` w `<script type="text/x-dc">`). Służą jako referencja wyglądu i logiki UI, **nie jako kod do skopiowania**. Implementacja ma powstać w Angularze z MapLibre GL, a z makiet przenosimy layout, tokeny, teksty i zachowanie.

### 16.1 Plansze

| # | Plik | Co pokazuje | Implementacja |
|---|---|---|---|
| 1 | `Main.dc.html` | Mapa główna desktop 1440×900, interaktywna | `MapPageComponent` (route `/`) |
| 1b | `MainDark.dc.html` | To samo w ciemnym motywie | motyw przez CSS custom properties |
| 2 | `Mobile.dc.html` | Mobile 390×844, panel zwinięty | ten sam `MapPageComponent`, układ < 768 px |
| 2b / 2c | `MobileSheet`, `MobileDark` | Panel rozwinięty (jasny / ciemny) | stan bottom sheet |
| 3 | `Popups.dc.html` | 4 warianty popupu punktu | `PointPopupComponent` |
| 4 | `History.dc.html` | Historia linii brzegowych | `HistoryPageComponent` (route `/historia`) |
| 5 | `Method.dc.html` | O metodzie | `MethodPageComponent` (route `/metoda`) |
| 6 | `States.dc.html` | Stany: ładowanie, ostrzeżenia, błędy, pusta historia | komponenty stanów + obsługa w serwisach |
| — | `LakeMap.dc.html` | **Makieta podkładu** (SVG z ręcznie narysowanym jeziorem) | **nie implementujemy**: w aplikacji to MapLibre z prawdziwymi warstwami (§16.5) |

### 16.2 Tożsamość i układ
- Nazwa aplikacji: **„Mielizna”**, podtytuł „Jezioro Nyskie · gdzie przepłynę?”. Logo: zaokrąglony kwadrat w kolorze akcentu z trzema falami (inline SVG z makiety).
- Font: **IBM Plex Sans** (400/500/600, italic 400) z Google Fonts; wszystkie liczby `font-variant-numeric: tabular-nums`.
- Nawigacja: trzy widoki „Mapa”, „Historia linii brzegowych”, „O metodzie” (w panelu na desktopie, ikony zegar / „i” w nagłówku na mobile).
- **Desktop (Main):** mapa na pełny ekran (nad stopką 36 px). Nad nią pływające panele z zaokrągleniem 12–14 px i cieniem:
  - lewy panel parametrów 360 px (`top/left 16`, `bottom 52`, przewijany);
  - kontrolki mapy prawy górny róg: przybliż, oddal, północ (44×44);
  - legenda prawy dolny róg 308 px;
  - skala „1 km” obok panelu;
  - wskaźnik „Przeliczam strefy…” jako pigułka na środku u góry;
  - stopka na całą szerokość: disclaimer po lewej, atrybucje po prawej.
- **Mobile:** pływający nagłówek (logo, nazwa, ikony Historia / O metodzie), przyciski zoomu po prawej i bottom sheet:
  - **zwinięty (290 px):** stepper zanurzenia (−/+), skrót poziomu wody (tap rozwija), mini-legenda, linijka podsumowania;
  - **rozwinięty (760 px):** pełne parametry, warstwy jako chipy, ustawienia zaawansowane, legenda i przycisk „Pokaż mapę”;
  - pod spodem stały pasek disclaimera.
- Breakpoint: desktop ≥ 768 px, mobile poniżej.

### 16.3 Tokeny kolorów

| Token | Jasny | Ciemny | Użycie |
|---|---|---|---|
| `mapBg` | `#EEF0EA` | `#151B20` | tło pod mapą |
| `panel` | `#FFFFFF` | `#12191F` | panele, popup |
| `text` | `#0E2433` | `#E6EEF3` | tekst |
| `muted` | `#4C6475` | `#A3B6C3` | etykiety, opisy |
| `border` / `borderStrong` | `#D8E0E5` / `#AFC0CB` | `#2A3640` / `#40505C` | obramowania |
| `subtle` | `#F3F6F8` | `#1A232B` | tła pól, przycisków |
| `accent` / `accentSoft` / `accentText` | `#1C5D8C` / `#E4EFF7` / `#FFFFFF` | `#6FB3E0` / `#1B3446` / `#0B1A24` | akcent, zaznaczone chipy, fokus |
| `track` / `trackObs` | `#DCE4EA` / `#9FC2DA` | `#2A3640` / `#3D6680` | suwak poziomu: tor / zakres obserwacji |
| `warnBg` / `warnText` | `#FFF4DB` / `#6E4300` | `#3A2A0A` / `#F6C66B` | ostrzeżenia |
| `barBg` / `barText` | `#0E2433` / `#FFFFFF` | `#0A0F13` / `#D6E1E8` | stopka z disclaimerem |
| **`safe`** | `#2BA6A0` | `#34B8B0` | strefa bezpieczna |
| **`risk`** + `hatch` | `#F2B134` + kreski `#8A5A00` | `#F2B134` + `#6B4300` | strefa ryzykowna (kreskowanie 45°) |
| **`danger`** | `#8E1B4F` | `#D0508A` | strefa zbyt płytka / ląd |

Na mapie strefy mają krycie **0,55**. Model dna: 5 stopni od `#C4DDE9` do `#215C86` (jasny) / `#2A4C5E` do `#1675AB` (ciemny). Niepewność: kropkowanie (`#0E2433` / `#E6EEF3`). Linia brzegu `#5F889C`, zapora `#3A4A55`, przystanie: okrąg z literą „P” / „S” w `#1C5D8C`.
Fokus klawiatury: `outline: 3px solid var(--accent); outline-offset: 2px`.

### 16.4 Panel parametrów (Main / Mobile)
1. **Zanurzenie jachtu** (główne pole):
   - przyciski −/+ (krok 0,05) i pole tekstowe `inputmode="decimal"`, które przyjmuje przecinek; zakres 0,10–3,00, podpowiedź pod polem;
   - chipy presetów: Omega 0,90 m · Sasanka 660 miecz w górze 0,40 m · Sasanka 660 miecz w dole 1,25 m · Własny;
   - chip zaznacza się, gdy wartość odpowiada presetowi; „Własny” ustawia fokus na polu.
   - **Wartości presetów z makiety są robocze: do potwierdzenia (§13).**
2. **Poziom wody:**
   - przełącznik segmentowy **Rzędna / Pojemność**;
   - tryb Rzędna: duża liczba „195,20 m n.p.m.” oraz „≈ X mln m³ · 0,20 m powyżej NPP”;
   - tryb Pojemność: pole „Pojemność z komunikatu RZGW [mln m³]”, a pod nim „→ poziom … m n.p.m.” (przeliczenie przez `/api/capacity-to-level`);
   - suwak z wyróżnionym pasmem zakresu obserwacji i znacznikami „min. obs.”, „NPP”, „Max PP”;
   - poza zakresem obserwacji pojawia się ostrzeżenie (`role="alert"`) „Poziom poza zakresem obserwacji (…). Model dna jest tu ekstrapolowany, wynik jest mniej pewny.”
3. **Warstwy:**
   - checkboxy: Strefy dla jachtu · Model dna (mapa wysokości) · Niepewność modelu · Historyczne linie brzegowe · Przystanie i slipy (OSM);
   - przełącznik podkładu Mapa / Ortofotomapa (WMS Geoportal);
   - na mobile te same opcje jako chipy `aria-pressed`.
4. **Ustawienia zaawansowane** (zwijane): zapas bezpieczeństwa −/+ (0–1 m, krok 0,05, domyślnie 0,30) z opisem.
5. Każda zmiana parametru przelicza strefy od razu: debounce ~250 ms, poprzedni wynik zostaje na mapie do czasu odpowiedzi i widać pigułkę „Przeliczam strefy…”.

### 16.5 Mapa (MapLibre zamiast `LakeMap`)
- Źródła: GeoJSON stref z `/api/zones`, rastry modelu dna / niepewności (kafle lub obraz z backendu), linie brzegowe z `/api/shorelines`, przystanie z `/api/marinas`.
- Strefy: `fill` z kolorami z §16.3, opacity 0,55. Kreskowanie strefy ryzykownej i kropki niepewności jako `fill-pattern` z obrazów wygenerowanych w canvas (`map.addImage`).
- Kliknięcie w mapę: pinezka (kropka z halo w kolorze `text`) i popup zakotwiczony nad punktem. Bez popupu u góry mapy widnieje podpowiedź „Kliknij w wodę, aby sprawdzić głębokość”.
- Atrybucje: © OpenStreetMap contributors · Copernicus Sentinel-2 · GUGiK (w stopce i w kontrolce atrybucji).

### 16.6 Legenda
Tytuł „Strefy dla jachtu” i trzy wiersze z próbką oraz opisem:
- „Bezpieczna: głębokość ≥ zanurzenie + zapas (1,50 m)”;
- „Ryzykowna: mieści się w zapasie lub niepewności modelu”;
- „Zbyt płytka / ląd: głębokość mniejsza niż zanurzenie”.

Pod spodem podsumowanie: „Jacht 1,20 m · poziom 195,20 m n.p.m. · bezpieczne 62% akwenu”. Procent pochodzi z `stats` w `/api/zones`; w makiecie jest wyliczany wzorem-atrapą.

### 16.7 Popup punktu (`Popups.dc.html`, dane z `/api/point`)
Szerokość 300 px. Wspólny układ dla wszystkich wariantów:
- nagłówek z przyciskiem zamknięcia;
- duża wartość głębokości;
- belka strefy z próbką koloru: „**Ryzykowna** dla jachtu 1,20 m”;
- lista `dl` ze szczegółami.

Warianty:

| Wariant | Wartość | Szczegóły |
|---|---|---|
| A. Woda, wynik z modelu | „1,4–1,9 m” (przedział D_lo–D_hi) | „Pod kilem 0,20 do 0,70 m · wymagany zapas 0,30 m”; wysokość dna „193,55 m n.p.m. ± 0,25”; liczba scen; położenie (lat, lon) |
| B. Część zawsze zalana | „≥ 4,8 m” | „Głębiej niż … (poniżej najniższego zaobserwowanego stanu …)”; dno „< 190,40 m n.p.m.”; obserwacje „brak (zawsze woda)” |
| C. Ląd przy tym poziomie | „Ląd” | „Dno 0,2–0,6 m powyżej lustra wody przy …”; strefa „Zbyt płytka / ląd” |
| D. Poza obszarem modelu | „Poza obszarem modelu” | „Model obejmuje czaszę zbiornika do rzędnej Max PP …”; „Bez oceny strefy” |

Reguła strefy w popupie i na mapie **musi być ta sama co w §6.4** (`D_lo ≥ d + m` bezpieczna; `D_hi < d` zbyt płytka; reszta ryzykowna). Makieta liczy ją lokalnie uproszczonym wzorem; w aplikacji strefę zwraca backend.

### 16.8 Historia linii brzegowych (`History.dc.html`)
- Lewy panel 400 px:
  - tytuł „Poziom wody na scenach Sentinel-2”;
  - mini-wykres poziomu w czasie z linią NPP i kropkami scen kolorowanymi wg poziomu;
  - chipy filtru roku (Wszystkie, 2026…2019);
  - licznik „12 scen · nałożone: 3” (odmiana: scena/sceny/scen);
  - lista scen: wiersz z próbką koloru, datą `DD.MM.RRRR`, poziomem i powierzchnią (km²), a obok checkbox „Nałóż na mapę”.
- Mapa: nałożone linie brzegowe, kolor wg poziomu (skala 190,0 → 195,5: `#9CC9E4` → `#143F66`). Niższe poziomy dodatkowo linią przerywaną / kropkowaną, żeby dało się je odróżnić bez koloru.
- Karta wybranej sceny: data, poziom, powierzchnia, „Sentinel-2 · zachm. X%”, link **„Ustaw ten poziom na mapie”**, który przechodzi do `/` z `?h=`.
- Pusty stan: „Brak scen dla tego filtra” i przycisk „Pokaż wszystkie sceny”.
- Dane z `/api/scenes` (lista scen w makiecie jest przykładowa).

### 16.9 O metodzie (`Method.dc.html`)
Strona tekstowa, kontener `max-width` 1120 px:
1. Wstęp „Jak powstaje mapa głębokości”.
2. **Pięć kroków** jako karty 01–05: Satelita, Woda / ląd, Linie brzegowe, Model dna, Strefy.
3. Wykres rozrzutu „Poziom a powierzchnia lustra wody” z liniami NPP i Max PP.
4. Kafle „Dokładność modelu”: RMSE dna, zgodność maski wody, liczba scen, zakres poziomów.
5. Tabela źródeł danych z licencjami.
6. Ramka z zastrzeżeniem.
7. Stopka „Projekt na przedmiot … · autor”.

**Treść do poprawienia względem metody z briefu:**
- krok 03: poziom wody przypisujemy **głównie z kalibracji NMT (wariant A)**, a RZGW jest wariantem B (§6.3); makieta mówi tylko o RZGW;
- krok 04: podstawowy model to **przedziały zalania per piksel** (§6.4), a interpolacja poziomic służy tylko do porównania; makieta mówi o interpolacji;
- „Zgodność maski wody (IoU)”: dopisać IoU do metryk w §7 albo zamienić kafel na OA / F1;
- placeholdery `[0,00]`, `[N]`, `[M]`, `[min]–[max]`, `[nazwa przedmiotu]`, `[autor]`, `[warunki do potwierdzenia]` wypełnić z `/api/meta` i raportu (autor: Paweł Ostromecki; przedmiot: Analiza Danych Przestrzennych, Politechnika Opolska).

### 16.10 Stany (`States.dc.html`)

| Stan | Zachowanie |
|---|---|
| A. Pierwsze ładowanie | szkielet mapy i paneli, status „Wczytuję model dna i strefy…” |
| B. Przeliczanie | poprzedni wynik widoczny, pigułka „Przeliczam strefy dla 1,35 m…” z paskiem postępu |
| C. Poziom poza zakresem | ostrzeżenie z wartością i najniższym zaobserwowanym stanem, mapa z warstwą niepewności |
| D. Błąd API | mapa przygaszona, komunikat „Nie udało się przeliczyć stref” z opisem ostatnich poprawnych parametrów, przycisk „Spróbuj ponownie” |
| E. Brak połączenia | pasek „Brak połączenia. Strefy z HH:MM mogą być nieaktualne.” i przycisk „Ponów” |
| F. Pusta historia | jak w §16.8 |

### 16.11 Liczby z makiet, których NIE wolno zaszyć w kodzie
Makiety używają wartości przykładowych. W aplikacji wszystkie przychodzą z API:
- **min. obs. 190,40, NPP 195,00, Max PP 195,70 m n.p.m.**: z `/api/meta`. **Te liczby z makiet są błędne.** Według tabeli z mapy KŻ NPP ≈ 195,9, a Max PP ≈ 198,9 m n.p.m. (do potwierdzenia, §13). Znaczniki NPP / Max PP na suwaku i wykresie „O metodzie” trzeba przesunąć, a najniższy obserwowany stan wyznaczyć z serii scen;
- zakres suwaka 189,00–196,50: wyliczany z `/api/meta` (zakres obserwacji ± margines). Po poprawce Max PP suwak nie może kończyć się poniżej NPP;
- przeliczenie pojemność ↔ poziom: w makiecie atrapa `125·((h−184)/11,7)^1,8`; w aplikacji krzywa z `/api/capacity-to-level`;
- procent bezpiecznego akwenu, dane punktu, lista scen, wykresy: z API.

### 16.12 Dostępność (przenieść 1:1 z makiet)
- Prawdziwe `<button>`, `<a>`, `<input>` z `<label>`.
- `aria-label` na przyciskach z samą ikoną.
- `aria-pressed` na chipach i przełącznikach.
- `aria-valuetext` na suwaku („195,20 metra nad poziomem morza”).
- `role="alert"` dla ostrzeżeń, `role="status"` dla ładowania, `role="dialog"` dla popupu.
- Cele dotyku ≥ 44 px.
- Strefy rozróżnialne bez koloru: kreskowanie i etykiety.
- Język dokumentu `pl`, liczby z przecinkiem dziesiętnym.

### 16.13 Kryteria akceptacji UI
1. Desktop 1440×900 i mobile 390×844 wyglądają jak plansze 1 i 2 / 2b, w obu motywach (przełączanie wg `prefers-color-scheme`).
2. Zmiana zanurzenia, zapasu lub poziomu (w obu trybach) przelicza strefy, legendę i podsumowanie bez przycisku „Oblicz”.
3. Popup obsługuje wszystkie 4 warianty z §16.7, a strefa w popupie zgadza się z kolorem na mapie.
4. Wszystkie stany z §16.10 dają się wywołać (np. przez wyłączenie backendu lub wybór pustego roku).
5. Żadna z liczb z §16.11 nie jest zaszyta we frontendzie.
