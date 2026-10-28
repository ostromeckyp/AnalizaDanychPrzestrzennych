"""Test trybu /kz serwera kontroli rzędnych: kolejka warstwowa, zapis CSV, walidacja, brak regresji trybu brzegu."""
import csv
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import label_server  # noqa: E402


def _setup(tmp_path):
    n = 12
    df = pd.DataFrame({"id": range(n), "z": 188.0 + np.arange(n) / 10, "color": "blue", "conf": 90.0,
                       "color_ok": [i >= 4 for i in range(n)], "px": 100.0 + 5 * np.arange(n), "py": 80.0,
                       "text": "188,0"})            # ids 0..3 podejrzane (color_ok == False)
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.px, df.py), crs="EPSG:2180")
    ocr = tmp_path / "ocr.gpkg"
    gdf.to_file(ocr, driver="GPKG")
    Image.fromarray(np.full((200, 400, 3), 220, np.uint8)).save(tmp_path / "map.png")
    srv = label_server.serve(port=0, kz=True, kz_paths={"ocr": ocr, "qc": tmp_path / "qc.csv", "image": tmp_path / "map.png"})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e:
        return e.code


def test_kz_mode_end_to_end(tmp_path):
    srv, base = _setup(tmp_path)
    try:
        assert "rzędnych KŻ" in urllib.request.urlopen(base + "/kz").read().decode()
        png = urllib.request.urlopen(base + "/api/kz/crop/5.png").read()
        assert png[:4] == b"\x89PNG" and Image.open(__import__("io").BytesIO(png)).size == (600, 600)
        first = json.load(urllib.request.urlopen(base + "/api/kz/next"))
        assert first["target"] == 12 and first["total"] == 12      # populacja < 200: cel = wszystkie punkty
        seen = []
        for k in range(6):
            p = json.load(urllib.request.urlopen(base + "/api/kz/next"))
            seen.append(p["suspect"])
            assert _post(base + "/api/kz/qc", {"id": p["id"], "qc": "ok"}) == 200
        assert seen == [True, False] * 3                      # warstwy na przemian
        done = {int(x["id"]) for x in csv.DictReader(open(tmp_path / "qc.csv"))}
        c, r, k, x = [i for i in range(12) if i not in done][:4]
        assert _post(base + "/api/kz/qc", {"id": c, "qc": "corrected", "z_qc": 190.4}) == 200
        assert _post(base + "/api/kz/qc", {"id": r, "qc": "rejected"}) == 200
        assert _post(base + "/api/kz/qc", {"id": k, "qc": "skip"}) == 200
        assert _post(base + "/api/kz/qc", {"id": x, "qc": "corrected"}) == 400            # brak z_qc
        assert _post(base + "/api/kz/qc", {"id": x, "qc": "corrected", "z_qc": 250}) == 400
        assert _post(base + "/api/kz/qc", {"id": x, "qc": "ok", "z_qc": 190.0}) == 400
        assert _post(base + "/api/kz/qc", {"id": x, "qc": "maybe"}) == 400
        assert _post(base + "/api/kz/qc", {"id": 999, "qc": "ok"}) == 404
        assert _post(base + "/api/kz/undo", {"id": k}) == 200
        rows = list(csv.DictReader(open(tmp_path / "qc.csv")))
        assert list(rows[0]) == ["id", "ocr_z", "qc", "z_qc"] and len(rows) == 8
        assert {r["id"]: r["qc"] for r in rows}[str(c)] == "corrected" and str(k) not in {r["id"] for r in rows}
        # stan odtwarzany z pliku po restarcie
        st = label_server._KzState(tmp_path / "ocr.gpkg", tmp_path / "qc.csv", tmp_path / "map.png")
        assert len(st.rows) == 8 and st.next_point()["id"] not in st.rows
        # tryb brzegu nie jest ładowany w trybie --kz
        try:
            urllib.request.urlopen(base + "/api/next")
            raise AssertionError("oczekiwano 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()
