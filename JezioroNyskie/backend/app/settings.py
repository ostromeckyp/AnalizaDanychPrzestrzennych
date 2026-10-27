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


def get_settings() -> Settings:
    """Buduje `Settings` z bieżącego środowiska (wartości domyślne, gdy zmiennej brak)."""
    env = os.environ
    return Settings(
        data_dir=Path(env["MIELIZNA_DATA_DIR"]) if env.get("MIELIZNA_DATA_DIR") else _pipeline_data_dir(),
        period=env.get("MIELIZNA_PERIOD", "all"),
        live=env.get("MIELIZNA_LIVE", "1") != "0",
        refresh_hours=float(env.get("MIELIZNA_REFRESH_H", 6)),
        fresh_days=int(env.get("MIELIZNA_FRESH_DAYS", 10)),
    )
