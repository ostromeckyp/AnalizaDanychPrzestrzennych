import json
from pathlib import Path

OPENAPI = Path(__file__).resolve().parents[1] / "openapi.json"


def test_openapi_snapshot_is_current(app):
    assert json.loads(OPENAPI.read_text("utf-8")) == app.openapi()
