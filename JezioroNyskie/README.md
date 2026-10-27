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

## Dokumentacja

- Brief: [`docs/BRIEF.md`](docs/BRIEF.md)
- Spec: [`docs/superpowers/specs/2026-10-26-mielizna-design.md`](docs/superpowers/specs/2026-10-26-mielizna-design.md)
- Plan 1: [`docs/superpowers/plans/2026-10-27-plan1-pipeline-model-dna.md`](docs/superpowers/plans/2026-10-27-plan1-pipeline-model-dna.md)
