import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_current_level_offline(client):
    r = client.get("/api/current-level")
    assert r.status_code == 200 and r.json()["source"] == "pipeline" and "stale" in r.json()
    assert r.headers["cache-control"] == "no-cache"
    assert r.json()["refreshing"] is False


def test_background_task_survives_exception(products, tmp_path):
    n = {"calls": 0}

    def flaky(a, b):
        n["calls"] += 1
        raise RuntimeError("boom")
    app = create_app(Settings(data_dir=tmp_path, live=True, refresh_hours=0.00002), products, search_fn=flaky)
    with TestClient(app) as c:                     # 0.00002 h = 0,072 s między odświeżeniami
        time.sleep(0.3)
        r = c.get("/api/current-level")
        assert r.status_code == 200 and "boom" in r.json()["last_error"]
    assert n["calls"] >= 2
