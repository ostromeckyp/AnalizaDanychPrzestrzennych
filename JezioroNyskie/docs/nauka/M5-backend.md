# M5 — Backend: jak z plików pipeline'u robimy API „co jest bezpieczne przy poziomie h"

Po ludzku: pipeline (M1–M4) zostawił na dysku mapę przedziałów dna (`z_min`, `z_max` dla każdego piksela 10 × 10 m). Backend (`backend/`, FastAPI) czyta ją raz przy starcie
i na zapytanie „poziom wody h, zanurzenie d, zapas m" odpowiada, które miejsca są bezpieczne, ryzykowne albo za płytkie. Do tego podaje bieżący poziom jeziora ze świeżego zdjęcia Sentinel-2.

## 1. Co powstało

| moduł `backend/app/` | rola |
|---|---|
| `settings.py` | zmienne `MIELIZNA_*` w jednym miejscu |
| `data.py` | `load_products`: czyta model, krzywe, sceny, linie brzegowe, tabelę KŻ; liczy `z_lo`/`z_hi` (NaN → ∓∞) |
| `zones.py` | **jedna** reguła stref, statystyki powierzchni, wektoryzacja do GeoJSON |
| `point.py` | to samo dla jednego punktu (kliknięcie na mapie) |
| `layers.py` | obrazy dna i niepewności w EPSG:3857 (PNG, motyw jasny/ciemny) |
| `current.py` | bieżący poziom: STAC → scena → klasyfikacja → poziom z krzywej (wątek w tle) |
| `cache.py`, `main.py`, `schemas.py` | cache TTL, ETag, endpointy, kontrakt (`backend/openapi.json`) |

Uruchomienie: `cd backend && uv run uvicorn app.main:app`; zmienne w `README.md`.

## 2. Reguła stref i dlaczego „zbyt płytka" wygrywa

Dno znamy jako przedział `[z_min, z_max]`, więc głębokość też jest przedziałem: `D_lo = h − z_max` (najpłycej, jak może być) i `D_hi = h − z_min` (najgłębiej).
- **zbyt płytka**: `D_hi < d` — nawet w najgłębszym wariancie łódź nie przejdzie (ląd przy h też tu trafia);
- **bezpieczna**: `D_lo ≥ d + m` (z tolerancją 1e-6) — nawet w najpłytszym wariancie jest zapas;
- **ryzykowna**: reszta.

Gdyby piksel spełniał oba warunki naraz (sprzeczny przedział), wygrywa „zbyt płytka": pomyłka w stronę „bezpiecznie" kończy się osadzeniem łodzi, pomyłka w drugą stronę — tylko zbędnym objazdem.
Granice ±∞ (zawsze woda: `z_min = −∞`; zawsze ląd: `z_max = +∞`) działają bez osobnych przypadków. Parametry zaokrąglamy do 0,05 m przed liczeniem i przed kluczem cache, więc ETag, cache i treść się zgadzają.

## 3. Dlaczego Otsu do krzywej powierzchnia ↔ poziom

Krzywa zamienia powierzchnię jeziora ze sceny na poziom wody (scena bez komunikatu RZGW, metoda C). Uczy się jej na powierzchniach **Otsu**, bo RF przy niskiej wodzie nasyca powierzchnię (błoto liczy jako woda, R23).
Dlatego bieżąca scena też musi dać powierzchnię Otsu — inaczej mierzylibyśmy inną wielkością niż uczona krzywa. Scena z `qc_ok == False` nie publikuje poziomu, powierzchni ani linii brzegowej.

## 4. Reprojekcja obrazów do EPSG:3857

Obliczenia są w EPSG:2180 (siatka 10 m), ale mapa w przeglądarce (MapLibre) układa kafelki w 3857. Obraz warstwy w 2180 po nałożeniu w 3857 byłby krzywy (obrócony i skośny prostokąt),
więc backend przelicza raster do 3857 (najbliższy sąsiad, bez zmyślania wartości) i podaje narożniki w lon/lat. Warstwa niepewności jest skalowana 2× z kropką 1×1 px na komórkę 2×2 (R9):
po dekodowaniu ≈ 26 MB zamiast ≈ 100 MB, co ma znaczenie na telefonie.

## 5. Cache i ETag

- Strefy (`/api/zones`): cache TTL w pamięci, klucz = zaokrąglona trójka (h, d, m); wynik jest funkcją modelu i parametrów.
- ETag = funkcja wersji modelu (`model_version`) i parametrów; `If-None-Match` równy ETagowi daje 304 bez ciała. Dane statyczne (sceny, linie, przystanie) i PNG mają dłuższy `max-age`, bo zmieniają się tylko z nowym modelem.
- `/api/current-level` ma `Cache-Control: no-cache` — to jedyna odpowiedź zmieniająca się w czasie. Odświeżanie idzie w wątku roboczym, odczyt nigdy nie czeka na sieć.
- Cache TTL (`cachetools.TTLCache`) nie jest bezpieczny wątkowo, więc dostęp jest pod blokadą.

## 6. Liczby z testów `real` (`backend/tests/test_real.py`, prawdziwe `data/processed/`)

| co | wynik |
|---|---|
| `/api/zones` zimny start (h 195,5, d 1,0, m 0,3; świeża aplikacja, pusty cache) | **0,09 s** (budżet < 1 s) |
| `/api/meta`: `n_scenes`, `h_min_obs`, `z_max_floor`, wersja modelu | 218; 192,9; 193,05; `…311e18c951a8` |
| bezpieczna strefa h 195,5, d 1,0, m 0 | **12,8885 km²** w obrysie jeziora OSM (128 885 px); całe API: 12,988 km² (129 880 px) |
| `SceneContext.build` na prawdziwych danych | siatka = `reference_grid()`, RF i `lake.gpkg` się ładują |

Różnica 128 885 px (nasz wynik w obrysie jeziora) wobec 128 908 px z ledgera planu 1: ledger liczył w obrysie jeziora OSM przed R25; R25 mogło tylko zmniejszyć, i zmniejszyło o 23 px.
API liczy cały model (AOI), a 995 px bezpiecznej strefy leży poza obrysem OSM (woda poza poligonem, np. brzeg i zatoki), stąd 12,988 km² w odpowiedzi.

## 7. Bieżący poziom — sprawdzenie na żywo (2026-10-27, Earth Search + publiczne COG na S3)

Uruchomiono `uvicorn` z `MIELIZNA_LIVE=1`, pierwsze odświeżenie zakończyło się po ok. 55 s.
- 2026-10-23 (S2A i S2B): odrzucone `not_usable` (zapisane werdykty danych).
- **2026-10-26 (S2B): przyjęta**, `h = 194,40 m`, σ = 0,49 m, metoda `C_live` (z krzywej), powierzchnia Otsu 12,9243 km², chmury lokalne 1,34%.
- Porównanie z pipeline: `h_t` tej daty w `scenes.json` = 194,20 m (B, komunikat RZGW), powierzchnia Otsu 12,924 km² — **ta sama powierzchnia**, różnica poziomu +0,20 m, czyli ≈ 0,4 σ (w granicach niepewności krzywej).
- Ponieważ data sceny jest równa dacie z pipeline'u, remis rozstrzyga pipeline (dokładniejszy, metoda B): `/api/current-level` zwraca `source: "pipeline"`, `h = 194,20`, `last_checked` ustawione, `last_error: null`.

## 8. Znane ograniczenia M5

- Strefy zwracają tylko 3 obiekty (po jednym na strefę); uproszczenie osobno na strefę zostawia szwy (~0,08% powierzchni, R7).
- Wiek sceny na żywo to doba kalendarzowa wg zegara serwera; brak scen przez >10 dni daje `stale: true`.
- Test `real` nie ćwiczy `load_scene` z COG po `search_fn` automatycznie (sieć); to sprawdzenie ręczne z §7.

## 9. Pytania, które może zadać prowadzący

**1. Dlaczego odpowiedź API zależy od dwóch głębokości, a nie od jednej?**
Bo dna nie znamy punktowo, tylko jako przedział. „Bezpiecznie" musi wytrzymać najpłytszy wariant (`D_lo`), „za płytko" ogłaszamy dopiero, gdy nawet najgłębszy (`D_hi`) nie wystarcza.

**2. Co, jeśli piksel jest jednocześnie bezpieczny i zbyt płytki?**
Wygrywa zbyt płytka. Koszt pomyłki jest asymetryczny (osadzenie łodzi vs objazd).

**3. Dlaczego krzywa poziomu używa powierzchni Otsu, a nie RF?**
RF nasyca powierzchnię przy niskiej wodzie; krzywa uczona na Otsu i stosowana do Otsu jest spójna (R23).

**4. Dlaczego obrazy warstw w 3857, a obliczenia w 2180?**
2180 daje metry bez zniekształceń dla powierzchni i głębokości; 3857 jest układem kafelków mapy, więc obraz musi tam trafić, żeby leżał prosto.

**5. Skąd wiadomo, że zimny `/api/zones` mieści się w sekundzie?**
Test `real` buduje świeżą aplikację (pusty cache) i mierzy pierwsze zapytanie: 0,09 s. Kolejne trafiają w cache.

**6. Czemu `safe_km2` z API (12,988) różni się od 12,891 z planu 1?**
Ledger liczył w obrysie jeziora OSM; w tym obrysie mamy 12,8885 (po R25 o 23 px mniej). API liczy cały model, a ~1000 px bezpiecznej strefy leży poza obrysem OSM.

**7. Czy aplikacja sama łączy się z siecią w testach?**
Nie. Wyszukiwanie STAC i wczytanie sceny są wstrzykiwane; tylko ręczne sprawdzenie z §7 używa sieci.

**8. Co jeśli S3 lub STAC nie odpowiada?**
Błąd przejściowy trafia do `last_error`, nie jest zapisywany jako odrzucenie i będzie ponowiony przy następnym odświeżeniu (R10); API dalej serwuje scenę z pipeline'u.
