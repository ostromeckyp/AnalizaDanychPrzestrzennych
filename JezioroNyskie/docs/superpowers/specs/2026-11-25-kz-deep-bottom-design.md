# Dno głębokiej części z mapy KŻ i czytelna ścieżka liczenia głębokości — projekt

Data: 2026-11-25. Status: zaakceptowany 2026-11-25 (po recenzji budowniczego, Fable; z kalibracją i eksperymentem poziomów).

## Po co

Model dna z satelity zna dno tylko tam, gdzie woda kiedykolwiek odsłoniła brzeg. W strefie „zawsze woda”
(flaga `FLAG_ALWAYS_WATER`, `z_min` = NaN, w backendzie `z_lo = −∞`) satelita wie tylko, że dno leży **poniżej
najniższego zaobserwowanego poziomu** (`z_max` ≈ 193,05 m). To 10,5 km², ok. 42 % pikseli modelu. Popup nie podaje
tam głębokości, a tabela błędów ma w paśmie < 192,9 m „brak danych”.

Mapa KŻ Nysa (W. Wróblewski, 2023) ma rzędne dna (145 punktów używanych po kontroli ręcznej i odrzutach położenia,
`kz_points.json:n_spots_used`), z czego większość poniżej 192,9 m, plus poziomice 192,5 i 195,0 m. Rzędna jest
bezwzględna (m n.p.m.), więc głębokość = bieżący poziom − rzędna, bez znajomości poziomu z dnia pomiaru. Użytkownik
traktuje te punkty jako najbliższy odpowiednik pomiaru terenowego, jaki mamy.

Druga potrzeba (użytkownik): kod liczenia głębokości ma być czytelny dla człowieka, z przewodnikiem, w jakiej
kolejności czytać pliki, żeby zrozumieć, jak z poszczególnych danych powstaje głębokość.

## Fakty z danych (2026-11-25, model `all`; potwierdzone niezależnie przez recenzenta)

| | wartość |
|---|---|
| piksele w modelu / „zawsze woda” | 250 421 / 104 928 (10,49 km²) |
| `z_max` w „zawsze woda” | 193,05 m dla ≥ 95 % pikseli, maks. 194,45 m |
| pokrycie przez `kz_surface.tif` (wariant D: punkty + poziomice 192,5 i 195,0) | 82,9 % |
| KŻ − `z_max` (P5 / mediana / P95), piksele z KŻ > `z_max` | −5,68 / −1,24 / +1,56 m; 13,6 % |
| sprzeczności wg odległości od poziomicy 195,0 m | < 100 m: 67 %; 100–300 m: 38 %; > 300 m (75 % pikseli): 2,4 % |
| powierzchnia **bez** poziomicy 195,0 m | pokrycie 81,9 %, sprzeczności 6,8 %, P95 KŻ − `z_max` +0,23 m |
| przybliżony LOO (98 punktów w „zawsze woda”, TIN w punkcie) | MAE 1,46 m, bias +0,96 m, błąd ze znakiem P5 / P95 = −1,42 / +5,47 m, 69 % dodatnich |
| wpływ na strefy (zanurzenie 0,5, zapas 0,3) | przy h ≥ 194,0 m bez zmian (już „bezpiecznie”); przy h = 193,0 m 16–32 % pikseli ryzyko → bezpiecznie |

Wnioski: (1) sprzeczności to głównie artefakt TIN przy poziomicy 195,0 m, nie zero wodowskazu KŻ; (2) błąd
interpolacji jest asymetryczny — powierzchnia częściej pokazuje dno **płycej** niż punkt (bezpieczna strona);
(3) główny zysk dla użytkownika to głębokość w popupie i liczba w tabeli błędów; strefy zmieniają się tylko przy
bardzo niskiej wodzie. Użytkownik wybrał mimo to pełną wersję (strefy + popup + warstwa + tabela), żeby wszystko
liczyć jednym wzorem.

## Cele

1. **Refaktor ścieżki backendu (najpierw, bez zmiany wyników).** Czytelna ścieżka w kolejności: wczytanie granic dna
   z satelity (z ±∞) → (od celu 3) łączenie z KŻ → głębokości `D_lo`, `D_hi` → strefa → odpowiedź punktowa.
   Obejmuje `backend/app/data.py` (część dot. granic dna), `zones.py`, `point.py`. `pipeline/mielizna/bottom.py`
   (`compute_bounds`) **zostaje bez zmian** (decyzja użytkownika: ryzyko zmiany wyników; ma już docstringi
   co/dlaczego/jak obronić). Test regresji: przed refaktorem zapisujemy referencję na rzeczywistych danych —
   rastry `zone_classes`, `zone_stats` i odpowiedzi `point_info` dla siatki (h ∈ {193,0; 194,0; 195,0; 195,91},
   zanurzenie ∈ {0,3; 0,5; 1,0}, zapas ∈ {0; 0,3}) i próbki punktów obejmującej wszystkie warianty — po
   refaktorze identyczne.
2. **Przewodnik `docs/jak-czytac-kod.md`.** Kolejność czytania: skąd `h_t` sceny (06, `levels.py`), jak
   `bottom.py` robi z mokro/sucho przedział `[z_min, z_max]`, jak backend robi z tego głębokość i strefę, skąd dno
   KŻ. Dwa przykłady liczbowe przeliczone ręcznie: piksel z dnem z satelity i piksel z dnem z KŻ, od danych do
   koloru i tekstu popupu. Liczby przykładów sprawdza test (przewodnik nie może rozjechać się z kodem).
3. **Powierzchnia dna KŻ dla głębokiej części (pipeline).** Własna powierzchnia, **nie** `kz_surface.tif` wariantu D:
   TIN z punktów KŻ po kontroli + poziomica 192,5 m, **bez poziomicy 195,0 m** (ta opisuje brzegi wysp, które zna
   satelita, i tworzy większość sprzeczności). Żwirownia NaN jak w wariancie D (dno przekopane po mapie). Wariant D
   bez zmian.
4. **Sprawdzian leave-one-out na punktach KŻ.** Dla każdego punktu KŻ w pikselu „zawsze woda”: powierzchnia z celu
   3 bez tego punktu (poziomica 192,5 zostaje), odczyt w pikselu punktu, błąd ze znakiem `err = odczyt − rzędna`
   (dodatni = powierzchnia płycej). Punkty poza otoczką po usunięciu: pomijane i liczone. Zapis
   `data/processed/eval/kz_loo.json`: n, n_pominiętych, MAE, bias, kwantyle P5 i P95 błędu ze znakiem, P90 |err|,
   oraz to samo osobno dla punktów < 192,9 m. Nazwa w raporcie, JSON i UI: **„błąd interpolacji mapy KŻ”** — nie
   całkowita niepewność (LOO nie widzi błędu pomiaru KŻ ani zera wodowskazu; obok podajemy bias K5 +0,30 m).
5. **Reguła łączenia (tylko piksele „zawsze woda” z powierzchnią KŻ).** Z błędu ze znakiem: prawdziwe dno =
   odczyt − err, więc
   - `z_hi = min(z_max_sat, kz − P5)` (płytsza granica; P5 < 0, np. kz + 1,42),
   - `z_lo = kz − P95` (głębsza granica, np. kz − 5,47),
   - źródło piksela `kz`.
   - Sprzeczność: `z_lo > z_max_sat` (nawet najgłębszy wariant KŻ jest wyżej, niż satelita widział wodę) → piksel
     zostaje satelitarny (`z_lo = −∞`, `z_hi = z_max_sat`, źródło `satellite`) z flagą `kz_conflict`. Bez
     wymyślania szerokości przedziału.
   - Piksele bez powierzchni KŻ i wszystkie piksele poza „zawsze woda”: bez zmian, źródło `satellite`.
   - Kwantyle z jednego globalnego LOO (n ≈ 98, liczba zaszumiona — zapisane w ograniczeniach).
   - Produkty w **osobnym katalogu** `data/processed/model/<okres>_kz/` (`bottom_zlo.tif`, `bottom_zhi.tif`,
     `bottom_source.tif` uint8, `kz_conflict` jako bit lub osobny raster, `meta.json` z kwantylami i hashem
     wejść). Kontrole (08, 10, 12, 13) czytają tylko rastry satelitarne; test pilnuje, że ich nie otwierają.
6. **Backend.**
   - `data.py` wczytuje rastry łączone, gdy istnieją (bez nich zachowanie jak dziś).
   - `z_max_floor` (ostrzeżenie `below_observed_bottom`) liczony **tylko z satelitarnego `z_max`**, jak dziś.
   - `Products.version` (ETag `/api/zones`, `/api/point`, klucz cache) obejmuje hash rastrów łączonych i
     `kz_loo.json`.
   - `/api/point`: `kind` bez zmian (stan hydrologiczny: `model`, `always_water`, `land`, `outside`); nowe pola
     we wszystkich wariantach: `bottom_source` (`satellite` | `kz`), `kz_conflict` (bool). Dla `always_water` z
     `bottom_source = kz` głębokości od–do są skończone. Kolejność wariantów jak dziś (`h ≤ z_lo` → `land`).
   - Warstwa barwna dna (`layers.py`, `products.z`) bez zmian — dalej satelitarna.
   - Nowy endpoint (lub pole w istniejącym) z obrysem obszaru `bottom_source = kz` w EPSG:4326, z atrybucją KŻ.
7. **Frontend.**
   - Popup: „Dno: mapa KŻ 2023 (orientacyjne; błąd interpolacji od −a do +b m)” albo „Dno: model satelitarny”;
     przy `kz_conflict` informacja, że mapa KŻ jest tu sprzeczna z satelitą i pokazujemy tylko satelitę.
     Zastrzeżenie: mapa KŻ opisuje dno z 2023 r. i poniżej 192,5 m jest orientacyjna.
   - Warstwa „Dno wg mapy KŻ” (obrys/kreskowanie, odróżnialna od stref i żwirowni), włączona domyślnie, atrybucja
     jak żwirownia; warunki „UWAGA” w opisie źródła.
   - Regeneracja `frontend/src/api/schema.ts` (openapi-typescript).
8. **Tabela błędów i raport.**
   - Budżet: pasmo < 192,9 m dostaje **osobne pole** `kz_loo` (MAE, P5/P95, n) i nową notkę; `range_m` dalej
     `null` (LOO to błąd KŻ względem KŻ, nie modelu względem referencji — nie mieszamy z `combine_band`).
     Zmiany: `13_error_budget.py` (`NO_DATA_NOTE`, wymuszone `range_m=None`), `schemas.ValidationBand` (pole
     opcjonalne), tabela na froncie.
   - Raport: nowa sekcja „Dno głębokiej części z mapy KŻ” (reguła, LOO, sprzeczności i ich związek z poziomicą
     195,0 m, wpływ na strefy, ograniczenia) z markerami `<!-- eval:... -->`; wiersz w tabeli §5.1.
   - „O metodzie”: akapit i wiersz tabeli.

9. **Eksperyment: wpływ szumu poziomu wody (tylko pomiar).** Hold-out roczny powtórzony dla modelu zbudowanego
   bez scen z poziomem z krzywej powierzchnia↔rzędna (bez `h_method = C`; 26 scen) oraz drugi wariant tylko ze
   scen B i R. Ta sama procedura, foldy i metryki co `12_holdout.py`; wynik w
   `data/processed/eval/holdout_level_sources.json` (wariant → MAE, bias, P90, share_in_bounds, liczba scen
   budujących, po pasmach). Kontekst: hold-out ≈ in-sample (0,94 vs 0,93 m), więc błąd siedzi w wejściu, a różnica
   poziomów A − B ma MAE 0,47 m. Eksperyment **nie zmienia serwowanego modelu**; decyzję o zmianie podejmuje
   użytkownik po wynikach. Raport: krótki akapit w §5.5 z wynikiem, także gdy poprawy brak.
10. **Kalibracja przedziałów dna (satelita).** Dziś prawdziwe dno mieści się w `[z_min, z_max]` tylko w 17 %
    przypadków hold-outu (`holdout.json:holdout.vertical.share_in_bounds`), więc strefy obiecują za dużo.
    - Z hold-outu (poza próbą, nie in-sample) dla każdego pasma budżetu (192,9–194,8 i ≥ 194,8 m) liczymy
      jednostronne poszerzenia: `δ_lo` = P95 z `max(0, z_lo − h)` i `δ_hi` = P95 z `max(0, h − z_hi)` na pikselach
      brzegowych, gdzie `h` to poziom sceny testowej; docelowe pokrycie ok. 90 %.
    - Skalibrowane granice: `z_lo − δ_lo`, `z_hi + δ_hi`, tylko dla granic skończonych (±∞ bez zmian); pasmo
      piksela wg środka przedziału, a dla jednostronnie skończonych wg granicy skończonej; poniżej 192,9 m używamy
      δ pasma 192,9–194,8.
    - Kalibracja jest częścią rastrów łączonych (cel 5): najpierw kalibracja granic satelitarnych, potem reguła KŻ,
      a sprzeczność KŻ sprawdzamy względem skalibrowanego `z_hi`. Granice KŻ nie są kalibrowane drugi raz (mają
      własne kwantyle LOO).
    - `kz_loo.json` i `calibration.json` (δ na pasmo, pokrycie przed/po w hold-oucie) w `data/processed/eval/`.
    - `z_max_floor` i kontrole dalej na surowych granicach satelitarnych.
    - Spodziewany skutek: więcej żółtego (ryzyko) przy granicach stref. Raport i „O metodzie” pokazują udział
      stref przed/po dla typowego poziomu 194,5 m (najczęstszy w danych) i dla 193,6 m (typowa zima).
    - Popup: przedział głębokości pokazuje granice skalibrowane; tekst „przedział obejmuje dno w ok. 90 %
      sprawdzonych przypadków”.

## Kolejność prac

Refaktor (1) z testem regresji → przewodnik (2) → eksperyment poziomów (9) → powierzchnia i LOO KŻ (3, 4) →
kalibracja i rastry łączone (10, 5) → backend (6) → frontend (7) → budżet, raport, „O metodzie” (8). Przewodnik
uzupełniany o KŻ i kalibrację na końcu.

## Poza zakresem

- Zmiana modelu satelitarnego, `bottom.py`, klasyfikacji wody, OCR mapy KŻ, wariantu D.
- Korekta zera wodowskazu KŻ (zostaje hipotezą; bias pokazujemy, nie odejmujemy).
- Dno z KŻ poza strefą „zawsze woda” (tam KŻ pozostaje niezależną kontrolą satelity).
- Refaktor kodu spoza ścieżki backendu głębokości.
- Walidacja terenowa (echosonda) — dalej odłożona.

## Czego unikać (porażka, nawet jeśli działa)

- Refaktor, który zmienia jakąkolwiek liczbę. Refaktor i nowa funkcja w osobnych commitach.
- Utrata niezależności kontroli: K5, hold-out i budżet liczone na rastrach satelitarnych, nigdy na łączonych.
- Ukrywanie źródła: użytkownik zawsze widzi, czy głębokość pochodzi z satelity, czy z KŻ.
- Dno z KŻ wyżej niż granica satelity; wymyślony przedział przy sprzeczności.
- Nazwanie błędu interpolacji „dokładnością” lub „całkowitym błędem”.
- Ciche wyłączenie ostrzeżenia `below_observed_bottom`; nieaktualny ETag po przeliczeniu KŻ.
- Przewodnik niezgodny z kodem.

## Ograniczenia

- Mapa KŻ: amatorska, „dno poniżej 192,5 m odwzorowano orientacyjnie”, stan z 2023 r. (raport §4: zmiana dna
  poniżej 193,8 m nie jest wykluczona); warunki „UWAGA” z `data/reference/KZ_ZRODLO_I_WARUNKI.md` przy każdym
  produkcie pochodnym.
- LOO mierzy tylko błąd interpolacji między punktami; kwantyle z ok. 98 punktów są zaszumione.
- Siatka 10 m, EPSG:2180, okres modelu wg `model_choice.json` (obecnie `all`).
- JSON bez NaN/∞ (jak dziś: `None`).

## Podejścia rozważone

1. **Rastry łączone w pipelinie, osobny katalog (wybrane).** Jedno miejsce reguły, testowalne offline, raport i API
   liczą z tego samego; osobny katalog chroni niezależność kontroli.
2. Łączenie w backendzie przy starcie. Odrzucone: reguła w kodzie serwera, raport nie widzi tego samego wyniku.
3. Tylko popup, bez stref. Odrzucone przez użytkownika (pełna wersja mimo małego wpływu na strefy).
4. Przedział symetryczny `kz ± P90|err|`. Odrzucone po recenzji: błąd jest asymetryczny, symetria zawyża płytszą
   granicę o ok. 2 m.
5. Użycie `kz_surface.tif` wariantu D. Odrzucone po recenzji: poziomica 195,0 m daje większość sprzeczności.

## Decyzje użytkownika

- Pełna wersja: dno z KŻ w strefach, popup, warstwa, tabela błędów (2026-11-25, po przedstawieniu małego wpływu na
  strefy).
- Refaktor: ścieżka backendu + przewodnik; `bottom.py` bez zmian (2026-11-25).
- Dopisać kalibrację przedziałów i eksperyment ze źródłami poziomu; projekt zaakceptowany (2026-11-25).
- Kalibracja także dla granic jednostronnych (np. „zawsze woda”), mimo że δ zmierzono tylko na pikselach z obiema
  granicami — wybrane po zobaczeniu skutku (zielone przy 194,5 m: 48 % → 18 %; wariant „tylko obie granice”: 42 %).
  Raport podaje oba warianty i nazywa to ekstrapolacją (2026-11-25).

## Decyzje projektu (po recenzji)

- Powierzchnia bez poziomicy 195,0 m; przedział z kwantyli P5/P95 błędu ze znakiem; przy sprzeczności satelita bez
  zmian + flaga; `kind` bez zmian, źródło jako osobne pole; `z_max_floor` tylko z satelity; hash KŻ w wersji;
  osobny katalog rastrów; osobne pole budżetu.

## Zostawione budowniczemu

- Nazwy modułów i funkcji w refaktorze (byle kroki dało się przeczytać w kolejności z przewodnika).
- Numer skryptu pipeline'u (np. `14_kz_deep.py`) i cel w Makefile.
- Kształt endpointu obrysu KŻ i styl warstwy na mapie.
- Kodowanie `kz_conflict` (bit w rastrze źródła albo osobny raster).
