# Plan 3: frontend React (M6) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aplikacja „Mielizna” w React: mapa jeziora ze strefami dla zadanego poziomu wody, zanurzenia i zapasu (desktop i mobile, jasny i ciemny motyw), popup punktu, historia linii brzegowych i strona „O metodzie”. Wszystkie liczby przychodzą z API planu 2.

**Architecture:** Vite + React + TypeScript w `frontend/`. Warstwy z spec §3: **komponent** (tylko widok, propsy + callbacki) → **hook-fasada / view-model** (`use*Vm`: stan UI, debounce, zaokrąglanie, polskie formatowanie, stany §16.10) → **TanStack Query** (cache po kluczu z zaokrąglonych parametrów) → **klient API** (czyste funkcje `fetch` + typy wygenerowane z `backend/openapi.json`). Mapa to MapLibre GL JS sterowany imperatywnie z jednego komponentu `MapView`. Wygląd, teksty i zachowanie z makiet `docs/design/*.dc.html` (brief §16).

**Tech Stack:** Node 22, Vite, React 18, TypeScript (strict), @tanstack/react-query v5, react-router-dom v6, maplibre-gl v4, openapi-typescript, Vitest + @testing-library/react + jsdom, ESLint, Playwright (tylko Task 11). Wersje: aktualna stabilna gałąź główna w chwili instalacji, w `package.json` **przypięte dokładnie** (bez `^`/`~`), `package-lock.json` w repo.

**Spec:** `docs/superpowers/specs/2026-10-26-mielizna-design.md` (§3 „Warstwy frontendu”, §2 pkt 6–7) + `docs/BRIEF.md` (§15, §16 — wiążące dla UI) + makiety `docs/design/*.dc.html` + kontrakt `backend/openapi.json` (plan 2).

**Kolejne plany:** plan 4 — LiDAR (wariant A), mapa KŻ (K1–K3, K5), wariant D, ocena dokładności, `docs/raport.md`, docker compose (serwowanie frontu i proxy `/api`).

## Global Constraints

- Katalog roboczy `JezioroNyskie/`; repo git to katalog nadrzędny. Gałąź `feat/frontend` od `main`.
- Frontend w `frontend/`. Komendy: `npm test` (Vitest, jednorazowo), `npm run build` (`tsc --noEmit && vite build`), `npm run lint`, `npm run gen:api` (openapi-typescript `../backend/openapi.json` → `src/api/schema.ts`). Dev: `npm run dev` z proxy Vite `/api` → `http://localhost:8000` (bez CORS w backendzie).
- **Warstwy (spec §3):** pliki w `src/components/**` i `src/pages/**` nie importują `@tanstack/react-query`, `src/api/**` ani nie wołają `fetch`. Tylko `src/vm/**` używa TanStack Query i klienta API. Pilnuje tego test architektury (Task 2).
- **Żadna liczba z makiet nie jest zaszyta** (brief §16.11): min. obs., NPP, Max PP, zakres suwaka, presety, procenty, metryki, lista scen — wszystko z API (`/api/meta`, `/api/zones`, …). Test architektury wyszukuje w `src/` literały `190,40`, `195,00`, `195,70`, `189,00`, `196,50`, `62%`.
- Parametry `h`, `draft`, `margin` zaokrąglane do **0,05** w VM przed kluczem zapytania (`round05(x) = Math.round(x / 0.05) * 0.05`, potem 2 miejsca). Debounce zmian **250 ms**. `placeholderData: keepPreviousData` dla stref.
- **Polskie formatowanie:** przecinek dziesiętny (`Intl.NumberFormat('pl-PL')`), jednostka zawsze przy liczbie z twardą spacją (`195,20 m n.p.m.`, `1,20 m`, `45,6 mln m³`, `12,9 km²`), daty `DD.MM.RRRR`, odmiana `scena / sceny / scen`. Wszystkie liczby w UI `font-variant-numeric: tabular-nums`.
- **Tokeny kolorów** brief §16.3 jako CSS custom properties w `src/styles/tokens.css`, jasny domyślnie, ciemny przez `@media (prefers-color-scheme: dark)`. Strefy na mapie: `safe #2BA6A0/#34B8B0`, `risk #F2B134` + kreski `#8A5A00/#6B4300` pod 45°, `danger #8E1B4F/#D0508A`, krycie **0,55**. Font **IBM Plex Sans** 400/500/600 + italic 400 (Google Fonts).
- **Dostępność (brief §16.12):** prawdziwe `<button>/<a>/<input>` z `<label>`; `aria-label` na przyciskach z ikoną; `aria-pressed` na chipach i przełącznikach; `aria-valuetext` na suwaku („195,20 metra nad poziomem morza”); `role="alert"` dla ostrzeżeń, `role="status"` dla ładowania, `role="dialog"` dla popupu; cele dotyku ≥ 44 px; fokus `outline: 3px solid var(--accent); outline-offset: 2px`; `<html lang="pl">`.
- Breakpoint: desktop ≥ **768 px**, mobile poniżej. Routing: `/`, `/historia`, `/metoda`; `/?h=195.25` ustawia poziom.
- Teksty UI po polsku dosłownie z makiet i briefu §16 (z poprawkami treści z §16.9). Disclaimer zawsze widoczny: „Projekt naukowy. Nie służy do nawigacji. Dno modelowane z obrazów satelitarnych z niepewnością.” Atrybucje: „© OpenStreetMap contributors · Copernicus Sentinel-2 · GUGiK”.
- Podkład: OSM raster `https://tile.openstreetmap.org/{z}/{x}/{y}.png` (256 px, atrybucja), ortofotomapa WMS Geoportalu `https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution`, `LAYERS=Raster`, `FORMAT=image/jpeg`, `bbox={bbox-epsg-3857}`.
- Komentarze w kodzie po polsku, krótkie, tylko tam, gdzie „dlaczego” nie wynika z kodu; identyfikatory po angielsku.
- Commity kończą się linią `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Szybkie przeciąganie suwaka:** wiele zmian w 250 ms daje jedno zapytanie, a odpowiedź dla starszych parametrów nie nadpisuje nowszych (mapa i legenda zawsze dla ostatnich h/d/m). → test w Task 4.
2. **Wpisywanie liczb po polsku:** „1,2”, „1.2”, „ 1,25 ”, „abc”, „5” w polu zanurzenia i pojemności — przecinek działa, śmieci i wartości spoza zakresu nie idą do API (podpowiedź pod polem, ostatnia poprawna wartość zostaje). → test w Task 6.
3. **Zmiana motywu w trakcie pracy** (system przełącza jasny/ciemny): kolory stref i obrazy warstw dna/niepewności (`?theme=`) zmieniają się bez przeładowania. → test w Task 5.
4. **Kliknięcie w ląd, poza model, w część zawsze zalaną:** właściwy wariant popupu (§16.7 A–D), nigdy „null m”, „NaN” ani „Infinity”. → test w Task 7.
5. **Backend pada w trakcie sesji / brak sieci:** poprzednie strefy zostają na mapie, pokazuje się stan D lub E z godziną ostatnich poprawnych stref, „Spróbuj ponownie” / „Ponów” działa. → testy w Task 4 i Task 7.

---

### Task 1: Backend — GeoJSON bez `null` w `id`/`bbox` (R13 planu 2)

**Files:**
- Modify: `backend/app/main.py` (serializacja `ZonesResponse`), `backend/openapi.json`
- Test: `backend/tests/test_api_zones.py`

- [ ] **Step 1: Write the failing test**
```python
def test_zone_features_have_no_null_id_or_bbox(client):
    j = client.get("/api/zones", params={"h": 195.0, "draft": 1.2}).json()
    for f in j["features"]:
        assert "bbox" not in f or isinstance(f["bbox"], list)
        assert "id" not in f or f["id"] is not None
```
- [ ] **Step 2:** Run `cd backend && uv run pytest tests/test_api_zones.py -q` → FAIL.
- [ ] **Step 3:** Serializować strefy przez `model_dump_json(exclude_none=True)` (żadne inne pole `ZonesResponse` nie jest opcjonalne); odświeżyć `openapi.json` (`scripts/export_openapi.py`), jeśli się zmienia.
- [ ] **Step 4:** Run `uv run pytest -q` → PASS.
- [ ] **Step 5:** Commit `fix(backend): omit null id/bbox in zone features (RFC 7946)`

---

### Task 2: Szkielet frontendu, tokeny i test architektury

**Files:**
- Create: `frontend/package.json`, `package-lock.json`, `vite.config.ts`, `tsconfig.json`, `index.html` (`lang="pl"`, IBM Plex Sans), `eslint.config.js`, `src/main.tsx`, `src/App.tsx` (router z trzema pustymi stronami), `src/styles/tokens.css`, `src/styles/base.css`, `src/test/setup.ts`
- Create: `src/api/schema.ts` (wygenerowany), `src/architecture.test.ts`
- Modify: `.gitignore` (`frontend/node_modules/`, `frontend/dist/`), `README.md` (sekcja „Frontend”)

**Interfaces:**
- Produces: skrypty npm z Global Constraints; `src/api/schema.ts` = wynik `openapi-typescript ../backend/openapi.json`; tokeny CSS o nazwach z briefu §16.3 w kebab-case (`--map-bg`, `--panel`, `--text`, `--muted`, `--border`, `--border-strong`, `--subtle`, `--accent`, `--accent-soft`, `--accent-text`, `--track`, `--track-obs`, `--warn-bg`, `--warn-text`, `--bar-bg`, `--bar-text`, `--safe`, `--risk`, `--hatch`, `--danger`, `--shore`, `--dam`); `src/theme.ts` z `ZONE_COLORS`, `BOTTOM_RAMP`, `UNC_DOT` dla obu motywów (te same wartości co w CSS — jedno źródło: CSS czyta MapLibre przez `getComputedStyle` albo `theme.ts` generuje CSS; wybrać jedno i opisać w komentarzu).

- [ ] **Step 1: Write the failing test** `src/architecture.test.ts` (czyta pliki przez `import.meta.glob('./**/*.{ts,tsx}', { as: 'raw', eager: true })`):
```ts
it('components and pages do not touch the query layer or fetch', () => {
  for (const [path, src] of viewFiles()) {   // src/components/**, src/pages/**
    expect(src, path).not.toMatch(/@tanstack\/react-query|from ['"].*\/api\/|\bfetch\(/);
  }
});
it('no mockup numbers are hardcoded', () => {
  for (const [path, src] of allSourceFiles()) {   // bez *.test.*, src/test/** i schema.ts
    for (const n of ['190,40', '195,00', '195,70', '189,00', '196,50', '62%']) expect(src, path).not.toContain(n);
  }
});
it('generated API schema matches backend/openapi.json', async () => {
  expect(await generateSchema('../backend/openapi.json')).toBe(read('src/api/schema.ts'));
});
```
- [ ] **Step 2:** Run `cd frontend && npm test` → FAIL (brak projektu / plików).
- [ ] **Step 3:** Utworzyć projekt (Vite react-ts), zainstalować zależności z Tech Stack z dokładnymi wersjami, skonfigurować Vitest (`jsdom`, `setup.ts` z `@testing-library/jest-dom`), proxy `/api`, ESLint (`no-restricted-imports` dla `src/components/**` i `src/pages/**` z tą samą regułą co test), tokeny jasne/ciemne, `npm run gen:api`.
- [ ] **Step 4:** Run `npm test && npm run lint && npm run build` → PASS.
- [ ] **Step 5:** Commit `feat(frontend): scaffold, tokens, generated API types, architecture test`

---

### Task 3: Klient API i formatowanie

**Files:**
- Create: `src/api/client.ts`, `src/format.ts`, `src/test/fixtures.ts`
- Test: `src/api/client.test.ts`, `src/format.test.ts`

**Interfaces:**
- Produces:
  - typy z `schema.ts`: `Meta`, `Zones`, `ZoneFeature`, `Point`, `Scene`, `Shoreline`, `Marinas`, `CurrentLevel`, `CapacityToLevel`, `LevelToCapacity` (aliasy `components['schemas'][...]`).
  - `class ApiError extends Error { status: number; detail: unknown }`.
  - `api.meta()`, `api.zones({h, draft, margin}, signal?)`, `api.point({lon, lat, h, draft, margin}, signal?)`, `api.scenes()`, `api.shoreline(date)`, `api.marinas()`, `api.currentLevel()`, `api.capacityToLevel(v)`, `api.levelToCapacity(h)` → `Promise<T>`; ścieżki względne `/api/...`; parametry przez `URLSearchParams` z kropką dziesiętną; odpowiedź != 2xx → `ApiError` (z `detail` z JSON, gdy jest).
  - `api.layerUrl(url: string, theme: 'light' | 'dark') => string` (dopisuje `?theme=`).
  - `format.ts`: `round05(x: number): number`; `parsePlNumber(s: string): number | null` (przecinek lub kropka, spacje obcięte, `null` dla śmieci); `fmtNum(x: number, digits: number): string` (pl-PL); `fmtLevel(h)` → `"195,20 m n.p.m."`; `fmtM(x, digits = 2)` → `"1,20 m"`; `fmtCapacity(v)` → `"45,6 mln m³"`; `fmtKm2(a)` → `"12,9 km²"`; `fmtPct(p)` → `"62%"`; `fmtDate(iso)` → `"26.10.2026"`; `fmtTime(d: Date)` → `"10:42"`; `plScenes(n)` → `"1 scena" | "3 sceny" | "5 scen" | "22 sceny" | "12 scen"`; `levelValueText(h)` → `"195,20 metra nad poziomem morza"`. Jednostki z twardą spacją U+00A0.
  - `src/test/fixtures.ts` (wspólne dla testów Task 4–10; test architektury pomija `src/test/**`), typowane odpowiedzi zgodne z `schema.ts`: `meta` (`h_min_obs 192.9`, `h_max_obs 197.92`, `npp 195.91`, `max_pp 198.89`, `slider {min 192.4, max 198.9, step 0.05}`, `defaults {h 194.2, draft 1.2, margin 0.3}`, presety Omega 0.90 / Sasanka 660 miecz w górze 0.40 / w dole 1.25, `presets_provisional true`, `limits {draft [0.1, 3.0], margin [0, 1]}`, `z_max_floor 193.05`, `accuracy {rf_oa 0.8162, rf_ba 0.7718, rf_kappa 0.3731, otsu_ba 0.7554, n_labels 185}`, `area_level` z 3 punktami i 3 węzłami, `layers` z czterema narożnikami i 6 progami); `zones(h, draft, margin)` (budowniczy: 3 obiekty, `stats.safe_pct 62`, `params` = argumenty); `pointModel`, `pointAlwaysWater`, `pointLand`, `pointOutside` (wartości jak w fixture backendu: przedział 193,0/194,0; zawsze woda `z_max 193.05`; ląd `z_min 196.0`, `z_max null`; poza modelem); `scenes` (3 sceny w 2025 i 2026, ostatnia `2026-10-20`, `h_t 194.2`, B); `currentLevel` (pipeline, B, `2026-10-20`).

- [ ] **Step 1: Write the failing tests**
```ts
it.each([['1,2', 1.2], ['1.2', 1.2], [' 1,25 ', 1.25], ['abc', null], ['', null], ['1,2,3', null]])(
  'parsePlNumber(%s)', (s, v) => expect(parsePlNumber(s)).toBe(v));
it('round05', () => { expect(round05(195.2300001)).toBe(195.25); expect(round05(1.224)).toBe(1.2); });
it('formats', () => {
  expect(fmtLevel(195.2)).toBe('195,20 m n.p.m.');
  expect(fmtCapacity(45.62)).toBe('45,6 mln m³');
  expect(fmtDate('2026-10-26')).toBe('26.10.2026');
  expect([1, 3, 5, 12, 22].map(plScenes)).toEqual(['1 scena', '3 sceny', '5 scen', '12 scen', '22 sceny']);
});
it('zones request uses dot decimals and throws ApiError with detail', async () => {
  const f = mockFetch(422, { detail: [{ loc: ['query', 'h'], msg: 'x', type: 'value_error' }] });
  await expect(api.zones({ h: 195.25, draft: 1.2, margin: 0.3 })).rejects.toMatchObject({ status: 422 });
  expect(f).toHaveBeenCalledWith('/api/zones?h=195.25&draft=1.2&margin=0.3', expect.anything());
});
```
- [ ] **Step 2:** Run `npm test` → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(frontend): API client and Polish formatting`

---

### Task 4: Warstwa zapytań i view-modele

**Files:**
- Create: `src/vm/queryClient.ts`, `src/vm/useMetaVm.ts`, `src/vm/useZonesVm.ts`, `src/vm/useCurrentLevelVm.ts`, `src/vm/useCapacityVm.ts`, `src/vm/useDebounced.ts`
- Test: `src/vm/useZonesVm.test.tsx`, `src/vm/useMetaVm.test.tsx`, `src/vm/useCurrentLevelVm.test.tsx`

**Interfaces:**
- Consumes: `api`, `format` (Task 3).
- Produces:
  - `queryClient`: `retry: 1`, `staleTime: 5 min`; klucze `['meta']`, `['zones', h, draft, margin]`, `['point', lon6, lat6, h, draft, margin]`, `['scenes']`, `['shoreline', date]`, `['marinas']`, `['current-level']` (`refetchInterval: 30 min`), `['capacity', v]`, `['level-capacity', h]`.
  - `useMetaVm(): { status: 'loading' | 'error' | 'ready'; meta?: Meta; slider?: {min, max, step, obsMin, obsMax, npp, maxPp}; presets?: {label, draft}[]; retry(): void }`.
  - `useZonesVm(params: {h, draft, margin}): { zones?: Zones; summary?: string; status: ZonesStatus; lastOkAt?: Date; lastOkParams?: {h, draft, margin}; warnings: string[]; retry(): void }`, gdzie `ZonesStatus = 'first-load' | 'ready' | 'recalculating' | 'error' | 'offline'` (stany §16.10 A, B, D, E). Wejście debounce 250 ms → `round05` → zapytanie; `placeholderData: keepPreviousData`; `summary` = `"Jacht 1,20 m · poziom 195,20 m n.p.m. · bezpieczne 62% akwenu"` (procent z `stats.safe_pct`, zaokrąglony do całości); `offline` z `onlineManager` TanStack Query.
  - `useCurrentLevelVm(): { level?: {h, label, note?}; status }`: `label` = `"poziom z 26.10.2026, wyznaczony z obrazu satelitarnego"` (source `satellite` albo `h_method` C), `"poziom z 26.10.2026, z komunikatu RZGW"` (`h_method` B/R); `stale` → `note: "ostatnia znana wartość"`; `ice_unverified` → `note: "możliwy lód — poziom niezweryfikowany"`.
  - `useCapacityVm(mode: 'level' | 'capacity', input)`: `{ hFromCapacity?: number; capacityAtLevel?: number; aboveNpp?: string }` (`"0,20 m powyżej NPP"` / `"poniżej NPP"`, NPP z meta).

- [ ] **Step 1: Write the failing tests** (renderHook z `QueryClientProvider`, `vi.useFakeTimers()`, `api` zamockowane)
```ts
it('debounces and rounds: 5 changes in 200 ms → 1 request with rounded params', async () => { /* rerender h=195.21..195.24 */
  expect(api.zones).toHaveBeenCalledTimes(1);
  expect(api.zones).toHaveBeenLastCalledWith({ h: 195.25, draft: 1.2, margin: 0.3 }, expect.anything());
});
it('late response for old params never replaces newer result', async () => { /* resolve h=195.0 after h=195.5 */
  expect(result.current.zones?.params.h).toBe(195.5);
});
it('keeps previous zones while recalculating', async () => {
  expect(result.current.status).toBe('recalculating'); expect(result.current.zones?.params.h).toBe(195.0);
});
it('error keeps last good zones and params', async () => {
  expect(result.current.status).toBe('error'); expect(result.current.lastOkParams).toEqual({ h: 195, draft: 1.2, margin: 0.3 });
  expect(result.current.zones).toBeDefined();
});
it('offline status from onlineManager', async () => { onlineManager.setOnline(false); expect(result.current.status).toBe('offline'); });
it('summary text', () => expect(summary).toBe('Jacht 1,20 m · poziom 195,00 m n.p.m. · bezpieczne 62% akwenu'));
it('current level label B vs satellite, stale and ice notes', () => { /* trzy przypadki */ });
```
(Literał `62%` w teście jest dozwolony — test architektury pomija `*.test.*`.)
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(frontend): query layer and view-models`

---

### Task 5: `MapView` — MapLibre, warstwy, motyw

**Files:**
- Create: `src/components/map/MapView.tsx`, `src/components/map/patterns.ts`, `src/components/map/layers.ts`, `src/vm/useThemeVm.ts`
- Test: `src/components/map/MapView.test.tsx` (`vi.mock('maplibre-gl')` z atrapą `Map` rejestrującą `addSource/addLayer/setPaintProperty/addImage/getSource().setData/updateImage/on`)

**Interfaces:**
- Consumes: tokeny / `theme.ts` (Task 2).
- Produces:
  - `useThemeVm(): 'light' | 'dark'` (`matchMedia('(prefers-color-scheme: dark)')` z nasłuchem zmian).
  - `<MapView theme bbox zones? bottomLayer? uncertaintyLayer? shorelines? marinas? visible={{zones, bottom, uncertainty, shorelines, marinas}} basemap="osm" | "orto" pin?={lon,lat} onMapClick(lon, lat) onReady? />` — komponent nie wie nic o API (dostaje gotowe GeoJSON i `{url, coordinates}`).
  - Źródła/warstwy (stałe nazwy w `layers.ts`): `basemap-osm`, `basemap-orto` (raster), `bottom` (image), `uncertainty` (image), `zones` (geojson) z warstwami `zones-safe`, `zones-risk` (fill-pattern `risk-hatch`), `zones-danger`, `shorelines` (line, kolor wg poziomu skala `#9CC9E4` → `#143F66` dla 190,0 → 195,5; poziomy < NPP linia przerywana), `marinas` (circle + symbol „P”/„S”), `pin` (circle z halo).
  - `patterns.ts`: `makeHatch(theme) -> ImageData` (canvas 16×16, tło `risk`, kreski 45° `hatch`), dodawane `map.addImage('risk-hatch', …)`; przy zmianie motywu `updateImage`.
  - Zmiana motywu: `setPaintProperty` kolorów stref, nowa kreska, nowe `url` obrazów (`?theme=`); bez tworzenia mapy od nowa.
  - Początkowy widok: `fitBounds(bbox_wgs84)`; kontrolki zoom +/− i północ jako własne przyciski 44×44 (`aria-label`: „Przybliż”, „Oddal”, „Północ”); `AttributionControl` z tekstem atrybucji.

- [ ] **Step 1: Write the failing tests**
```ts
it('adds zone layers with 0.55 opacity and hatch pattern for risk', () => {
  expect(addLayer).toHaveBeenCalledWith(expect.objectContaining({ id: 'zones-risk', paint: expect.objectContaining({ 'fill-pattern': 'risk-hatch', 'fill-opacity': 0.55 }) }));
});
it('setData on zones update, no re-add', () => { rerender(<MapView … zones={z2} />); expect(setData).toHaveBeenCalledWith(z2); });
it('theme switch updates colours, hatch and image urls without recreating the map', () => {
  rerender(<MapView theme="dark" … />);
  expect(MapCtor).toHaveBeenCalledTimes(1);
  expect(setPaintProperty).toHaveBeenCalledWith('zones-danger', 'fill-color', '#D0508A');
  expect(updateImage).toHaveBeenCalledWith('risk-hatch', expect.anything());
  expect(imageSource.updateImage).toHaveBeenCalledWith(expect.objectContaining({ url: expect.stringContaining('theme=dark') }));
});
it('click reports lon/lat', () => { fire('click', { lngLat: { lng: 17.25, lat: 50.45 } }); expect(onMapClick).toHaveBeenCalledWith(17.25, 50.45); });
it('visibility toggles via layout property', () => { /* visible.bottom=false → setLayoutProperty('bottom','visibility','none') */ });
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5: Ręczna kontrola WMS:** w `npm run dev` z backendem przełączyć podkład na ortofotomapę i sprawdzić, że kafle się ładują w EPSG:3857 (Network: 200, obraz). Jeśli serwis nie obsługuje 3857, zapisać to w raporcie i przełączyć na `VERSION=1.1.1&SRS=EPSG:3857`; gdy i to nie działa — ukryć przełącznik ortofotomapy i opisać w raporcie (nie zgadywać innego serwisu).
- [ ] **Step 6:** Commit `feat(frontend): MapView with zones, layers and theme switching`

---

### Task 6: Panel parametrów i legenda

**Files:**
- Create: `src/components/panel/DraftField.tsx`, `src/components/panel/LevelControl.tsx`, `src/components/panel/LayersControl.tsx`, `src/components/panel/AdvancedMargin.tsx`, `src/components/panel/ParameterPanel.tsx`, `src/components/legend/Legend.tsx`
- Test: `src/components/panel/*.test.tsx`, `src/components/legend/Legend.test.tsx`

**Interfaces:**
- Consumes: `format.ts`; dane jako propsy z VM (Task 4).
- Produces (wszystko kontrolowane, propsy + callbacki, bez stanu domenowego):
  - `<DraftField value presets limits onChange(d) />`: −/+ krok 0,05, pole `inputmode="decimal"` przyjmujące przecinek (`parsePlNumber`), zakres z `limits.draft`; śmieci lub poza zakresem → podpowiedź pod polem „Podaj wartość od 0,10 do 3,00 m” (liczby z `limits`), `onChange` NIE jest wołane, wartość pola zostaje do poprawienia; chipy presetów (`aria-pressed` gdy wartość równa presetowi) + „Własny” (fokus na pole); `presets_provisional` → dopisek „wartości robocze”.
  - `<LevelControl mode h slider level capacity currentLevel warnings onModeChange onLevelChange onCapacityChange />`: przełącznik segmentowy „Rzędna / Pojemność”; tryb Rzędna: duża liczba `fmtLevel(h)`, pod nią „≈ X mln m³ · 0,20 m powyżej NPP”; tryb Pojemność: pole „Pojemność z komunikatu RZGW [mln m³]” i „→ poziom … m n.p.m.” lub „poza tabelą pojemności” (`in_table=false`); suwak `type=range` z `aria-valuetext`, pasmem zakresu obserwacji (`--track-obs`) i znacznikami „min. obs.”, „NPP”, „Max PP” w pozycjach z `slider`; ostrzeżenia `role="alert"`: `h_out_of_range` → „Poziom poza zakresem obserwacji (192,90–197,92 m n.p.m.). Model dna jest tu ekstrapolowany, wynik jest mniej pewny.”; `below_observed_bottom` → „Dna poniżej 192,90 m n.p.m. nie obserwowano — przy tym poziomie i zanurzeniu nie ma strefy bezpiecznej.” (liczby z meta: `h_min_obs`, `h_max_obs`); etykieta bieżącego poziomu z `useCurrentLevelVm` pod suwakiem.
  - `<LayersControl visible basemap onToggle(name) onBasemap(b) variant="list" | "chips" />`: checkboxy desktop / chipy `aria-pressed` mobile; nazwy „Strefy dla jachtu”, „Model dna (mapa wysokości)”, „Niepewność modelu”, „Historyczne linie brzegowe”, „Przystanie i slipy (OSM)”; podkład „Mapa / Ortofotomapa”.
  - `<AdvancedMargin value limits onChange />`: zwijane „Ustawienia zaawansowane”, −/+ 0–1 m krok 0,05, opis z makiety.
  - `<Legend draft margin summary compact? />`: tytuł „Strefy dla jachtu”, trzy wiersze z próbką (ryzykowna z kreskowaniem) i tekstami §16.6 („Bezpieczna: głębokość ≥ zanurzenie + zapas (1,50 m)” — suma liczona z propsów), linijka podsumowania.

- [ ] **Step 1: Write the failing tests** (Testing Library, `userEvent`)
```ts
it.each(['1,25', '1.25'])('draft accepts %s', async (s) => { await type(field, s); blur(); expect(onChange).toHaveBeenLastCalledWith(1.25); });
it.each(['abc', '5', '0,05'])('draft rejects %s with hint and no onChange', async (s) => {
  await type(field, s); blur(); expect(onChange).not.toHaveBeenCalled(); expect(screen.getByText(/Podaj wartość od 0,10 do 3,00/)).toBeInTheDocument();
});
it('preset chip pressed when value matches', () => expect(chip('Omega')).toHaveAttribute('aria-pressed', 'true'));
it('slider has aria-valuetext and markers from meta', () => {
  expect(slider).toHaveAttribute('aria-valuetext', '195,20 metra nad poziomem morza');
  expect(screen.getByText(/min\. obs\./)).toBeInTheDocument();
});
it('out-of-range warning is an alert with meta numbers', () => expect(screen.getByRole('alert')).toHaveTextContent('192,90–197,92'));
it('capacity mode shows converted level or out-of-table', () => { /* in_table true / false */ });
it('legend safe row shows draft + margin sum', () => expect(screen.getByText(/zanurzenie \+ zapas \(1,50 m\)/)).toBeInTheDocument());
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (layout, odstępy, rozmiary z `Main.dc.html` / `Mobile.dc.html`). **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(frontend): parameter panel and legend`

---

### Task 7: `MapPage` desktop, popup punktu i stany

**Files:**
- Create: `src/pages/MapPage.tsx`, `src/components/popup/PointPopup.tsx`, `src/components/states/*.tsx` (`LoadingSkeleton`, `RecalcPill`, `ErrorOverlay`, `OfflineBar`), `src/components/chrome/Footer.tsx`, `src/components/chrome/AppNav.tsx`, `src/vm/usePointVm.ts`, `src/vm/useMapPageVm.ts`
- Test: `src/components/popup/PointPopup.test.tsx`, `src/pages/MapPage.test.tsx` (MapView zamockowany jako atrapa), `src/vm/usePointVm.test.tsx`

**Interfaces:**
- Consumes: Task 4–6.
- Produces:
  - `useMapPageVm()`: składa `useMetaVm`, `useZonesVm`, `useCurrentLevelVm`, `useCapacityVm`, `usePointVm`, `useThemeVm`; stan UI: `h` (początkowo: `?h=` z URL, potem bieżący poziom z `/api/current-level`, potem `meta.defaults.h`; zawsze przycięty do `slider`), `draft` (`meta.defaults.draft`), `margin`, `mode`, `visible`, `basemap`, `pin`.
  - `usePointVm(pin, params)`: `{ popup?: PopupModel; status }`, gdzie `PopupModel = { variant: 'A' | 'B' | 'C' | 'D'; title: string; value: string; zone?: {name, label}; rows: {term, desc}[] }` — mapowanie `kind`: `model` → A („1,40–1,90 m”, „Pod kilem 0,20 do 0,70 m · wymagany zapas 0,30 m”, „Wysokość dna 193,55 m n.p.m. ± 0,25”, „Liczba scen”, „Położenie”), `always_water` → B („≥ 1,95 m”, „Głębiej niż … (poniżej najniższego zaobserwowanego stanu 192,90 m n.p.m.)”, „Dno < 193,05 m n.p.m.”, „Obserwacje: brak (zawsze woda)”), `land` → C („Ląd”, „Dno 0,20–0,60 m powyżej lustra wody przy …”, gdy `bottom_above_water_max` null → „Dno co najmniej 1,00 m powyżej lustra wody”), `outside` → D („Poza obszarem modelu”, „Model obejmuje czaszę zbiornika do rzędnej Max PP …”, „Bez oceny strefy”). Strefa z odpowiedzi API (`zone`), nigdy liczona na froncie. Dokładne sformułowania z `Popups.dc.html`.
  - `<PointPopup model onClose />` (`role="dialog"`, 300 px, przycisk zamknięcia `aria-label="Zamknij"`), zakotwiczony nad pinezką; bez popupu podpowiedź „Kliknij w wodę, aby sprawdzić głębokość”.
  - Stany: A `LoadingSkeleton` („Wczytuję model dna i strefy…”, `role="status"`); B `RecalcPill` („Przeliczam strefy dla 1,35 m…” z paskiem); C ostrzeżenie w panelu + włączona warstwa niepewności; D `ErrorOverlay` (mapa przygaszona, „Nie udało się przeliczyć stref”, opis ostatnich poprawnych parametrów, „Spróbuj ponownie”); E `OfflineBar` („Brak połączenia. Strefy z 10:42 mogą być nieaktualne.”, „Ponów”).
  - `Footer` (36 px, disclaimer po lewej, atrybucje po prawej), `AppNav` (logo SVG z makiety, „Mielizna”, „Jezioro Nyskie · gdzie przepłynę?”, linki Mapa / Historia linii brzegowych / O metodzie).
  - Layout desktop §16.2: panel 360 px (`top/left 16`, `bottom 52`, przewijany), kontrolki mapy prawy górny róg, legenda prawy dolny róg 308 px, skala „1 km”, pigułka u góry.

- [ ] **Step 1: Write the failing tests**
```ts
it.each([
  [pointModel, 'A', '1,40–1,90 m'], [pointAlwaysWater, 'B', '≥ 1,95 m'],
  [pointLand, 'C', 'Ląd'], [pointOutside, 'D', 'Poza obszarem modelu'],
])('popup variant from kind', (resp, variant, value) => {
  const m = toPopupModel(resp, meta); expect(m.variant).toBe(variant); expect(m.value).toBe(value);
  expect(JSON.stringify(m)).not.toMatch(/null|NaN|Infinity|undefined/);
});
it('initial h: ?h= beats current level beats meta default, clamped to slider', () => { /* trzy przypadki */ });
it('error state shows last good params and retry refetches', async () => { /* api.zones odrzuca → ErrorOverlay; klik „Spróbuj ponownie” → kolejne wywołanie */ });
it('offline bar shows time of last good zones', async () => { /* onlineManager false → „Strefy z HH:MM” */ });
it('changing draft re-requests zones and closes nothing else', async () => { /* … */ });
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS; `npm run lint && npm run build` → PASS.
- [ ] **Step 5:** Commit `feat(frontend): map page, point popup and states`

---

### Task 8: Układ mobile (< 768 px)

**Files:**
- Create: `src/components/mobile/MobileHeader.tsx`, `src/components/mobile/BottomSheet.tsx`, `src/vm/useViewport.ts`
- Modify: `src/pages/MapPage.tsx`
- Test: `src/components/mobile/BottomSheet.test.tsx`, `src/pages/MapPage.mobile.test.tsx`

**Interfaces:**
- Produces: `useViewport(): 'desktop' | 'mobile'` (`matchMedia('(min-width: 768px)')`); `MobileHeader` (logo, nazwa, ikony Historia / O metodzie z `aria-label`); `BottomSheet` zwinięty **290 px** (stepper zanurzenia −/+, skrót poziomu — tap rozwija, mini-legenda, linijka podsumowania) i rozwinięty **760 px** (pełne parametry, warstwy jako chipy, ustawienia zaawansowane, legenda, przycisk „Pokaż mapę”), `aria-expanded` na uchwycie; pasek disclaimera pod spodem. Te same komponenty panelu co desktop (Task 6), inny układ.

- [ ] **Step 1: Write the failing tests**
```ts
it('collapsed sheet shows draft stepper, level shortcut, mini legend and summary only', () => { /* … */ });
it('tapping level shortcut expands the sheet; „Pokaż mapę” collapses it', async () => { /* aria-expanded */ });
it('touch targets ≥ 44 px on mobile buttons', () => { /* computed min-height/min-width z CSS modułu lub inline */ });
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (wymiary z `Mobile.dc.html`, `MobileSheet.dc.html`). **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(frontend): mobile layout with bottom sheet`

---

### Task 9: Historia linii brzegowych (`/historia`)

**Files:**
- Create: `src/pages/HistoryPage.tsx`, `src/components/history/LevelChart.tsx`, `src/components/history/SceneList.tsx`, `src/components/history/SceneCard.tsx`, `src/vm/useHistoryVm.ts`
- Test: `src/vm/useHistoryVm.test.tsx`, `src/components/history/*.test.tsx`

**Interfaces:**
- Consumes: `api.scenes`, `api.shoreline`, `MapView` (z `shorelines`).
- Produces:
  - `useHistoryVm()`: `{ years: number[] (malejąco, z dat scen); year: number | 'all'; scenes: SceneRow[]; overlay: string[]; selected?: SceneRow; shorelines: FeatureCollection; counter: string ("12 scen · nałożone: 3"); setYear, toggleOverlay(date), select(date) }`; linie pobierane tylko dla nałożonych dat (`['shoreline', date]`); `SceneRow = {date, dateLabel, level, area, color, dashed}` (kolor wg skali 190,0 → 195,5 `#9CC9E4` → `#143F66`, `dashed` gdy `h_t < npp`).
  - `<LevelChart scenes npp />`: SVG ręcznie (bez biblioteki wykresów), poziom w czasie, linia NPP, kropki scen w kolorze poziomu, `aria-label` z opisem zakresu.
  - Lista: próbka koloru, data, poziom, powierzchnia km², checkbox „Nałóż na mapę”. Karta wybranej sceny: data, poziom, powierzchnia, „Sentinel-2 · zachm. 1,3%”, link „Ustaw ten poziom na mapie” → `/?h=<h_t>`.
  - Pusty stan: „Brak scen dla tego filtra” + „Pokaż wszystkie sceny”.

- [ ] **Step 1: Write the failing tests**
```ts
it('year filter and counter with Polish plural', () => { setYear(2026); expect(counter).toMatch(/^\d+ scen(a|y)? · nałożone: 0$/); });
it('overlay fetches only selected shorelines', () => { toggleOverlay('2026-10-20'); expect(api.shoreline).toHaveBeenCalledTimes(1); });
it('empty filter shows empty state with reset', () => { /* rok bez scen */ });
it('card link sets level on map', () => expect(link).toHaveAttribute('href', '/?h=194.2'));
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (układ z `History.dc.html`, lewy panel 400 px). **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(frontend): shoreline history page`

---

### Task 10: O metodzie (`/metoda`)

**Files:**
- Create: `src/pages/MethodPage.tsx`, `src/components/method/AreaLevelChart.tsx`, `src/components/method/AccuracyTiles.tsx`, `src/components/method/SourcesTable.tsx`, `src/vm/useMethodVm.ts`
- Test: `src/vm/useMethodVm.test.tsx`, `src/pages/MethodPage.test.tsx`

**Interfaces:**
- Consumes: `useMetaVm` (`area_level`, `accuracy`, `n_scenes`, `h_min_obs`, `h_max_obs`, `npp`, `max_pp`, `period_dates`).
- Produces:
  - Treść z `Method.dc.html` z poprawkami §16.9 obowiązującymi **dla stanu projektu po planie 2**: krok 03 — poziom z komunikatów RZGW (wariant B) i z krzywej powierzchnia–poziom (wariant C); kalibracja NMT (wariant A) jako „w przygotowaniu” (plan 4); krok 04 — przedziały zalania per piksel jako model podstawowy; interpolacja poziomic nie jest opisywana jako metoda.
  - `<AreaLevelChart points nodes npp maxPp />`: SVG rozrzut powierzchnia Otsu [km²] vs poziom [m n.p.m.], kolor kropek wg `h_method`, krzywa z węzłów, poziome linie NPP i Max PP.
  - `<AccuracyTiles />`: „Zgodność maski wody (OA)” = `rf_oa`, „Zrównoważona trafność (BA)” = `rf_ba` (z porównaniem do Otsu `otsu_ba`), „Liczba scen” = `n_scenes`, „Zakres poziomów” = `h_min_obs–h_max_obs`; kafel „RMSE dna” = „w przygotowaniu (porównanie z NMT LiDAR — plan 4)”. IoU z makiety zastąpione OA/BA (brief §16.9).
  - `SourcesTable`: Sentinel-2 (Copernicus, licencja), komunikaty Wody Polskie/RZGW, mapa KŻ Nysa (Wiktor Wróblewski, użycie niekomercyjne), OSM (ODbL), GUGiK (ortofotomapa).
  - Stopka: „Projekt na przedmiot Analiza Danych Przestrzennych, Politechnika Opolska · Paweł Ostromecki”.

- [ ] **Step 1: Write the failing tests**
```ts
it('accuracy tiles from meta, Polish numbers, RMSE pending', () => {
  expect(tile('Zgodność maski wody (OA)')).toHaveTextContent('81,6%');   // z fixture meta.accuracy.rf_oa = 0.8162
  expect(tile('RMSE dna')).toHaveTextContent(/w przygotowaniu/);
});
it('chart renders one dot per area_level point and NPP/Max PP lines', () => { /* liczba <circle>, dwie linie z aria-label */ });
it('step 03 mentions RZGW and the area–level curve, not only RZGW', () => { /* tekst */ });
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (kontener `max-width: 1120px`). **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(frontend): method page`

---

### Task 11: Przekrój end-to-end, zrzuty i notatka

**Files:**
- Create: `frontend/e2e/smoke.spec.ts`, `frontend/playwright.config.ts`, `docs/nauka/M6-frontend.md`, `docs/img/` (zrzuty)
- Modify: `README.md`, `docs/nauka/decyzje.md`

- [ ] **Step 1: Write the e2e test** (Playwright, `webServer`: backend `uv run uvicorn app.main:app --port 8000` z `MIELIZNA_LIVE=0` oraz `npm run build && npx vite preview --port 4173` z proxy `/api`; pomijany, gdy brak `data/processed/model/all/`):
```ts
test('zmiana zanurzenia przelicza strefy i podsumowanie', async ({ page }) => { /* / → czekaj na „bezpieczne X% akwenu”; +0,05 → pigułka → nowy procent */ });
test('klik w wodę otwiera popup z przedziałem głębokości', async ({ page }) => { /* klik w środek jeziora → role=dialog z „m” */ });
test('historia: nałożenie linii i „Ustaw ten poziom na mapie”', async ({ page }) => { /* … URL /?h= */ });
test('stan błędu przy wyłączonym API', async ({ page }) => { /* page.route('/api/zones*', abort) → „Nie udało się przeliczyć stref” */ });
```
- [ ] **Step 2:** Run `npx playwright test` → PASS (Chromium).
- [ ] **Step 3: Zrzuty do porównania z makietami:** 1440×900 i 390×844 (zwinięty i rozwinięty panel), jasny i ciemny (`colorScheme`), popup A, `/historia`, `/metoda` → `docs/img/m6-*.png`. Porównać z makietami w `docs/design/` (otwarte w przeglądarce) i zapisać w `M6-frontend.md` listę rozbieżności (każda: co, dlaczego zostaje albo poprawka w tym kroku). Sprawdzić też szwy między strefami (ruling R7 planu 2): jeśli widoczne przy zoomie 15, zapisać jako zadanie do backendu.
- [ ] **Step 4:** Napisać `docs/nauka/M6-frontend.md` (warstwy komponent → VM → Query → klient i po co; debounce + zaokrąglanie + cache; dlaczego reguła stref nie jest na froncie; obrazy w 3857 i `coordinates`; dostępność; pytania prowadzącego z odpowiedziami) i dopisać decyzje do `decyzje.md`; README: uruchomienie backend + frontend.
- [ ] **Step 5:** Run `npm test && npm run lint && npm run build` i `cd ../backend && uv run pytest -q` → PASS.
- [ ] **Step 6:** Commit `test(frontend): e2e smoke, screenshots and M6 notes`
