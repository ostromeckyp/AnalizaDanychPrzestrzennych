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
    """PNG z wycinkiem sceny wokół piksela: kolory naturalne | false-color, z krzyżykiem w środku.

    Co robi: czyta okno 64x64 px wokół (row, col), buduje dwa panele (RGB oraz SWIR16/NIR/G),
      powiększa je 4x i rysuje czerwony krzyżyk z przerwą na środku; brzegi poza rastrem są czarne.
    Dlaczego tak: false-color SWIR16/NIR/G odróżnia wodę od lądu tam, gdzie RGB jest niejednoznaczny
      (płycizny, szuwary); przerwa w krzyżyku nie zasłania etykietowanego piksela.
    Wejście → wyjście: ścieżka COG, wiersz i kolumna piksela → bajty PNG (512 x 256 px przy 4x).
    Jak to obronić: wycinek pochodzi z tego samego COG i tej samej siatki co dane modelu, a
      kolejność pasm bierze z `BAND_INDEX` (zgodnie z `BANDS` zapisanym w 01_fetch_s2.py).
    """
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
        out = {"done": done, "total": len(shore), "id": None,
               "n_class": len(L.human_class_labels(self.gdf))}
        if len(todo):
            p = todo.iloc[0]
            lon, lat = _TO_WGS84.transform(p.x, p.y)
            out.update(id=int(p.id), date=str(p.date), x=float(p.x), y=float(p.y), lon=lon, lat=lat)
        return out

    def _update(self, pid: int, label: str | None, source: str) -> bool:
        """Zmienia etykietę na kopii, zapisuje plik i dopiero potem podmienia stan w pamięci."""
        with self.lock:
            hit = self.gdf.id == pid
            if not hit.any():
                return False
            new = self.gdf.copy()
            new.loc[hit, "label"] = label
            new.loc[hit, "source"] = source
            new["label"] = new["label"].astype(object).where(new["label"].notna(), None)
            L.save(new, self.path)
            self.gdf = new
            return True

    def set_label(self, pid: int, label: str) -> bool:
        return self._update(pid, label, "human")

    def unlabel(self, pid: int) -> bool:
        """Cofa etykietę punktu do stanu początkowego (label=None, source="auto")."""
        return self._update(pid, None, "auto")


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
            if self.path not in ("/api/label", "/api/unlabel"):
                return self._json({"error": "nie znaleziono"}, 404)
            is_label = self.path == "/api/label"
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                pid = int(body["id"])
                label = body["label"] if is_label else None
            except (ValueError, KeyError, TypeError):
                return self._json({"error": "oczekiwano {id, label}" if is_label else "oczekiwano {id}"}, 400)
            if is_label and label not in VALID_LABELS:
                return self._json({"error": f"label musi być jednym z {sorted(VALID_LABELS)}"}, 400)
            try:
                ok = state.set_label(pid, label) if is_label else state.unlabel(pid)
            except OSError as e:
                return self._json({"error": f"zapis nieudany: {e}"}, 500)
            if not ok:
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
