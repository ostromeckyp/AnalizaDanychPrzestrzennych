"""Wczytywanie konfiguracji i ścieżek danych."""
from pathlib import Path

import yaml

PIPELINE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PIPELINE_DIR.parent / "data"
DEFAULT_CONFIG = PIPELINE_DIR / "config.yaml"


def load_config(path: Path | None = None) -> dict:
    """Wczytuje config.yaml (domyślnie pipeline/config.yaml) jako słownik."""
    with open(path or DEFAULT_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def data_path(kind: str, *parts) -> Path:
    """Ścieżka w katalogu danych; kind ∈ {raw, processed, reference}."""
    paths = load_config()["paths"]
    if kind not in paths:
        raise ValueError(f"Nieznany rodzaj ścieżki: {kind!r}; dozwolone: {sorted(paths)}")
    return DATA_DIR.joinpath(paths[kind], *map(str, parts))
