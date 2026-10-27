# Mielizna — dokument projektowy implementacji

**Data:** 2026-10-26
**Autor projektu:** Paweł Ostromecki (Analiza Danych Przestrzennych, Politechnika Opolska)
**Źródło prawdy dla treści merytorycznej:** `BRIEF.md` v1.5 (w katalogu głównym `JezioroNyskie/`; zostanie przeniesiony do `docs/BRIEF.md`, §9 briefu).

Ten dokument **nie powtarza briefu**. Ustala to, czego brief nie rozstrzyga albo co zmieniono w rozmowie 26.10.2026: cel implementacji, zakres, sposób pracy, zmiany stacku i kolejność. Wszystko, czego tu nie ma (metoda, dane, adresy, reguła stref, API, wygląd UI), obowiązuje w brzmieniu briefu.

---

## 1. Cel i dlaczego

**Cel (słowami autora):** zrobić wszystko, co potrzeba, żeby móc **dynamicznie pokazać strefy bezpieczne i niebezpieczne na jeziorze w zależności od zadanego zanurzenia** (i poziomu wody), agregując dane tak, jak opisuje brief: **Wody Polskie / RZGW** (pojemność zbiornika), **zdjęcia satelitarne Sentinel-2** (zalanie powierzchni), **LiDAR / NMT GUGiK**, **mapa KŻ Nysa**.

**Termin:** brak twardego cięcia zakresu pod termin („ile pokażemy, tyle pokażemy”). Autor chce mieć coś do pokazania za ok. 2 tygodnie (ok. 9.11.2026), ale to nie zmienia zakresu, tylko uzasadnia kolejność (§5): najpierw działający przekrój od danych do mapy, potem uszczelnianie.

**Sposób pracy:** Claude pisze całość (pipeline, backend, frontend), autor uczy się jej po fakcie i broni ustnie. Wymóg przedmiotu: każdy krok musi dać się wytłumaczyć. Konsekwencje dla kodu w §4.

## 2. Zakres

### W zakresie (to, co potrzebne do celu)
1. **Sentinel-2** (D1): wybór scen 2017–2026, maska chmur SCL, MNDWI/NDWI, klasyfikacja woda/ląd (§6.1–6.2 briefu), maski `water_t`, linie brzegowe `shorelines.gpkg`. **Klasyfikatorem produkcyjnym jest od razu Random Forest (autor, 27.10)**, bo jest używany w dwóch miejscach (pipeline + endpoint „aktualny poziom”). **Otsu zostaje** jako punkt odniesienia w porównaniu i jako cecha RF (MNDWI − próg Otsu); jest tani (kilkanaście linijek). Szczegóły RF w §2a.
2. **Poziom wody `h_t`** (§6.3 briefu), wszystkie cztery źródła:
   - **B** — komunikaty Wody Polskie/RZGW (Wayback 11.2019–03.2024 + gov.pl od 06.2025) → pojemność → rzędna przez tabelę V↔h z mapy KŻ (K4);
   - **A** — LiDAR (4 epoki: data nalotu z GPS time, poziom z klasy 8, NMT w pikselach brzegu);
   - **C** — hipsometria dla luk;
   - **D** — dopasowanie poziomic KŻ, jako kontrola.
   Każda scena: `h_t`, `h_method`, `h_sigma`. Punkt kontrolny 28.04.2025 (197,84–198,00 m).
3. **Mapa KŻ** (D8): K1 georeferencja, K2 punkty rzędnych (OCR + kontrola ręczna), K3 poziomice 192,5 i 195,0, K4 tabela V↔h, K5 porównania.
4. **Model dna** (§6.4 briefu): przedziały zalania per piksel → `bottom_z/zmin/zmax/obs_count.tif` (COG, EPSG:2180).
5. **Ocena dokładności** w zakresie potrzebnym do obrony: OA/Kappa/F1 maski (RF vs Otsu vs SCL), RMSE/bias dna vs NMT LiDAR (holdout blokowy 500 m), porównanie z KŻ (K5), zgodność wariantów `h_t`. Wyniki do `docs/raport.md`.
6. **Backend FastAPI** z API z §8.2 briefu (z `/api/capacity-to-level`) **oraz nowy endpoint `/api/current-level` (autor, 27.10):** backend pobiera najnowszą bezchmurną scenę S2 (Earth Search), stosuje zapisany model RF (`joblib`) → maska wody → powierzchnia lustra → poziom z krzywej powierzchnia↔poziom (wariant C z pipeline'u). Zwraca `h`, datę sceny, zachmurzenie lokalne, linię brzegową i niepewność. Front ustawia suwak na ten poziom przy starcie (z oznaczeniem „poziom z dd.mm.rrrr, wyznaczony z obrazu satelitarnego”). Wynik cache'owany per scena; gdy brak świeżej sceny (np. > 10 dni) lub za dużo chmur, front pokazuje ostatnią znaną wartość z datą. Szczegóły (próg świeżości, limit chmur) — builder.
7. **Frontend React** (§3 tego dokumentu) z makiet §16 briefu: mapa, panel parametrów, legenda + podsumowanie, popup 4 warianty, historia linii brzegowych, „O metodzie”, stany z §16.10, jasny/ciemny motyw, mobile.
8. **Uruchomienie:** `docker compose` (backend + frontend), pipeline przez `uv`.

### Odłożone (decyzja Claude — nie są potrzebne do celu; robimy tylko jeśli zostanie czas)
- Interpolacja poziomic TIN/IDW jako porównawczy model dna (§6.4 briefu).
- Mapa zmian dna M8 (§6.5).
- Kafle rastrowe `/api/zones/tiles` (opcjonalne w briefie).

### Poza zakresem
Jak w briefie §3 i §15.9.

## 2a. Random Forest woda/ląd (ustalone w rozmowie 27.10)

- **Zadanie:** klasyfikacja binarna. Próbka = para (piksel 10 m, scena), etykieta woda/ląd. Wynik zastępuje lub uzupełnia maskę Otsu jako wejście modelu dna (model dna min/max bez zmian).
- **Biblioteka:** `scikit-learn` `RandomForestClassifier` (~50–100 drzew), zapis `joblib`.
- **Cechy (wszystkie z S2 L2A, siatka 10 m):**
  - pasma B02, B03, B04, B08, B11, B12 (B11/B12 z 20 m → 10 m bilinear) — **B02 i B12 dopisać do pobierania** względem briefu;
  - wskaźniki NDWI, MNDWI, AWEI_sh, AWEI_nsh, NDVI;
  - MNDWI − próg Otsu tej sceny (normalizacja między scenami);
  - średnia i odchylenie MNDWI w oknie 3×3 (kontekst przy brzegu);
  - sin/cos dnia roku (fenologia roślinności).
- **Celowo NIE są cechami** (przeciek do modelu dna i jego walidacji): wysokość z NMT, częstość zalewania piksela, `h_t`. Klasa wody z SCL nie jest cechą, tylko trzecim punktem odniesienia obok Otsu i RF.
- **Jeden globalny model** dla wszystkich scen.
- **Walidacja:** grupowa po scenach i po blokach przestrzennych 500 m (bez sąsiednich pikseli w uczącym i testowym); metryki z §7 briefu (macierz pomyłek, OA, Kappa, F1 wody) dla Otsu, RF i SCL; permutation importance cech.
- **Etykiety (autor zgodził się 27.10):**
  - punkty łatwe (stały środek jeziora, odległy ląd) oznaczane automatycznie;
  - **trudne punkty przy brzegu (~150–200) oznacza autor** w prostym narzędziu przeglądarkowym: jeden punkt naraz, krzyżyk na scenie S2 z danego dnia + ortofotomapa obok, klawisze W / L / ? (pomiń);
  - losowanie warstwowe z naciskiem na strefę brzegową;
  - wynik `data/reference/labels.geojson` w repo (§11 briefu: jedyny ręczny krok).
  - Narzędzie: lokalna strona serwowana przez backend dev albo osobny mały skrypt — decyzja buildera; ma być gotowe przed krokiem 6b.
- **Pozostałe kroki ręczne z briefu (decyzja Claude):** kontrola OCR mapy KŻ (≥ 200 punktów) w tym samym narzędziu (wycinek mapy + odczytana liczba, autor potwierdza lub poprawia); linie brzegowe „ręczne” z §7 briefu zastępuje ocena na etykietach brzegowych + kontrola wizualna Claude na 5 scenach; sceny zimowe (lód) odrzuca SCL = 11 + przegląd miniatur przez Claude, z listą odrzuconych w raporcie.
- **Odrzucone warianty ML** (decyzja Claude): głębokość wprost z odbicia (Stumpf) — woda mętna, a KŻ ma być walidacją, nie danymi uczącymi; regresja położenia dna w [z_min, z_max] — możliwa później; regresja `h_t` z powierzchni — spline prostszy.

## 3. Zmiany stacku względem briefu

| Obszar | Brief | Teraz | Kto zdecydował |
|---|---|---|---|
| Framework frontu | Angular | **React** | autor |
| Komunikacja z backendem | — | **TanStack Query** | autor |
| Architektura frontu | — | **komponent → hook-fasada (view-model) → TanStack Query → klient API** | autor |
| Build | — | Vite + TypeScript | Claude |
| Mapa | MapLibre lub OpenLayers | **MapLibre GL JS** bezpośrednio (bez `react-map-gl`) | Claude (§16.5 briefu już zakłada MapLibre) |
| Biblioteki UI / stan globalny | Angular Material lub własne | własne komponenty wg tokenów §16.3; bez Reduxa, stan w hookach | Claude |
| Python | 3.12 | 3.12 przypięty przez `uv` (na maszynie jest 3.13, brak `uv` — do zainstalowania) | Claude |

Nazwy komponentów z §16.1 briefu zachowujemy w wersji React: `MapPage`, `PointPopup`, `HistoryPage`, `MethodPage`; routing `/`, `/historia`, `/metoda`.

### Warstwy frontendu (autor)
- **Komponent** — tylko widok: dostaje gotowe dane i callbacki. **Nie importuje `useQuery` ani `fetch`.**
- **Hook-fasada / view-model** (np. `useZonesVm`, `usePointVm`, `useHistoryVm`, `useMetaVm`) — stan UI, debounce ~250 ms, zaokrąglanie h/d/m do 0,05 m, polskie formatowanie liczb, mapowanie odpowiedzi API na model widoku, wyliczanie stanów z §16.10.
- **TanStack Query** — cache po kluczu z zaokrąglonych parametrów (np. `['zones', h, d, m]`), `placeholderData` = poprzedni wynik (mapa nie znika podczas przeliczania, pigułka „Przeliczam strefy…”), retry, `onlineManager` dla stanu „Brak połączenia”.
- **Klient API** — czyste funkcje `fetch` + typy TS odpowiedzi z §8.2 briefu.

### Backend (ustalone 27.10)
- **Bez bazy danych.** Przy starcie backend wczytuje do pamięci produkty pipeline'u: `bottom_z/zmin/zmax.tif`, `obs_count.tif`, `scenes.json`, `shorelines.gpkg`, `marinas.gpkg`, `kz_pojemnosc_rzedna.csv`, krzywą powierzchnia↔poziom, `rf_model.joblib`.
- **Endpointy:** z §8.2 briefu + `/api/current-level` (§2 pkt 6) + obrazy warstw `GET /api/layers/bottom.png` i `/api/layers/uncertainty.png` (z bbox w `/api/meta`) — decyzja Claude; kafle rastrowe odłożone.
- **Układ kodu (decyzja Claude):** `main.py` (tylko endpointy) · `zones.py` (reguła stref §6.4 + wektoryzacja, czysta logika, testy) · `point.py` · `current.py` (najnowsza scena + RF + krzywa) · `data.py` (wczytanie plików) · `schemas.py` (Pydantic = kontrakt z frontem) · `cache.py`.
- **Cache (autor zaakceptował propozycję, bez Redisa):**
  1. przeglądarka — TanStack Query po `[zones, h, d, m]`;
  2. HTTP — `Cache-Control` + `ETag` z wersją modelu (hash produktów pipeline'u);
  3. backend — cache w pamięci (`cachetools`, LRU + TTL) po zaokrąglonych `(h, d, m, wersja modelu)`; `/api/current-level` cache'owany po dacie najnowszej sceny, sprawdzanie nowej sceny co kilka godzin.
  Cache za małym interfejsem `get/set`, żeby ewentualna podmiana na Redis (wiele instancji) była jednym plikiem i jednym kontenerem. Redis teraz poza zakresem: jeden proces, demo lokalne.

## 4. Kod pisany pod naukę i obronę (decyzja Claude, wynika ze sposobu pracy)
- Pipeline jako ponumerowane, liniowe skrypty (`pipeline/01_…py` … wg §9 briefu). Każdy zaczyna się od docstringu: **co robi, dlaczego tak, wejście → wyjście, jak to obronić**.
- Prostota ponad spryt: jawne pętle/kroki numpy zamiast jednolinijkowców; nazwy zmiennych jak w briefie (`h_t`, `z_min`, `z_max`, `D_lo`, `D_hi`).
- Reguła stref z §6.4 w **jednej** funkcji backendu, pokrytej testami jednostkowymi; front jej nie duplikuje.
- Po każdym kamieniu milowym krótka notatka `docs/nauka/MX.md`: co powstało, jakie wyszły liczby, jakie pytania może zadać prowadzący i odpowiedzi.
- Wyniki pośrednie oglądalne w QGIS (GeoTIFF/GPKG w EPSG:2180) — autor może sam sprawdzić każdy krok.

## 5. Kolejność (decyzja Claude)

Zasada: **jak najszybciej działający przekrój dane → strefy na mapie**, potem dokładanie źródeł i walidacji. Dzięki temu „coś do pokazania” istnieje wcześnie, a każde kolejne źródło widocznie poprawia wynik.

1. **M0 — szkielet:** struktura z §9 briefu w `JezioroNyskie/`, `.gitignore` dla `data/raw` i `data/processed`, `config.yaml`, `pyproject.toml` (uv), README, przeniesienie briefu do `docs/BRIEF.md` z adnotacją o zmianach z §3, zmiana nazwy PDF KŻ.
2. **K4 — tabela V↔h z mapy KŻ** (ręczne przepisanie 66 wierszy z obrazu PDF do `data/reference/kz_pojemnosc_rzedna.csv`) — tania, a odblokowuje wariant B.
3. **M1 (S2)** — sceny z odświeżonym BBOX, cechy (pasma + wskaźniki), Otsu jako szybki podgląd/odniesienie.
3b. **Narzędzie do etykiet + etykiety autora + RF (M2)** — uczenie, walidacja, porównanie z Otsu; maski `water_t` i linie brzegowe z RF. Tu autor ma swój ręczny krok (~20–30 min).
4. **Wariant B** — scraping komunikatów (Wayback + gov.pl, poprawka parsera z `check_sources_2.py`), V → h → `scenes.json`.
5. **M4 — model dna** z dostępnych `h_t`.
6. **M5 backend + M6 frontend** — pierwszy pełny przekrój działa; potem `/api/current-level`, gdy jest krzywa powierzchnia↔poziom.
7. **Wariant A (LiDAR)** — epoki, daty nalotu, poziomy, kalibracja; KRON86 → EVRF2007; uzupełnienie luk B; wariant C dla reszty.
8. **K1–K3, K5 (mapa KŻ)** + wariant D + ocena dokładności (§7 briefu) → `docs/raport.md`.
9. **M7** — docker compose, raport, notatki do nauki.

Po każdym kroku model i aplikacja się przebudowują; liczby w UI zawsze z API (§16.11 briefu).

## 6. Repo i środowisko
- Kod w istniejącym repo `github.com/ostromeckyp/AnalizaDanychPrzestrzennych`, w folderze `JezioroNyskie/` (autor). Struktura wewnątrz wg §9 briefu.
- Dane surowe poza gitem (`data/raw/`, `data/processed/`); w gicie: `data/reference/` (małe pliki), `data/raw/check/` tylko jeśli małe — decyzja buildera.
- Na maszynie: Python 3.13, Node 22, Docker 28; brak `uv`, Angular CLI (niepotrzebny), GDAL CLI (niepotrzebny — `rasterio` ma własny).

## 6a. Decyzje Claude po recenzji (do sprawdzenia przez autora)
- **Język:** dokumentacja, docstringi, komentarze, `docs/nauka/`, `docs/raport.md` i UI po **polsku**; identyfikatory w kodzie po angielsku lub jak w briefie (`h_t`, `z_min`).
- **Priorytet źródeł `h_t`:** zgodnie z briefem: **A (LiDAR) wygrywa**, gdy scena jest w jego zasięgu; potem B, C. Kolejność implementacji z §5 (B przed A) dotyczy tylko tego, co powstaje wcześniej. Gdy A i B różnią się o > 0,2 m, nie uzgadniamy ich na siłę: zapisujemy obie wartości w `scenes.json` i raportujemy różnicę.
- **Okres modelu dna:** pipeline przyjmuje okres jako parametr. Aplikacja serwuje model z **całej serii** (najwięcej obserwacji). Dodatkowo powstaje model „do 08.2024” do porównania z KŻ oraz para przed/po powodzi 09.2024 do sprawdzenia, czy dno się zmieniło. Jeśli zmiana przekracza niepewność, aplikacja przechodzi na model po powodzi (osobna decyzja na podstawie liczb).
- **Rejon żwirowni:** obrys digitalizowany z mapy KŻ (po K1). W walidacji jest wykluczony. W aplikacji strefy są liczone, ale obrys pokazany jako warstwa „dno zmienne (eksploatacja kruszywa)”, a popup dopisuje ostrzeżenie.
- **Demo:** lokalne `docker compose` na komputerze autora; bez hostingu.

## 7. Zostawione builderowi
- Dokładny układ plików frontu, nazwy hooków poza przykładami, biblioteka routingu.
- Mozaika vs wybór kafla S2 per data, szczegóły cache pobrań, format rastrów dla warstw dna/niepewności w API (obraz PNG z bbox vs kafle).
- Sposób rozwiązywania sprzeczności `z_min > z_max` (brief daje dwie opcje).
- Narzędzie do georeferencji KŻ (GDAL przez `rasterio` vs ręczne GCP + `affine`).

## 8. Otwarte kwestie
Jak w §13 briefu. Te, które blokują konkretne kroki, oznaczamy w planie; brak odpowiedzi nie blokuje startu (wartości robocze z briefu, np. NPP ≈ 195,9, presety jachtów z makiet).
