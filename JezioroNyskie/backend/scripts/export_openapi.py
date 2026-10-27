"""Zapisuje `backend/openapi.json` - migawkę kontraktu API dla frontu.

Co robi: buduje aplikację (produkty ładowane leniwie, więc dane nie są potrzebne) i zapisuje `app.openapi()`.
Dlaczego tak: front generuje typy z tego pliku; test `test_openapi.py` pilnuje, by był aktualny.
Wejście → wyjście: brak → plik `backend/openapi.json`.
Jak to obronić: format `json.dumps(indent=1, ensure_ascii=False)` jest identyczny z tym, który porównuje test.
Uruchomienie: `cd backend && uv run python scripts/export_openapi.py`.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import create_app  # noqa: E402

if __name__ == "__main__":
    (ROOT / "openapi.json").write_text(
        json.dumps(create_app().openapi(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
