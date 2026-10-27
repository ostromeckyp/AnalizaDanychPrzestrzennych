"""Lokalny serwer do ręcznego etykietowania punktów brzegowych (woda / ląd / pomiń).

Co robi: serwuje stronę label.html i małe API JSON/PNG: następny nieoznaczony punkt `shore`,
  wycinek sceny Sentinel-2 (RGB i false-color SWIR16/NIR/G, 4x, krzyżyk na środku) oraz zapis
  etykiety od razu do pliku labels.gpkg.
Dlaczego tak: stdlib `http.server` nie wymaga żadnych zależności ani budowania frontendu;
  zapis po każdym kliknięciu (atomowo) oznacza, że można przerwać pracę w dowolnym momencie.
  Etykieta „skip” trafia do pliku, żeby punkt nie wracał w kolejce.
Wejście → wyjście: data/reference/labels.gpkg + data/processed/s2/{data}.tif → http://localhost:8765.
Jak to obronić: etykieta jest decyzją człowieka (source=human) na podstawie obrazu z daty sceny
  i ortofotomapy; model nigdy nie widzi ortofotomapy, tylko ją porównuje autor.
"""
import io
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import matplotlib.image
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.windows import Window

from mielizna import labels as L
from mielizna.config import data_path

HTML = Path(__file__).with_name("label.html")
CROP_PX = 64
ZOOM = 4
VALID_LABELS = {"water", "land", "skip"}
BAND_INDEX = {"blue": 1, "green": 2, "red": 3, "nir": 4, "swir16": 5}  # numery pasm w COG (od 1)
_TO_WGS84 = Transformer.from_crs(2180, 4326, always_xy=True)


def _stretch(a: np.ndarray, hi: float) -> np.ndarray:
    return np.clip(np.nan_to_num(a, nan=0.0) / hi, 0, 1) ** (1 / 1.5)


def render_crop(tif: Path, row: int, col: int) -> bytes:
    """PNG: wycinek 64x64 px wokół piksela, RGB | false-color (SWIR16, NIR, G), 4x, krzyżyk w środku.

    Brzegi poza rastrem są dopełnione NaN (czarne). Krzyżyk ma przerwę na środku, żeby nie
    zasłaniać etykietowanego piksela."""
    half = CROP_PX // 2
    win = Window(col - half, row - half, CROP_PX, CROP_PX)
    with rasterio.open(tif) as ds:
        arr = ds.read(list(BAND_INDEX.values()), window=win, boundless=True, fill_value=np.nan)
    b, g, r, nir, s1 = arr
    rgb = np.dstack([_stretch(r, 0.2), _stretch(g, 0.2), _stretch(b, 0.2)])
    fc = np.dstack([_stretch(s1, 0.4), _stretch(nir, 0.5), _stretch(g, 0.2)])
    panels = []
    for img in (rgb, fc):
        big = np.kron(img, np.ones((ZOOM, ZOOM, 1)))
        c = half * ZOOM + ZOOM // 2
        gap = 2 * ZOOM
        big[c, : c - gap] = big[c, c + gap:] = (1, 0, 0)
        big[: c - gap, c] = big[c + gap:, c] = (1, 0, 0)
        panels.append(big)
    buf = io.BytesIO()
    matplotlib.image.imsave(buf, np.hstack(panels), format="png")
    return buf.getvalue()


class _State:
    def __init__(self, labels_path: Path, s2_dir: Path):
        self.path, self.s2_dir = Path(labels_path), Path(s2_dir)
        self.lock = threading.Lock()
        self.gdf = L.load(self.path)

    def next_point(self) -> dict:
        shore = self.gdf[self.gdf.stratum == "shore"]
        done = int(shore.label.notna().sum())
        todo = shore[shore.label.isna()]
        out = {"done": done, "total": len(shore), "id": None}
        if len(todo):
            p = todo.iloc[0]
            lon, lat = _TO_WGS84.transform(p.x, p.y)
            out.update(id=int(p.id), date=str(p.date), x=float(p.x), y=float(p.y), lon=lon, lat=lat)
        return out

    def set_label(self, pid: int, label: str) -> bool:
        with self.lock:
            hit = self.gdf.id == pid
            if not hit.any():
                return False
            self.gdf.loc[hit, "label"] = label
            self.gdf.loc[hit, "source"] = "human"
            L.save(self.gdf, self.path)
            return True


def make_handler(state: _State):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/next":
                with state.lock:
                    self._json(state.next_point())
            elif m := re.fullmatch(r"/api/crop/(\d+)\.png", path):
                with state.lock:
                    hit = state.gdf[state.gdf.id == int(m[1])]
                if hit.empty:
                    return self._json({"error": "nieznane id"}, 404)
                p = hit.iloc[0]
                tif = state.s2_dir / f"{p.date}.tif"
                self._send(200, render_crop(tif, int(p.row), int(p.col)), "image/png")
            else:
                self._json({"error": "nie znaleziono"}, 404)

        def do_POST(self):
            if self.path != "/api/label":
                return self._json({"error": "nie znaleziono"}, 404)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                pid, label = int(body["id"]), body["label"]
            except (ValueError, KeyError, TypeError):
                return self._json({"error": "oczekiwano {id, label}"}, 400)
            if label not in VALID_LABELS:
                return self._json({"error": f"label musi być jednym z {sorted(VALID_LABELS)}"}, 400)
            if not state.set_label(pid, label):
                return self._json({"error": "nieznane id"}, 404)
            self._json({"ok": True})

        def log_message(self, *args):
            pass

    return Handler


def serve(port: int = 8765, labels_path: Path | None = None, s2_dir: Path | None = None) -> HTTPServer:
    """Tworzy serwer (nie uruchamia pętli): wywołujący robi `serve_forever()`; port 0 = losowy."""
    labels_path = labels_path or data_path("reference", "labels.gpkg")
    s2_dir = s2_dir or data_path("processed", "s2")
    return HTTPServer(("127.0.0.1", port), make_handler(_State(labels_path, s2_dir)))


if __name__ == "__main__":
    srv = serve()
    print(f"Etykietowanie: http://localhost:{srv.server_address[1]}  (Ctrl+C kończy)", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
