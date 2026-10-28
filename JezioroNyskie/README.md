# Mielizna (Jezioro Nyskie)

Model dna Jeziora Nyskiego budowany z obrazów Sentinel-2 (siatka wzorcowa EPSG:2180, 10 m),
wraz z backendem i frontendem do wizualizacji mielizn.

## Uruchomienie

Wymagany jest Docker Compose v2 oraz gotowe `data/processed/` i `data/reference/` (wynik pipeline'u; montowane tylko do odczytu).

```bash
docker compose up --build        # http://localhost:8080
docker compose down
bash scripts/compose_smoke.sh    # test dymny: buduje, sprawdza /, /api/meta, /historia i sprząta
```

Tryb na żywo (odświeżanie bieżącego poziomu z Sentinel-2, potrzebna sieć wychodząca) jest domyślnie włączony;
`MIELIZNA_LIVE=0` w pliku `.env` obok `docker-compose.yml` go wyłącza (plik jest w `.gitignore`). Port frontu: 8080.
Cache bieżącego poziomu leży w wolumenie Dockera (`/cache/current`, `MIELIZNA_CURRENT_DIR`), bo dane są montowane tylko do odczytu.

## Szybki start pipeline'u

```bash
cd pipeline
uv sync
uv run pytest
```

Konfiguracja: `pipeline/config.yaml` (bbox, siatka, okresy, filtr scen, ścieżki danych).
Dane surowe (`data/raw/`) i przetworzone (`data/processed/`) nie są w git; wyjątek: `data/raw/check/`.

## Pipeline krok po kroku

Wszystko z katalogu `pipeline/`. `make help` wypisuje cele. Make porównuje daty plików, więc `make bottom` na gotowych
danych niczego nie trenuje i nie pobiera (model dna liczy się tylko, gdy `07` ma coś do odświeżenia — wtedy ok. 20 s; bez zmian wejścia: „nothing to be done"). Wymuszenie kroku: `make -W ../data/reference/labels.gpkg rf` (albo `make clean-model rf`) lub ogólnie `make -W <plik> <cel>`.
(`make -B rf` nie działa: `04a` odmawia nadpisania etykiet.) Po edycji `exclude_dates` lub innych pól `config.yaml` uruchom
`make s2` (potem `make classify` itd. albo od razu `make bottom`): `config.yaml` jest zależnością `scenes_candidates.csv`, więc
zmiana kaskadowo odświeża dalsze kroki (`classify`, `shorelines`, `levels`, `bottom`), ale nie retrenuje RF: model RF zależy tylko od etykiet (`labels.gpkg`), już nie od CSV scen.
Retrening to godziny (ok. 550 dopasowań), więc wymuszaj go świadomie.

| cel | skrypt | wejście → wyjście (w `data/processed/`, o ile nie podano inaczej) |
|---|---|---|
| `make osm` | `03_fetch_osm.py` | Overpass → `lake.gpkg`, `marinas.gpkg` |
| `make s2` | `01_fetch_s2.py` | STAC Earth Search → `scenes_candidates.csv`, `s2/{data}.tif`, `scenes_pass2_rejected.csv` |
| `make label-candidates` (alias `labels`) | `04a_label_candidates.py` | → `../reference/labels.gpkg` (nie nadpisuje etykiet human) |
| `make label-ui` | `tools/label_server.py` | ręczne etykietowanie, http://localhost:8765 |
| `make rf` | `04b_train_rf.py` | etykiety + sceny → `model/rf_model.joblib`, `rf_metrics.json`, `rf_report.md` |
| `make classify` | `04_classify.py` | → `masks/`, `masks_otsu/`, `proba/`, `classify_stats.csv` |
| `make shorelines` | `05_shorelines.py` | → `shorelines.gpkg`, `qc/*.png` |
| `make bulletins` | `06a_fetch_bulletins.py` | komunikaty RZGW → `bulletins.csv` |
| `make levels` | `06_water_levels.py` | → `scenes.json`, `model/area_level_curve.json` |
| `make bottom` | `07_bottom_model.py` | → `model/{all,pre_flood,post_flood}/bottom_*.tif`, `model_meta.json` |
| `make all` | wszystkie po kolei | staje przed `rf`, jeśli < 150 ręcznych etykiet klas |
| `make test` | `pytest -q` | 182 testów |

Dane surowe w `data/raw/`, logi w `data/processed/logs/`. Notatki do nauki (po polsku, z pytaniami obronnymi):
[`docs/nauka/`](docs/nauka/) — `M1-dane.md`, `M2-klasyfikacja.md`, `M3-poziomy.md`, `M4-model-dna.md`, `M5-backend.md`, `M6-frontend.md`, `decyzje.md`.

## Backend

API FastAPI serwujące produkty pipeline'u (`backend/`, pakiet `app`; pipeline `mielizna` jako zależność lokalna).

```bash
cd backend && uv sync && uv run pytest        # testy na syntetycznym zbiorze danych
uv run uvicorn app.main:app                   # uruchomienie (http://127.0.0.1:8000/docs)
uv run pytest -m real -q                      # testy na prawdziwych danych (wymagają data/processed/model/all/)
```

Zmienne środowiskowe: `MIELIZNA_DATA_DIR` (katalog danych), `MIELIZNA_PERIOD` (domyślnie `all`),
`MIELIZNA_LIVE` (`0` wyłącza tryb na żywo), `MIELIZNA_REFRESH_H`, `MIELIZNA_FRESH_DAYS`.

## Frontend

Pełne uruchomienie (dwa terminale): `cd backend && uv run uvicorn app.main:app --port 8000`, potem `cd frontend && npm ci && npm run dev`
i otwórz http://localhost:5173 (`MIELIZNA_LIVE=0` wyłącza odświeżanie poziomu z sieci).

React + TypeScript + Vite (`frontend/`), MapLibre GL, TanStack Query. Typy API generowane z `backend/openapi.json`.

```bash
cd frontend && npm ci
npm run dev        # http://localhost:5173, proxy /api -> http://localhost:8000
npm test           # Vitest (w tym test architektury warstw)
npm run lint && npm run build
npm run e2e        # Playwright (Chromium): sam stawia backend i vite preview; wymaga data/processed/model/all/
SCREENSHOTS=1 npx playwright test e2e/screenshots.spec.ts   # zrzuty do docs/img/m6-*.png
npm run gen:api    # odświeża src/api/schema.ts po zmianie openapi.json
```

## Dokumentacja

- Brief: [`docs/BRIEF.md`](docs/BRIEF.md)
- Spec: [`docs/superpowers/specs/2026-10-26-mielizna-design.md`](docs/superpowers/specs/2026-10-26-mielizna-design.md)
- Plan 1: [`docs/superpowers/plans/2026-10-27-plan1-pipeline-model-dna.md`](docs/superpowers/plans/2026-10-27-plan1-pipeline-model-dna.md)
