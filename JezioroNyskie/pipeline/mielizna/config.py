"""Wczytywanie konfiguracji i ścieżek danych."""
import os
from pathlib import Path

import yaml

PIPELINE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PIPELINE_DIR.parent / "data"
DEFAULT_CONFIG = PIPELINE_DIR / "config.yaml"


# Części konfiguracji w osobnych plikach obok config.yaml (klucz najwyższego poziomu = nazwa części). Osobno, bo config.yaml
# jest zależnością make łańcucha S2 -> klasyfikacja -> model; strojenie KŻ lub LiDAR nie może go unieważniać.
PART_CONFIGS = ("config_lidar.yaml", "config_kz.yaml")


def load_config(path: Path | None = None) -> dict:
    """Wczytuje config.yaml (domyślnie pipeline/config.yaml) i dołącza części obok niego (config_lidar.yaml, config_kz.yaml).

    Wynik to jeden słownik (cfg["kz"], cfg["lidar"] jak dawniej). Brak pliku części jest dozwolony; ten sam klucz najwyższego
    poziomu w dwóch plikach to błąd (ValueError), żeby nie było cichego nadpisania."""
    path = Path(path or DEFAULT_CONFIG)
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    for name in PART_CONFIGS:
        part_path = path.parent / name
        if not part_path.exists():
            continue
        with open(part_path, encoding="utf-8") as f:
            part = yaml.safe_load(f) or {}
        dup = sorted(set(part) & set(cfg))
        if dup:
            raise ValueError(f"{part_path.name}: klucze {dup} są już w {path.name}")
        cfg.update(part)
    return cfg


def data_dir() -> Path:
    """Katalog danych: `MIELIZNA_DATA_DIR`, jeśli ustawiona (czytana przy każdym wywołaniu), inaczej `DATA_DIR`."""
    env = os.environ.get("MIELIZNA_DATA_DIR")
    return Path(env) if env else DATA_DIR


def data_path(kind: str, *parts) -> Path:
    """Ścieżka w katalogu danych; kind ∈ {raw, processed, reference}."""
    paths = load_config()["paths"]
    if kind not in paths:
        raise ValueError(f"Nieznany rodzaj ścieżki: {kind!r}; dozwolone: {sorted(paths)}")
    return data_dir().joinpath(paths[kind], *map(str, parts))
