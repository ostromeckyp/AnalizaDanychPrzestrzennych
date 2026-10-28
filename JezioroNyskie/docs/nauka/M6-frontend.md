# M6 — Frontend: jak z API robimy mapę, której można ufać

Po ludzku: backend (M5) liczy strefy i głębokości, a frontend (`frontend/`, React + MapLibre) tylko je pokazuje i pyta o nowe, gdy zmienisz zanurzenie lub poziom wody.
Żadna liczba na ekranie nie jest zaszyta w kodzie: zakres suwaka, presety jachtów, NPP, procenty i lista scen przychodzą z `/api/meta`, `/api/zones`, `/api/scenes`.

## 1. Warstwy: komponent → VM → Query → klient

| warstwa | gdzie | co wolno | po co |
|---|---|---|---|
| komponent | `src/components/**`, `src/pages/**` | tylko propsy, callbacki, JSX | da się go testować bez sieci i bez TanStack Query |
| view-model | `src/vm/use*Vm.ts` | stan UI, debounce, zaokrąglanie, polskie formatowanie, stany ładowania/błędu | cała „logika ekranu" w jednym miejscu, testowana hookami |
| TanStack Query | `src/vm/**` | cache po kluczu z zaokrąglonych parametrów, `keepPreviousData` | to samo zapytanie nie leci dwa razy, stare strefy zostają na mapie podczas liczenia |
| klient API | `src/api/**` | czyste funkcje `fetch` + typy z `backend/openapi.json` | jedyne miejsce znające adresy i kształt odpowiedzi |

Granicę pilnują dwa mechanizmy: test architektury (`architecture.test.ts` czyta źródła i szuka zakazanych importów oraz literałów z makiet, np. `195,70`) i ESLint (`no-restricted-imports`, `no-restricted-globals: fetch` dla `components` i `pages`).

## 2. Debounce, zaokrąglanie, cache

Suwak generuje dziesiątki wartości na sekundę. VM czeka **250 ms** po ostatniej zmianie i zaokrągla `h`, `draft`, `margin` do **0,05 m** (`round05`) przed zbudowaniem klucza zapytania. Dzięki temu:
1. przeciąganie suwaka daje jedno zapytanie, a nie sto;
2. 195,21 i 195,19 to ten sam klucz, więc cache trafia;
3. odpowiedź dla starszych parametrów nie nadpisuje nowszej (klucz zapytania jest częścią stanu, `placeholderData: keepPreviousData` pokazuje poprzednie strefy do czasu nowych);
4. backend zaokrągla tak samo (M5 §2), więc ETag i treść się zgadzają.

## 3. Dlaczego reguły stref nie ma na froncie

Reguła „zbyt płytka wygrywa" (M5 §2) leży w jednym miejscu: `backend/app/zones.py`. Gdyby front liczył własną, mielibyśmy dwie wersje prawdy i kiedyś rozjechałyby się o jeden piksel w złą stronę (bezpiecznie zamiast ryzykownie). Front dostaje gotowe wielokąty stref i werdykt punktu (`/api/point`), a legendę buduje z `stats` odpowiedzi.

## 4. Obrazy w EPSG:3857 i `coordinates`

Obliczenia są w EPSG:2180, ale MapLibre układa świat w 3857. Backend oddaje PNG warstw dna i niepewności już w 3857 (najbliższy sąsiad) razem z narożnikami w lon/lat. Frontend wkłada to do źródła `image` jako `coordinates` (lewy-górny, prawy-górny, prawy-dolny, lewy-dolny) bez żadnych przeliczeń. Parametr `?theme=` wybiera paletę jasną lub ciemną, a zmiana motywu systemu podmienia URL obrazu bez przeładowania strony.

## 5. Dostępność

Prawdziwe `<button>`, `<a>`, `<input>` z `<label>`; `aria-label` na przyciskach z ikoną; `aria-pressed` na chipach i przełącznikach; `aria-valuetext` suwaka („195,20 metra nad poziomem morza"); `role="alert"` (ostrzeżenia, błędy), `role="status"` (ładowanie, „przeliczam"), `role="dialog"` (popup, zamykany Esc, fokus trafia do środka); cele dotyku ≥ 44 px; fokus `outline: 3px solid var(--accent)`; `<html lang="pl">`; strefy odróżnialne nie tylko kolorem (kreskowanie ryzykownej). Jednostki zawsze przy liczbie, z twardą spacją.

## 6. Test end-to-end i zrzuty

`npm run e2e` (Playwright, Chromium 1243 = `@playwright/test` 1.63.0) stawia backend (`MIELIZNA_LIVE=0`) i `vite preview` z proxy `/api`, po czym sprawdza cztery ścieżki: zmiana zanurzenia → nowe podsumowanie, klik w wodę → popup, historia → „Ustaw ten poziom na mapie" → `/?h=`, błąd `/api/zones` → ekran błędu. Każdy `pageerror` wywala test. Bez `data/processed/model/all/` testy się pomijają.
Zrzuty (`docs/img/m6-*.png`): `SCREENSHOTS=1 npx playwright test e2e/screenshots.spec.ts` (`MOCKUPS=1` dodatkowo renderuje makiety do porównania).

Wynik oglądu i błąd znaleziony przez zrzut: przy pierwszym kadrze zachodnia część jeziora chowała się pod panelem (stałe `padding: 24` w `fitBounds`). Poprawka: padding uwzględnia panel (desktop, 400 px z lewej) lub dolny arkusz (mobile). 

## 7. Rozbieżności względem makiet (`docs/design/*.dc.html`)

Makiety to szablony z polami `{{...}}` i bez podkładu mapy, a ciemne warianty (`MainDark`, `MobileDark`, `MobileSheet`) renderują się w przeglądarce prawie pusto, więc porównanie było układu i tekstów, nie pikseli.

| co | status |
|---|---|
| Nagłówek strony `/metoda`: logo i zakładki ułożone w dwóch wierszach, w makiecie logo po lewej, zakładki po prawej w jednym | zostaje, osobny CSS nagłówka strony treści: do poprawki po planie 3 |
| Karty „Pięć kroków": brak ikon z makiety | zostaje (ikony SVG nie są w briefie §16, tekst zgodny) |
| Wykres „Poziom a powierzchnia": zamiast krzywej z przykładowymi punktami rzeczywiste 218 scen na osiach poziom/powierzchnia, z tłem siatki | zostaje świadomie: dane z `/api/meta`; makieta miała dane przykładowe |
| `/metoda`: 5. kafelek „RMSE dna — w przygotowaniu" zajmuje drugi wiersz, makieta ma 4 kafelki | zostaje: brak wartości do czasu planu 4 (LiDAR), tekst z §16.9 |
| Źródła danych: 5 wierszy (dodana mapa KŻ), makieta 4 | zostaje: KŻ jest źródłem wariantu B |
| Mobile: dymek „Kliknij w wodę…" częściowo zasłania skalę mapy | zostaje, mały; do ewentualnej zmiany położenia po planie 4 |
| Mobile: pasek legendy w stanie zwiniętym zawiera zdanie podsumowania | zgodne z makietą Mobile |
| Panel desktop: ostrzeżenie „Dno poniżej 192,90…" docięte u dołu przy 900 px wysokości (panel się przewija) | zostaje, przewijanie panelu jest zamierzone |
| Kadr startowy mapy: lekko inny niż w makiecie (zasłonięcie przez panel) | **poprawione w tym kroku** (`MapView` padding) |
| Duża „obwódka" strefy „Zbyt płytka / ląd" wokół jeziora | zostaje: AOI modelu = obrys + bufor (B-R12), ląd w AOI jest „zbyt płytki" z definicji |

## 8. Szwy między strefami (B-R7) przy zoomie 15

Sprawdzone na `docs/img/m6-zoom15.png` (zoom ok. 15–16, brzeg strefy ryzykownej i zbyt płytkiej): szwów (jasnych smug między wielokątami) nie widać. Zadanie dla backendu: brak. B-R7 zostaje otwarte tylko w teorii (0,08% pow.).

## 9. Znane ograniczenia

- `npm audit`: moderate advisories w łańcuchu vitest/vite i maplibre-gl v4; wersje przypięte przez plan (Vite 6, maplibre 4.7.1), aktualizacja to osobne zadanie.
- Rodzaj przystani `pier` rysowany jest jako litera „P" (jak marina), bez osobnej ikony.
- Popup przy górnej krawędzi mapy może się przyciąć (zakotwiczony markerem, bez automatycznego odwracania).
- Test e2e nie sprawdza pigułki „Przeliczam…" (przy lokalnym backendzie odpowiedź przychodzi w ułamku sekundy; pigułka jest pokryta testami jednostkowymi stanów).
- Wykres na `/metoda` i obrazy warstw nie mają jeszcze opisu tekstowego dla czytników ekranu poza `aria-label`.

## 10. Pytania prowadzącego z odpowiedziami

**Dlaczego front nie liczy stref sam?** Żeby była jedna reguła i jedna odpowiedzialność za bezpieczną stronę błędu; front tylko pokazuje wynik backendu.

**Jak to się zachowuje przy szybkim przeciąganiu suwaka?** Debounce 250 ms + zaokrąglenie do 0,05 m dają jedno zapytanie; poprzednie strefy zostają na mapie z pigułką „Przeliczam…", a stara odpowiedź nie nadpisze nowej, bo klucz zapytania zależy od parametrów.

**Dlaczego obrazy są w 3857?** Mapa w przeglądarce jest w 3857; obraz w 2180 byłby skośny. Reprojekcja jest raz, po stronie serwera, najbliższym sąsiadem.

**Co użytkownik widzi, gdy backend padnie?** Poprzednie strefy zostają, pojawia się pasek offline lub ekran błędu z godziną ostatnich poprawnych stref i „Spróbuj ponownie".

**Skąd liczba „bezpieczne X% akwenu"?** Z `stats.safe_pct` odpowiedzi (M5, B-R6), zaokrąglona do całości; front jej nie wylicza.

**Czy aplikacja nadaje się do nawigacji?** Nie, i mówi to stały pasek: model dna ma niepewność, a poniżej 192,90 m nie ma obserwacji.

**Jak testowano?** 242 testy jednostkowe/komponentowe (Vitest), test architektury warstw, 104 testy backendu, 4 testy e2e w prawdziwym Chromium na prawdziwych danych.
