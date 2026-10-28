"""Ustawienia backendu czytane ze zmiennych środowiskowych.

Co robi: zbiera konfigurację (katalog danych, okres modelu, tryb „na żywo", odświeżanie) w jednym
  niemutowalnym obiekcie.
Dlaczego tak: jedno miejsce czytania `os.environ` ułatwia testy (podmiana env) i obronę - widać
  wszystkie pokrętła systemu na jednym ekranie.
Wejście → wyjście: zmienne MIELIZNA_DATA_DIR, MIELIZNA_PERIOD, MIELIZNA_LIVE ("0" wyłącza),
  MIELIZNA_REFRESH_H, MIELIZNA_FRESH_DAYS → `Settings`; `get_settings()` czyta env przy każdym wywołaniu.
Jak to obronić: domyślny katalog danych to ten sam, którego używa pipeline (`mielizna.config.data_dir()`),
  więc backend i pipeline nie mogą wskazywać różnych danych.
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from mielizna.config import data_dir as _pipeline_data_dir


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=_pipeline_data_dir)
    period: str = "all"
    live: bool = True
    refresh_hours: float = 6
    fresh_days: int = 10


PERIODS = ("all", "pre_flood", "post_flood")


def period_from_model_choice(data_dir: Path) -> str | None:
    """Okres z `processed/eval/model_choice.json` (decyzja oceny zmian dna) albo None, gdy pliku/wartości brak."""
    try:
        period = json.loads((Path(data_dir) / "processed" / "eval" / "model_choice.json").read_text(encoding="utf-8")).get("period")
    except (OSError, ValueError, AttributeError):
        return None
    return period if period in PERIODS else None


def get_settings() -> Settings:
    """Buduje `Settings` z bieżącego środowiska. Okres: `MIELIZNA_PERIOD` wygrywa, potem `model_choice.json`, potem `all`."""
    env = os.environ
    data_dir = Path(env["MIELIZNA_DATA_DIR"]) if env.get("MIELIZNA_DATA_DIR") else _pipeline_data_dir()
    return Settings(
        data_dir=data_dir,
        period=env.get("MIELIZNA_PERIOD") or period_from_model_choice(data_dir) or "all",
        live=env.get("MIELIZNA_LIVE", "1") != "0",
        refresh_hours=float(env.get("MIELIZNA_REFRESH_H", 6)),
        fresh_days=int(env.get("MIELIZNA_FRESH_DAYS", 10)),
    )
