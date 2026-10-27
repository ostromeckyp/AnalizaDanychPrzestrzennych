# Mielizna (Jezioro Nyskie)

Model dna Jeziora Nyskiego budowany z obrazów Sentinel-2 (siatka wzorcowa EPSG:2180, 10 m),
wraz z backendem i frontendem do wizualizacji mielizn.

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
[`docs/nauka/`](docs/nauka/) — `M1-dane.md`, `M2-klasyfikacja.md`, `M3-poziomy.md`, `M4-model-dna.md`, `decyzje.md`.

## Dokumentacja

- Brief: [`docs/BRIEF.md`](docs/BRIEF.md)
- Spec: [`docs/superpowers/specs/2026-10-26-mielizna-design.md`](docs/superpowers/specs/2026-10-26-mielizna-design.md)
- Plan 1: [`docs/superpowers/plans/2026-10-27-plan1-pipeline-model-dna.md`](docs/superpowers/plans/2026-10-27-plan1-pipeline-model-dna.md)
