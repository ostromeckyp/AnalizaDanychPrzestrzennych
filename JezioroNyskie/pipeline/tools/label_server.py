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

Tryb /kz (K2): kontrola ręczna rzędnych odczytanych OCR-em z mapy KŻ (http://localhost:8765/kz).
  Jeden punkt naraz: wycinek mapy 200 x 200 px (3x) z krzyżykiem na kotwicy i odczytana liczba; klawisze:
  Enter = poprawne, liczba + Enter = korekta, X = to nie jest rzędna, ? = pomiń, Backspace = cofnij.
  Kolejka: losowa (ziarno stałe), naprzemiennie z warstwy „podejrzane” (color_ok == False lub conf < 80)
  i „zwykłe”, więc próba jest warstwowa; wynik w data/reference/kz_spot_qc.csv (id, ocr_z, qc, z_qc),
  zapisywany po każdym kliknięciu. Mapa KŻ: warunki w data/reference/KZ_ZRODLO_I_WARUNKI.md.
  Uruchomienie: `python tools/label_server.py --kz` (cel `make kz-qc-ui`); bez flagi działa etykietowanie brzegu.
"""
import argparse
import csv
import io
import json
import os
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
KZ_HTML = Path(__file__).with_name("kz.html")
KZ_CROP_PX = 200
KZ_ZOOM = 3
KZ_QC_VALUES = {"ok", "corrected", "rejected", "skip"}
KZ_Z_RANGE = (185.0, 200.0)
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
        """Następny punkt: najpierw do przeglądu (`review`), potem shore, potem shore_low.

        Stara etykieta (`label_v1`) nigdy nie trafia do odpowiedzi – ocena ma być ślepa.
        """
        pool = self.gdf[self.gdf.stratum.isin(L.HUMAN_STRATA)]
        todo = pool[pool.label.isna()]
        n_review = int(todo.review.sum())
        out = {"done": int(pool.label.notna().sum()), "total": len(pool), "id": None,
               "n_class": len(L.human_class_labels(self.gdf)), "n_review": n_review}
        if len(todo):
            rank = todo.review.map({True: 0, False: 1}) * 10 + todo.stratum.map(
                {s: i for i, s in enumerate(L.HUMAN_STRATA)})
            p = todo.loc[rank.sort_values(kind="stable").index[0]]
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


def render_kz_crop(img, px: float, py: float) -> bytes:
    """PNG: wycinek 200 x 200 px mapy KŻ wokół kotwicy, powiększony 3x, z czerwonym krzyżykiem (przerwa w środku)."""
    from PIL import Image, ImageDraw

    half = KZ_CROP_PX // 2
    x0, y0 = int(round(px)) - half, int(round(py)) - half
    crop = img.crop((x0, y0, x0 + KZ_CROP_PX, y0 + KZ_CROP_PX)).resize(
        (KZ_CROP_PX * KZ_ZOOM, KZ_CROP_PX * KZ_ZOOM), Image.NEAREST)
    d = ImageDraw.Draw(crop)
    cx, cy, gap, arm = (px - x0) * KZ_ZOOM, (py - y0) * KZ_ZOOM, 8, 40
    for seg in (((cx - gap - arm, cy), (cx - gap, cy)), ((cx + gap, cy), (cx + gap + arm, cy)),
                ((cx, cy - gap - arm), (cx, cy - gap)), ((cx, cy + gap), (cx, cy + gap + arm))):
        d.line(list(seg), fill=(255, 0, 0), width=2)
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return buf.getvalue()


class _KzState:
    """Stan trybu /kz: punkty OCR (gpkg), plik QC (csv) i obraz mapy; zapis atomowy po każdej ocenie."""

    COLUMNS = ["id", "ocr_z", "qc", "z_qc"]

    def __init__(self, ocr_path: Path, qc_path: Path, image_path: Path, seed: int = 0):
        import geopandas as gpd
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        self.qc_path = Path(qc_path)
        self.lock = threading.Lock()
        self.ocr = gpd.read_file(ocr_path).drop(columns="geometry").set_index("id", drop=False)
        self.suspect = (~self.ocr.color_ok.astype(bool)) | (self.ocr.conf < 80)
        order = np.random.default_rng(seed).permutation(self.ocr.index.to_numpy())
        self.order = {True: [i for i in order if self.suspect[i]], False: [i for i in order if not self.suspect[i]]}
        self.image = Image.open(image_path).convert("RGB")
        self.rows: dict[int, dict] = {}
        if self.qc_path.exists():
            with open(self.qc_path, newline="") as f:
                for r in csv.DictReader(f):
                    self.rows[int(r["id"])] = r

    def _save(self, rows: dict):
        self.qc_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.qc_path.with_suffix(".tmp")
        with open(tmp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.COLUMNS)
            w.writeheader()
            w.writerows(rows.values())
        os.replace(tmp, self.qc_path)

    def next_point(self) -> dict:
        """Następny nieoceniony punkt; warstwy na przemian (najpierw ta z mniejszą liczbą ocen, remis = podejrzane)."""
        done = {h: sum(1 for i in self.rows if bool(self.suspect.get(int(i), False)) == h) for h in (True, False)}
        out = {"done": sum(1 for r in self.rows.values() if r["qc"] != "skip"), "total": len(self.ocr),
               "n_suspect_done": done[True], "n_regular_done": done[False], "id": None}
        for h in sorted((True, False), key=lambda h: (done[h], not h)):
            todo = [i for i in self.order[h] if i not in self.rows]
            if todo:
                p = self.ocr.loc[todo[0]]
                out.update(id=int(p.id), z=float(p.z), conf=float(p.conf), color=str(p.color),
                           suspect=bool(h), text=str(p.text))
                break
        return out

    def record(self, pid: int, qc: str, z_qc: float | None) -> bool:
        with self.lock:
            if pid not in self.ocr.index:
                return False
            rows = dict(self.rows)
            rows[pid] = {"id": pid, "ocr_z": float(self.ocr.loc[pid, "z"]), "qc": qc,
                         "z_qc": "" if z_qc is None else z_qc}
            self._save(rows)
            self.rows = rows
            return True

    def undo(self, pid: int) -> bool:
        with self.lock:
            if pid not in self.rows:
                return False
            rows = {k: v for k, v in self.rows.items() if k != pid}
            self._save(rows)
            self.rows = rows
            return True

    def crop(self, pid: int) -> bytes | None:
        if pid not in self.ocr.index:
            return None
        p = self.ocr.loc[pid]
        return render_kz_crop(self.image, float(p.px), float(p.py))


def make_handler(state: _State | None, kz_state: _KzState | None = None):
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
            if path == "/kz" and kz_state is not None:
                self._send(200, KZ_HTML.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/kz/next" and kz_state is not None:
                with kz_state.lock:
                    self._json(kz_state.next_point())
            elif (m := re.fullmatch(r"/api/kz/crop/(\d+)\.png", path)) and kz_state is not None:
                png = kz_state.crop(int(m[1]))
                if png is None:
                    return self._json({"error": "nieznane id"}, 404)
                self._send(200, png, "image/png")
            elif state is None and path in ("/", "/api/next") or state is None and path.startswith("/api/crop/"):
                self._json({"error": "tryb etykietowania brzegu wyłączony (uruchomiono z --kz)"}, 404)
            elif path == "/":
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

        def _post_kz(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                pid = int(body["id"])
                if self.path == "/api/kz/undo":
                    ok = kz_state.undo(pid)
                    return self._json({"ok": True}) if ok else self._json({"error": "brak oceny"}, 404)
                qc = body["qc"]
                z_qc = body.get("z_qc")
                z_qc = None if z_qc is None else float(z_qc)
            except (ValueError, KeyError, TypeError):
                return self._json({"error": "oczekiwano {id, qc[, z_qc]}"}, 400)
            if qc not in KZ_QC_VALUES:
                return self._json({"error": f"qc musi być jednym z {sorted(KZ_QC_VALUES)}"}, 400)
            if (qc == "corrected") != (z_qc is not None):
                return self._json({"error": "z_qc wymagane tylko dla qc=corrected"}, 400)
            if z_qc is not None and not KZ_Z_RANGE[0] <= z_qc <= KZ_Z_RANGE[1]:
                return self._json({"error": f"z_qc poza zakresem {KZ_Z_RANGE}"}, 400)
            try:
                ok = kz_state.record(pid, qc, z_qc)
            except OSError as e:
                return self._json({"error": f"zapis nieudany: {e}"}, 500)
            self._json({"ok": True}) if ok else self._json({"error": "nieznane id"}, 404)

        def do_POST(self):
            if self.path in ("/api/kz/qc", "/api/kz/undo") and kz_state is not None:
                return self._post_kz()
            if state is None or self.path not in ("/api/label", "/api/unlabel"):
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


def serve(port: int = 8765, labels_path: Path | None = None, s2_dir: Path | None = None,
          kz: bool = False, kz_paths: dict | None = None) -> HTTPServer:
    """Tworzy serwer (nie uruchamia pętli): wywołujący robi `serve_forever()`; port 0 = losowy.

    `kz=True` włącza tylko tryb /kz (bez ładowania etykiet brzegu); `kz_paths` nadpisuje ścieżki testowo."""
    if kz:
        kp = {"ocr": data_path("processed", "kz", "kz_spot_ocr.gpkg"), "qc": data_path("reference", "kz_spot_qc.csv"),
              "image": data_path("raw", "kz", "kz_full.png"), **(kz_paths or {})}
        return HTTPServer(("127.0.0.1", port), make_handler(None, _KzState(kp["ocr"], kp["qc"], kp["image"])))
    labels_path = labels_path or data_path("reference", "labels.gpkg")
    s2_dir = s2_dir or data_path("processed", "s2")
    return HTTPServer(("127.0.0.1", port), make_handler(_State(labels_path, s2_dir)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kz", action="store_true", help="kontrola rzędnych OCR z mapy KŻ zamiast etykietowania brzegu")
    args = ap.parse_args()
    srv = serve(kz=args.kz)
    port = srv.server_address[1]
    print(f"Kontrola KŻ: http://localhost:{port}/kz  (Ctrl+C kończy)" if args.kz
          else f"Etykietowanie: http://localhost:{port}  (Ctrl+C kończy)", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
