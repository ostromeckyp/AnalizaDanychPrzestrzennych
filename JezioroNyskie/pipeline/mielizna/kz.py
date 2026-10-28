"""Mapa KŻ (Wróblewski, KŻ Nysa 2023): georeferencja skanu PDF do EPSG:2180.

Co robi: wyciąga największy obraz ze strony PDF, dopasowuje transformację piksel -> EPSG:2180
  (afiniczną albo wielomian 2. stopnia) do punktów kontrolnych (GCP) z przecięć siatki stopni/minut,
  liczy RMSE na punktach dopasowania (`fit`) i na punktach wstrzymanych (`check`) oraz werdykt.
Dlaczego tak: mapka jest amatorska, więc nie wiemy z góry, czy skan jest rzutem afinicznym; wielomian
  2. stopnia łapie łagodną krzywiznę, ale przy małej liczbie GCP przeucza, dlatego o wyborze decyduje
  RMSE na punktach, których dopasowanie nie widziało. Dopasowanie w współrzędnych znormalizowanych
  (stabilność numeryczna). Odwrotne mapowanie (EPSG:2180 -> piksel) jest osobnym dopasowaniem na
  gęstej siatce, żeby resampling rastra szedł "od wyniku do źródła" (`map_coordinates`).
Wejście → wyjście: PDF + tabela GCP (id, px, py, lon, lat, role) → `KzTransform`
  (px_to_2180, inverse_2180, rmse_fit, rmse_check) i werdykt good / acceptable / aggregated_only.
Jak to obronić: progi z briefu (<= 5 m dobry, <= 10 m akceptowalny, wyżej tylko porównania
  zagregowane); testy na danych syntetycznych ze znaną transformacją; kontrola niezależna od GCP:
  odległość korony zapory na mapie od linii OSM (skrypt 09).
Licencja: pochodne z mapki mają odwołanie do data/reference/KZ_ZRODLO_I_WARUNKI.md.

Rzędne punktowe (K2): OCR przez CLI `tesseract` (kafle 1200 px z zakładką, `--psm 11`), wzorzec `.?ddd,d` (opcjonalna kropka, 3 cyfry, przecinek, cyfra),
  zakres wiarygodny 185-200 m, kotwica = najbliższa izolowana kropka z dowolnej strony liczby, jeden do jednego
  (brak albo niejednoznaczna kropka = wartość odrzucona; ogonek własnego przecinka nie jest kropką),
  reguła koloru: niebieski <=> z < 195,0 (czarne to rzędne lądu/wysp). Błąd OCR szacujemy z próby kontrolnej
  (`ocr_error_rate`) z wagami warstw, bo próba nadreprezentuje punkty podejrzane.
"""
import csv
import io
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import pyproj

GOOD_M = 5.0
ACCEPTABLE_M = 10.0
MIN_POINTS = {"affine": 3, "poly2": 6}
_WGS_TO_2180 = pyproj.Transformer.from_crs(4326, 2180, always_xy=True)


def extract_image(pdf: Path, out: Path) -> tuple[int, int]:
    """Zapisuje największy obraz pierwszej strony PDF jako PNG; zwraca (szerokość, wysokość) w px."""
    from PIL import Image
    from pypdf import PdfReader

    Image.MAX_IMAGE_PIXELS = None  # skan ~47 Mpx jest zamierzony
    images = list(PdfReader(str(pdf)).pages[0].images)
    if not images:
        raise ValueError(f"Brak obrazu na stronie 1: {pdf}")
    best = max(images, key=lambda im: im.image.size[0] * im.image.size[1])
    img = best.image
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return img.size


def verdict(rmse_m: float) -> str:
    """Werdykt georeferencji z RMSE na punktach wstrzymanych [m]."""
    if rmse_m <= GOOD_M:
        return "good"
    if rmse_m <= ACCEPTABLE_M:
        return "acceptable"
    return "aggregated_only"


def _design(u: np.ndarray, v: np.ndarray, kind: str) -> np.ndarray:
    cols = [np.ones_like(u), u, v]
    if kind == "poly2":
        cols += [u * v, u ** 2, v ** 2]
    return np.column_stack(cols)


def _fit(src: np.ndarray, dst: np.ndarray, kind: str):
    """Najmniejsze kwadraty w współrzędnych znormalizowanych; zwraca funkcję src -> dst (N,2)."""
    mu, sd = src.mean(axis=0), src.std(axis=0)
    mu_d, sd_d = dst.mean(axis=0), dst.std(axis=0)
    u = (src - mu) / sd
    coef, *_ = np.linalg.lstsq(_design(u[:, 0], u[:, 1], kind), (dst - mu_d) / sd_d, rcond=None)

    def f(a, b):
        z = (np.column_stack([np.asarray(a, float), np.asarray(b, float)]) - mu) / sd
        out = _design(z[:, 0], z[:, 1], kind) @ coef * sd_d + mu_d
        return out[:, 0], out[:, 1]

    return f


@dataclass
class KzTransform:
    kind: str
    px_to_2180: object   # (px, py) -> (x, y)
    inverse_2180: object  # (x, y) -> (px, py)
    rmse_fit: float
    rmse_check: float
    n_fit: int
    n_check: int


def gcp_to_2180(gcp: pd.DataFrame) -> pd.DataFrame:
    """Dodaje kolumny x, y (EPSG:2180) policzone z lon/lat (WGS84)."""
    x, y = _WGS_TO_2180.transform(gcp["lon"].to_numpy(), gcp["lat"].to_numpy())
    return gcp.assign(x=x, y=y)


def fit_transform(gcp: pd.DataFrame, kind: Literal["affine", "poly2"]) -> KzTransform:
    """Dopasowuje transformację na GCP z role == 'fit'; RMSE [m] na `fit` i na `check`."""
    g = gcp_to_2180(gcp)
    fit, chk = g[g["role"] == "fit"], g[g["role"] == "check"]
    if len(fit) < MIN_POINTS[kind] or len(chk) < 1:
        raise ValueError(f"{kind}: za mało GCP (fit={len(fit)}, check={len(chk)})")
    fwd = _fit(fit[["px", "py"]].to_numpy(float), fit[["x", "y"]].to_numpy(float), kind)

    def rmse(d):
        x, y = fwd(d["px"], d["py"])
        return float(np.sqrt(np.mean((x - d["x"].to_numpy()) ** 2 + (y - d["y"].to_numpy()) ** 2)))

    # odwrotność: dopasowanie na gęstej siatce pikseli przeniesionej wprzód (w zakresie GCP z zapasem)
    px0, px1 = g["px"].min(), g["px"].max()
    py0, py1 = g["py"].min(), g["py"].max()
    gx, gy = np.meshgrid(np.linspace(px0 - 0.1 * (px1 - px0), px1 + 0.1 * (px1 - px0), 40),
                         np.linspace(py0 - 0.1 * (py1 - py0), py1 + 0.1 * (py1 - py0), 40))
    gx, gy = gx.ravel(), gy.ravel()
    fx, fy = fwd(gx, gy)
    inv0 = _fit(np.column_stack([fx, fy]), np.column_stack([gx, gy]), kind)

    def inv(x, y):
        # wielomian odwrotny jest tylko przybliżeniem; kilka kroków Newtona na transformacji wprzód
        # (jakobian numeryczny) doprowadza do dokładności ułamka piksela
        x, y = np.asarray(x, float), np.asarray(y, float)
        a, b = inv0(x, y)
        for _ in range(4):
            fx0, fy0 = fwd(a, b)
            h = 1.0
            fxa, fya = fwd(a + h, b)
            fxb, fyb = fwd(a, b + h)
            j11, j21, j12, j22 = (fxa - fx0) / h, (fya - fy0) / h, (fxb - fx0) / h, (fyb - fy0) / h
            det = j11 * j22 - j12 * j21
            ex, ey = x - fx0, y - fy0
            a = a + (j22 * ex - j12 * ey) / det
            b = b + (-j21 * ex + j11 * ey) / det
        return a, b
    return KzTransform(kind, fwd, inv, rmse(fit), rmse(chk), len(fit), len(chk))


def band_centre(profile: np.ndarray, d: np.ndarray, width_m: float, max_shift_m: float, min_contrast: float = 25.0):
    """Środek ciemnego pasa o szerokości `width_m` w profilu jasności (d: odległość podpisana [m]).

    Korelacja z szablonem pasa: dla każdego przesunięcia c w ±max_shift_m wynik = ciemność wewnątrz
    [c - w/2, c + w/2] minus ciemność w pasach flankujących o tej samej szerokości; ciemność = tło (mediana
    profilu) - jasność. Szablon odrzuca wąskie, ciemne sąsiedztwo (droga), bo wymaga całej szerokości pasa.
    Zwraca None, gdy najlepszy kontrast < `min_contrast` (brak pasa)."""
    dark = np.median(profile) - np.asarray(profile, float)
    best, best_c = -np.inf, None
    for c in np.arange(-max_shift_m, max_shift_m + 1e-9, float(np.median(np.diff(d)))):
        inside = np.abs(d - c) <= width_m / 2
        flank = (np.abs(d - c) > width_m / 2) & (np.abs(d - c) <= 1.5 * width_m)
        if inside.sum() < 2 or flank.sum() < 2:
            continue
        score = dark[inside].mean() - dark[flank].mean()
        if score > best:
            best, best_c = score, c
    return best_c if best >= min_contrast else None


def lake_facing_edges(dam_geoms, lake_geom, max_dist_m: float = 50.0) -> list:
    """Części brzegów pierścieni zapory leżące w `max_dist_m` od obrysu jeziora (strona wodna zapory).

    Warstwa `dam` z OSM to zamknięte pierścienie (obrysy obszarów zapory), więc pełny pierścień zawiera też
    skarpę od strony lądu; dla kontroli położenia bierzemy tylko krawędź od jeziora."""
    from shapely.geometry import LineString, MultiLineString

    zone = lake_geom.buffer(max_dist_m)
    out = []
    for g in dam_geoms:
        inter = g.boundary if g.geom_type in ("Polygon", "MultiPolygon") else g
        inter = inter.intersection(zone)
        parts = [inter] if isinstance(inter, LineString) else list(inter.geoms) if isinstance(inter, MultiLineString) else []
        out += [p for p in parts if isinstance(p, LineString) and p.length > 0]
    return out


# ---------------------------------------------------------------------------------------------------------
# K2: rzędne punktowe z OCR
# ---------------------------------------------------------------------------------------------------------
SPOT_RE = re.compile(r"\.?(\d{3}),(\d)\.?")
SPOT_MIN, SPOT_MAX = 185.0, 200.0
BLUE_BELOW = 195.0
LOW_CONF = 80.0
DOT_MIN_PX, DOT_MAX_PX = 2, 12
OCR_COLUMNS = ["text", "conf", "left", "top", "width", "height"]


def parse_spot(text: str) -> float | None:
    """Rzędna z tekstu OCR (`194,3`, `.193,5`, `196,0.`) albo None: zły format lub poza 185,0-200,0 m.

    Przecinek dziesiętny jest wymagany (BRIEF §6.6); zapis z kropką dziesiętną (`194.3`) jest odrzucany."""
    m = SPOT_RE.fullmatch(text.strip())
    if not m:
        return None
    z = float(f"{m[1]}.{m[2]}")
    return z if SPOT_MIN <= z <= SPOT_MAX else None


def _tesseract_tsv(png: Path) -> list[dict]:
    exe = shutil.which("tesseract")
    if exe is None:
        raise RuntimeError("brak `tesseract` w PATH (brew install tesseract)")
    out = subprocess.run([exe, str(png), "-", "--psm", "11", "tsv"], capture_output=True, text=True, check=True).stdout
    rows = csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE)
    return [r for r in rows if r.get("text") and r["text"].strip() and float(r["conf"]) >= 0]


def _iou(a, b) -> float:
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / (a[2] * a[3] + b[2] * b[3] - inter) if inter > 0 else 0.0


def ocr_tiles(img: np.ndarray, tile: int = 1200, overlap: int = 100, scales: tuple = (1.0,)) -> pd.DataFrame:
    """OCR kaflami: `tesseract <png> - --psm 11 tsv`; zwraca słowa w pikselach CAŁEGO obrazu.

    Kafle mają zakładkę `overlap` px, więc słowo przy szwie może wyjść dwa razy. `scales` = przebiegi
    (np. (1.0, 2.0): drugi na kaflach powiększonych 2x, ramki skalowane z powrotem). Duplikaty (ramki o IoU > 0,3
    albo ten sam tekst ze środkami bliżej niż 8 px) usuwamy; zostaje słowo pasujące do wzorca rzędnej, a przy
    remisie to o większej pewności."""
    from PIL import Image

    h, w = img.shape[:2]
    rows = []
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "tile.png"
        for sc in scales:
            src = max(int(tile / sc), 2 * overlap)         # rozmiar kafla w pikselach źródła
            step = src - overlap
            for y0 in range(0, max(h - overlap, 1), step):
                for x0 in range(0, max(w - overlap, 1), step):
                    pil = Image.fromarray(np.ascontiguousarray(img[y0:y0 + src, x0:x0 + src]))
                    if sc != 1.0:
                        pil = pil.resize((int(pil.width * sc), int(pil.height * sc)), Image.LANCZOS)
                    pil.save(png)
                    for r in _tesseract_tsv(png):
                        rows.append((r["text"].strip(), float(r["conf"]), int(round(int(r["left"]) / sc)) + x0,
                                     int(round(int(r["top"]) / sc)) + y0, max(int(round(int(r["width"]) / sc)), 1),
                                     max(int(round(int(r["height"]) / sc)), 1)))
    df = pd.DataFrame(rows, columns=OCR_COLUMNS)
    if df.empty:
        return df
    df["_spot"] = df["text"].map(parse_spot).notna()
    df = df.sort_values(["_spot", "conf"], ascending=False, kind="stable").reset_index(drop=True)
    keep, boxes = [], []
    for i, r in df.iterrows():
        box = (r.left, r.top, r.width, r.height)
        cx, cy = r.left + r.width / 2, r.top + r.height / 2
        if any(_iou(box, b) > 0.3 or (t == r.text and abs(cx - bx) < 8 and abs(cy - by) < 8)
               for b, t, bx, by in boxes):
            continue
        boxes.append((box, r.text, cx, cy))
        keep.append(i)
    return df.loc[keep].drop(columns="_spot").sort_values(["top", "left"]).reset_index(drop=True)


def _dark_mask(rgb: np.ndarray) -> np.ndarray:
    lum = rgb[..., :3].astype(float) @ np.array([0.299, 0.587, 0.114])
    return lum < 130


ANCHOR_RADIUS_FACTOR = 1.5   # promień szukania kropki = 1,5 x wysokość ramki od jej krawędzi (dobrane na danych)
ANCHOR_AMBIGUITY = 1.3       # dwie kropki o stosunku odległości < 1,3 = niejednoznaczne, liczba odrzucona


COMMA_TAIL_FACTOR = 0.3      # blob pod ramką nie dalej niż 0,3 x wysokość, nad zakresem cyfr = ogonek własnego przecinka


def _dark_mask_chunked(img: np.ndarray, rows: int = 512) -> np.ndarray:
    """Maska ciemnych pikseli całego obrazu, liczona pasami (pełna mapa ma 47 Mpx, bez kopii float na całość)."""
    out = np.zeros(img.shape[:2], bool)
    for y in range(0, img.shape[0], rows):
        out[y:y + rows] = _dark_mask(img[y:y + rows])
    return out


class _Blobs:
    """Składowe spójne całego obrazu (jednorazowo): wspólne dla wszystkich liczb, więc ta sama kropka ma ten sam
    identyfikator i środek niezależnie od okna szukania (rozwiązanie konfliktu „jedna kropka - jedna liczba”)."""

    def __init__(self, img: np.ndarray):
        from scipy.ndimage import find_objects, label

        self.img = img
        self.lab, _ = label(_dark_mask_chunked(img), structure=np.ones((3, 3)))
        rows = []
        for i, sl in enumerate(find_objects(self.lab), start=1):
            if sl is None:
                continue
            rows.append((i, sl[1].start, sl[1].stop, sl[0].start, sl[0].stop, int((self.lab[sl] == i).sum())))
        self.a = np.array(rows, dtype=float).reshape(-1, 6)    # id, x0, x1, y0, y1, area (x1/y1 wyłącznie)

    def is_dot(self, row) -> bool:
        i, x0, x1, y0, y1, area = row
        w, h = x1 - x0, y1 - y0
        if not (DOT_MIN_PX <= w <= DOT_MAX_PX and DOT_MIN_PX <= h <= DOT_MAX_PX) or area < 0.5 * w * h:
            return False
        ring = self.lab[max(int(y0) - 2, 0):int(y1) + 2, max(int(x0) - 2, 0):int(x1) + 2]
        if np.any((ring != 0) & (ring != i)):               # 2 px czystego tła: koniec izobaty nie jest kropką
            return False
        ys, xs = np.nonzero(self.lab[int(y0):int(y1), int(x0):int(x1)] == i)
        px = self.img[int(y0) + ys, int(x0) + xs, :3].astype(float)
        # kolor kropki jak tekstu rzędnej (niebieski albo czarny); czerwone/różowe krzyżyki komunikatów to nie kropki
        return _classify_rgb(*np.median(px, axis=0)) != "other"


def _dot_candidates(blobs: _Blobs, box, others) -> list[tuple[int, float, float, str, float]]:
    """Izolowane kropki w promieniu 1,5 x wysokość od ramki: (id blobu, x, y, strona, odległość).

    Cyfry to składowe o wysokości 0,5-1,25 wysokości ramki wewnątrz ramki. Pomijamy: kropki wewnątrz ramki (poza
    lewą od pierwszej cyfry: przecinek, cyfry dziesiętne), ogonek własnego przecinka wystający pod ramkę (blob nad
    zakresem cyfr, nie dalej niż 0,3 x wysokość pod dolną krawędzią) oraz kropki w ramkach innych słów z cyframi."""
    left, top, width, height = (int(round(v)) for v in box)
    r = ANCHOR_RADIUS_FACTOR * height
    A = blobs.a
    if len(A) == 0:
        return []
    near = A[(A[:, 2] > left - r) & (A[:, 1] < left + width + r) & (A[:, 4] > top - r) & (A[:, 3] < top + height + r)]
    w, h = near[:, 2] - near[:, 1], near[:, 4] - near[:, 3]
    dig = near[(h >= 0.5 * height) & (h <= 1.25 * height) & (w >= 3) & (w <= 0.8 * height)
               & (near[:, 1] >= left - 3) & (near[:, 2] <= left + width + 3)]
    if len(dig) == 0:
        return []
    first_left = dig[:, 1].min()
    out = []
    for row in near:
        i, x0, x1, y0, y1, _ = row
        if not blobs.is_dot(row):
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        inside = left <= cx <= left + width and top <= cy <= top + height
        if inside and x1 > first_left + 1:
            continue                      # przecinek albo cyfra dziesiętna własnej liczby
        if first_left <= cx <= left + width + 3 and top + height < cy <= top + height * (1 + COMMA_TAIL_FACTOR):
            continue                      # ogonek własnego przecinka wystający pod ramkę
        if any(ox - 1 <= cx <= ox + ow + 1 and oy - 1 <= cy <= oy + oh + 1 for ox, oy, ow, oh in others):
            continue                      # kropka (przecinek) innego słowa
        dx = max(left - cx, 0, cx - (left + width))
        dy = max(top - cy, 0, cy - (top + height))
        dist = float(np.hypot(dx, dy))
        if dist > r:
            continue
        if inside or dx >= dy:
            side = "left" if cx < left + width / 2 else "right"
        else:
            side = "above" if cy < top else "below"
        out.append((int(i), float(cx), float(cy), side, dist))
    return out


def spot_anchors(img: np.ndarray, boxes, others=None) -> list[tuple[float, float, str] | None]:
    """Kotwice (x, y, strona) dla wielu liczb naraz: najbliższa izolowana kropka z dowolnej strony, jeden do jednego.

    Zasady (R14): (1) każda liczba proponuje najbliższą kropkę w promieniu 1,5 x wysokość ramki; (2) dwie kropki
    o stosunku odległości < 1,3 = niejednoznaczne, liczba odrzucona; (3) kropka kotwiczy tylko jedną liczbę:
    gdy chcą jej dwie, wygrywa bliższa (o ile stosunek odległości >= 1,3, inaczej odpadają obie), a przegrana
    liczba jest odrzucona. Kropki to składowe całego obrazu (jeden identyfikator niezależnie od okna szukania).
    `others` = ramki słów z cyframi (domyślnie same `boxes`); ramka własna jest pomijana."""
    boxes = [tuple(b) for b in boxes]
    pool = [tuple(int(round(v)) for v in o) for o in (others if others is not None else boxes)]
    blobs = _Blobs(img)
    res: list = [None] * len(boxes)
    proposals: dict[int, list[tuple[float, int, tuple]]] = {}
    for n, box in enumerate(boxes):
        own = tuple(int(round(v)) for v in box)
        cands = sorted(_dot_candidates(blobs, box, [o for o in pool if o != own]), key=lambda c: c[4])
        if not cands:
            continue
        if len(cands) > 1 and (cands[1][4] + 1) / (cands[0][4] + 1) < ANCHOR_AMBIGUITY:
            continue
        c = cands[0]
        proposals.setdefault(c[0], []).append((c[4], n, c))
    for props in proposals.values():
        props.sort(key=lambda p: p[0])
        if len(props) > 1 and (props[1][0] + 1) / (props[0][0] + 1) < ANCHOR_AMBIGUITY:
            continue
        _, n, c = props[0]
        res[n] = (c[1], c[2], c[3])
    return res


def spot_anchor(img: np.ndarray, box, others=None) -> tuple[float, float] | None:
    """Środek kropki-kotwicy dla jednej liczby (patrz `spot_anchors`); brak albo niejednoznaczna kropka -> None."""
    r = spot_anchors(img, [box], others)[0]
    return None if r is None else (r[0], r[1])


def text_color(img: np.ndarray, box) -> Literal["blue", "black", "other"]:
    """Kolor tekstu w ramce: mediana RGB najciemniejszych pikseli (tło mapy jest jasne).

    blue = niebieski dominuje (b > r + 40 i b > g + 40); black = wszystkie kanały < 100 i prawie szare;
    reszta (magenta, zielone nazwy) = other."""
    left, top, width, height = (int(round(v)) for v in box)
    patch = img[max(top, 0):top + height, max(left, 0):left + width, :3].reshape(-1, 3).astype(float)
    lum = patch @ np.array([0.299, 0.587, 0.114])
    dark = patch[lum < 120]
    if len(dark) < 8:
        return "other"
    return _classify_rgb(*np.median(dark, axis=0))


def _classify_rgb(r: float, g: float, b: float) -> Literal["blue", "black", "other"]:
    if b > r + 40 and b > g + 40:
        return "blue"
    if max(r, g, b) < 100 and b - r < 40 and abs(g - r) < 40:
        return "black"
    return "other"


def color_consistent(z: float, color: str) -> bool:
    """Niebieski <=> z < 195,0 (rzędne wody), czarny <=> z >= 195,0 (ląd); `other` nigdy nie jest zgodny."""
    if color == "blue":
        return z < BLUE_BELOW
    if color == "black":
        return z >= BLUE_BELOW
    return False


def is_suspect(df: pd.DataFrame) -> pd.Series:
    """Warstwa „podejrzane” próby kontrolnej: niezgodność koloru z rzędną albo pewność OCR < 80."""
    return (~df["color_ok"].astype(bool)) | (df["conf"] < LOW_CONF)


def ocr_error_rate(qc: pd.DataFrame, population: pd.DataFrame) -> tuple[float, int]:
    """Błąd OCR z próby kontrolnej, ważony warstwami: (udział `corrected + rejected`, liczba ocenionych).

    `qc`: id, ocr_z, qc in {ok, corrected, rejected, skip}, z_qc oraz color_ok i conf (żeby wyznaczyć warstwę
    `is_suspect`); `population`: wszystkie punkty OCR (color_ok, conf). Próba jest losowana warstwowo
    (połowa podejrzanych), więc surowy udział błędów zawyża błąd. Estymator:

        rate = sum_h  W_h * e_h,   W_h = (udział warstwy h w populacji) / (udział warstwy h wśród ocenionych)
        wagi punktów: w_i = W_h, rate = sum_i w_i * err_i / sum_i w_i

    co jest równe sum_h P_h * e_h, gdzie P_h to udział populacji, a e_h niewazony błąd w warstwie. Wiersze `skip`
    nie są ocenione. Warstwa bez ocenionych punktów wypada, a wagi pozostałych renormalizuje się."""
    ev = qc[qc["qc"] != "skip"]
    if ev.empty:
        return float("nan"), 0
    pop_share = is_suspect(population).value_counts(normalize=True)
    s = is_suspect(ev)
    samp_share = s.value_counts(normalize=True)
    w = s.map(lambda h: pop_share.get(h, 0.0) / samp_share[h])
    err = ev["qc"].isin(["corrected", "rejected"]).astype(float)
    return float((w * err).sum() / w.sum()), int(len(ev))


def in_lake_zone(x, y, lake_geom, buffer_m: float = 100.0) -> np.ndarray:
    """Maska punktów (EPSG:2180) w obrysie jeziora z wyspami (dziury wypełnione) powiększonym o `buffer_m`.

    Odcina legendę i opisy poza zbiornikiem (tabela pojemność-rzędna ma liczby w zakresie 185-200 m); wyspy
    zostają, bo czarne rzędne wysp to prawdziwe punkty mapy."""
    from shapely import contains_xy
    from shapely.geometry import MultiPolygon, Polygon

    parts = lake_geom.geoms if lake_geom.geom_type == "MultiPolygon" else [lake_geom]
    filled = MultiPolygon([Polygon(p.exterior) for p in parts]).buffer(buffer_m)
    return np.asarray(contains_xy(filled, np.asarray(x, float), np.asarray(y, float)))


QC_MATCH_PX = 3.0
QC_MATCH_DZ = 0.05


def match_qc(qc: pd.DataFrame, spots: pd.DataFrame, tol_px: float = QC_MATCH_PX) -> tuple[pd.DataFrame, int]:
    """Przypisuje wiersze kontroli ręcznej do bieżących punktów OCR po położeniu, nie po numerze `id`.

    `id` w kz_spot_ocr.gpkg to numer w kolejności sortowania, więc zmienia się po każdym ponownym OCR (nowa wersja
    tesseract, zmiana kodu). Wiersz QC (`px, py, ocr_z`) pasuje do punktu o tej samej rzędnej (|dz| < 0,05) i
    kotwicy w promieniu `tol_px`; wybierany jest najbliższy. Zwraca (QC z nadpisanym `id`, liczba odrzuconych
    niedopasowanych wierszy)."""
    keep, ids = [], []
    sp = spots[["id", "z", "px", "py"]].to_numpy(float)
    for i, r in qc.iterrows():
        d = np.hypot(sp[:, 2] - float(r["px"]), sp[:, 3] - float(r["py"]))
        ok = (d <= tol_px) & (np.abs(sp[:, 1] - float(r["ocr_z"])) < QC_MATCH_DZ)
        if ok.any():
            keep.append(i)
            ids.append(int(sp[np.where(ok, d, np.inf).argmin(), 0]))
    out = qc.loc[keep].copy()
    out["id"] = ids
    return out.reset_index(drop=True), len(qc) - len(keep)


# --- Poziomice 192,5 i 195,0 m (K3) oraz obrys żwirowni -------------------------------------------------------
# Co robi: maska koloru -> poziom linii z sąsiedniego wypełnienia -> szkielet -> linie -> EPSG:2180.
# Dlaczego tak: wszystkie poziomice mapy mają ten sam granat (zmierzone: ok. RGB 15,30,140, grubość 2-3 px),
#   więc kolor linii nie wskazuje poziomu. Poziom wskazuje wypełnienie wody: pas 192,5-195,0 m jest biały,
#   głębiej jest błękit. Linia 195,0 (brzeg) graniczy z lądem; linia 192,5 z białym pasem i błękitem;
#   inne poziomice (np. 193,0 wewnątrz pasa) nie graniczą ani z lądem, ani z błękitem i odpadają.
#   Linie przerywane („orientacyjne”, dno poniżej 192,5) rozpadają się na kreski krótsze niż `min_len_px`.
# Jak to obronić: oglądany `qc_contours.png`; długości i liczby linii w M7; lista `contour_drop_ids` jawna.


def color_mask(img: np.ndarray, rgb: tuple[int, int, int], tol: int) -> np.ndarray:
    """Maska pikseli bliskich `rgb` (odległość Czebyszewa w RGB <= tol); liczy porcjami, bez kopii całego obrazu."""
    out = np.zeros(img.shape[:2], bool)
    ref = np.asarray(rgb, np.int16)
    for r0 in range(0, img.shape[0], 512):
        blk = img[r0:r0 + 512, :, :3].astype(np.int16)
        out[r0:r0 + 512] = (np.abs(blk - ref) <= tol).all(-1)
    return out


def _prune_spurs(adj: dict, spur_px: int) -> None:
    """Usuwa gałązki (od końcówki do rozwidlenia) krótsze niż `spur_px`: litery i ogonki przy linii."""
    ends = [p for p, n in adj.items() if len(n) == 1]
    for e in ends:
        if e not in adj or len(adj[e]) != 1:
            continue
        path, prev, cur = [e], None, e
        while True:
            nxt = [q for q in adj[cur] if q != prev]
            if len(nxt) != 1:
                break
            prev, cur = cur, nxt[0]
            if len(adj[cur]) >= 3:
                break
            path.append(cur)
            if len(path) > spur_px:
                break
        if len(path) <= spur_px and len(adj.get(cur, ())) >= 3:
            for p in path:
                for q in adj.pop(p):
                    if q in adj:
                        adj[q].remove(p)


def _merge_at_pair_nodes(paths: list) -> list:
    """Skleja ścieżki, które spotykają się w węźle z dokładnie dwiema ścieżkami (pozostałość po ucięciu ogonka)."""
    changed = True
    while changed:
        changed = False
        ends: dict = {}
        for i, p in enumerate(paths):
            for e in {p[0], p[-1]}:
                ends.setdefault(e, []).append(i)
        for e, idx in sorted(ends.items()):
            if len(idx) != 2 or idx[0] == idx[1]:
                continue
            a, b = paths[idx[0]], paths[idx[1]]
            a = a if a[-1] == e else a[::-1]
            b = b if b[0] == e else b[::-1]
            merged = a + b[1:]
            paths = [q for j, q in enumerate(paths) if j not in idx] + [merged]
            changed = True
            break
    return paths


def mask_to_lines(mask: np.ndarray, min_len_px: int = 80, spur_px: int = 12) -> list:
    """Szkielet maski -> linie (x=kolumna, y=wiersz); dzieli w rozwidleniach, ucina ogonki < `spur_px`
    i odrzuca linie krótsze niż `min_len_px` (długość euklidesowa)."""
    from shapely.geometry import LineString
    from skimage.morphology import skeletonize

    sk = skeletonize(mask)
    pts = np.argwhere(sk)
    pset = {(int(y), int(x)) for y, x in pts}
    adj = {p: [(p[0] + dy, p[1] + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
               if (dy or dx) and (p[0] + dy, p[1] + dx) in pset] for p in pset}
    _prune_spurs(adj, spur_px)
    keep = np.zeros(mask.shape, bool)             # po ucięciu zostaje „guzek” przy rozwidleniu: ponowne ścienienie
    ky, kx = zip(*adj) if adj else ((), ())
    keep[list(ky), list(kx)] = True
    pset = {(int(y), int(x)) for y, x in np.argwhere(skeletonize(keep))}
    adj = {p: [(p[0] + dy, p[1] + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
               if (dy or dx) and (p[0] + dy, p[1] + dx) in pset] for p in pset}
    node = {p for p, n in adj.items() if len(n) != 2}
    seen: set = set()          # krawędzie (para pikseli) już przejęte
    lines = []

    def walk(start, first):
        path, prev, cur = [start, first], start, first
        seen.add((start, first)); seen.add((first, start))
        while cur not in node:
            nxt = [q for q in adj[cur] if q != prev]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            if (prev, cur) in seen:
                break
            seen.add((prev, cur)); seen.add((cur, prev))
            path.append(cur)
        return path

    for s in sorted(node):
        for q in sorted(adj[s]):
            if (s, q) not in seen:
                lines.append(walk(s, q))
    for s in sorted(p for p in adj if p not in node):          # pętle bez węzłów (zamknięte poziomice)
        for q in sorted(adj[s]):
            if (s, q) not in seen:
                lines.append(walk(s, q))
    lines = _merge_at_pair_nodes([l for l in lines if len(l) >= 2])
    out = []
    for path in lines:
        ls = LineString([(x, y) for y, x in path]).simplify(0.7)
        if ls.length >= min_len_px:
            out.append(ls)
    out.sort(key=lambda g: (round(g.coords[0][1]), round(g.coords[0][0]), -g.length))   # stabilne id
    return out


def _blueness(img: np.ndarray) -> np.ndarray:
    """b - r piksela (granat/błękit linii ma b >> r; szara siatka nie)."""
    out = np.zeros(img.shape[:2], np.int16)
    for r0 in range(0, img.shape[0], 512):
        blk = img[r0:r0 + 512, :, :3].astype(np.int16)
        out[r0:r0 + 512] = blk[..., 2] - blk[..., 0]
    return out


def contour_level_masks(img: np.ndarray, colors: dict) -> dict:
    """Maski pikseli linii dla poziomów 192,5 i 195,0 (patrz komentarz modułu); `colors` jak `kz.contour_colors`."""
    from scipy import ndimage as ndi

    ring = int(colors.get("ring_px", 6))
    line = color_mask(img, tuple(colors["line"]), colors["line_tol"]) & (_blueness(img) >= 40)   # szara siatka i drogi odpadają
    shallow = color_mask(img, tuple(colors["shallow"]), colors["shallow_tol"])
    shallow = ndi.binary_opening(shallow, np.ones((5, 5), bool))      # bez cienkich linii siatki i obwódek tekstu
    deep = color_mask(img, tuple(colors["deep"]), colors["deep_tol"]) & ~shallow
    deep = ndi.binary_opening(deep, np.ones((5, 5), bool))            # odrzuca antyaliasing na krawędzi pasa
    land = np.zeros(line.shape, bool)
    for r0 in range(0, img.shape[0], 512):
        blk = img[r0:r0 + 512, :, :3].astype(np.int16)
        land[r0:r0 + 512] = blk[..., 1] - blk[..., 2] >= 12   # zieleń/beż: b wyraźnie < g (woda i biel mają b >= g)
    k = np.ones((2 * ring + 1, 2 * ring + 1), bool)
    near_shallow = ndi.binary_dilation(shallow, k)
    near_deep = ndi.binary_dilation(deep, k)
    near_land = ndi.uniform_filter(land.astype(np.float32), 2 * ring + 1) >= 0.1
    seeds = {195.0: line & near_land & ~(near_shallow & near_deep),
             192.5: line & near_shallow & near_deep & ~near_land}
    # Cienka linia blednie (antyaliasing, 1 px) i ma przerwy: ziarna rosną po szerszej masce granatu (do `grow_px`
    # kroków), więc łączą się w ciągłe linie, ale nie uciekają daleko na inne poziomice.
    wide = color_mask(img, tuple(colors["line"]), colors["line_tol"] + 25)
    wide &= _blueness(img) >= 50
    grow = int(colors.get("grow_px", 10))
    out = {}
    for lv, seed in seeds.items():
        cur = seed.copy()
        for _ in range(grow):
            cur |= ndi.binary_dilation(cur) & wide
        out[lv] = cur
    return out


def _side_class(rgb) -> str:
    """Klasa piksela obok linii: water (biel albo błękit wody), ink (granat linii, tekst, czerń) lub land (reszta:
    ciemna zieleń, piasek, beż, szarość). Poziom wody poznajemy po b >> r, więc beżowy symbol drogi nie jest wodą."""
    r, g, b = (int(v) for v in rgb)
    if r >= 232 and g >= 232 and b >= 232:
        return "water"
    if b >= 215 and b - r >= 20:
        return "water"
    if b - r >= 50 and r + g + b < 450 or r + g + b < 300:
        return "ink"
    return "land"


def line_side_votes(img: np.ndarray, xy_px: np.ndarray, offset_px: float = 8.0, step_px: float = 6.0):
    """Udział próbek wzdłuż linii (piksele obrazu), dla których jedna strona to woda, a druga ląd.

    Co `step_px` bierzemy normalną do linii i klasę piksela (mediana 3 x 3) po obu stronach w odległości
    `offset_px`; próbka z tuszem (tekst, inna linia) po którejś stronie nie liczy się. Zwraca (udział, liczba
    ważnych próbek). Brzeg 195,0 m: ląd po jednej stronie, woda po drugiej; poziomica nad brzegiem ma ląd po
    obu stronach, a w wodzie wodę po obu."""
    from shapely.geometry import LineString

    xy = np.asarray(xy_px, float)
    ls = LineString(xy)
    h, w = img.shape[:2]
    n_ok = n_shore = 0
    for d in np.arange(step_px, ls.length - step_px, step_px):
        a, b = ls.interpolate(d - 3), ls.interpolate(d + 3)
        p = ls.interpolate(d)
        tx, ty = b.x - a.x, b.y - a.y
        nn = np.hypot(tx, ty)
        if nn == 0:
            continue
        nx_, ny_ = -ty / nn, tx / nn
        cls = []
        for sgn in (1, -1):
            cx, cy = int(round(p.x + sgn * nx_ * offset_px)), int(round(p.y + sgn * ny_ * offset_px))
            if not (1 <= cx < w - 1 and 1 <= cy < h - 1):
                break
            med = np.median(img[cy - 1:cy + 2, cx - 1:cx + 2, :3].reshape(-1, 3), axis=0)
            cls.append(_side_class(med))
        if len(cls) < 2 or "ink" in cls:
            continue
        n_ok += 1
        n_shore += set(cls) == {"land", "water"}
    return (n_shore / n_ok if n_ok else 0.0), n_ok


def is_axis_aligned(xy_px: np.ndarray, tol_px: float = 3.0) -> bool:
    """Linia prosta wzdłuż osi obrazu (siatka mapy, ramka), nie poziomica."""
    xy = np.asarray(xy_px, float)
    return bool(min(np.ptp(xy[:, 0]), np.ptp(xy[:, 1])) <= tol_px)


def is_straight(xy_px: np.ndarray, ratio: float = 0.985, min_len_px: float = 150.0) -> bool:
    """Długa, niemal prosta linia (cięciwa / długość >= ratio): droga, wał, granica użytku, nie poziomica."""
    from shapely.geometry import LineString

    xy = np.asarray(xy_px, float)
    length = LineString(xy).length
    return bool(length >= min_len_px and np.hypot(*(xy[-1] - xy[0])) / length >= ratio)


def drop_outer_parallels(lines, ref_geom, tol_m: float = 12.0, frac: float = 0.5) -> list[bool]:
    """Maska „zostaw”: z pary równoległych poziomic (> `frac` długości w odległości <= `tol_m` od drugiej)
    zostaje ta bliżej `ref_geom` (obrys jeziora): niższa poziomica przy wodzie to 195,0, zewnętrzna jest wyżej."""
    from shapely.geometry import MultiPoint

    keep = [True] * len(lines)
    pts = [MultiPoint([lines[i].interpolate(d) for d in np.arange(0, lines[i].length, 5.0)] or [lines[i].interpolate(0)])
           for i in range(len(lines))]
    dist_ref = [float(np.mean([ref_geom.distance(q) for q in pts[i].geoms])) for i in range(len(lines))]
    for i, li in enumerate(lines):
        for j, lj in enumerate(lines):
            if i == j or not keep[j]:
                continue
            near = np.mean([lj.distance(q) <= tol_m for q in pts[i].geoms])
            if near > frac and dist_ref[i] > dist_ref[j]:
                keep[i] = False
                break
    return keep


def match_drops(lines, drops: list[dict], tol_m: float = 20.0) -> list[bool]:
    """Które linie wskazują wpisy `contour_drop` (środek w EPSG:2180 `x`,`y` w granicy `tol_m` i długość +-25 %);
    stabilne wobec zmiany numeracji po ponownym uruchomieniu."""
    from shapely.geometry import Point

    out = []
    for g in lines:
        c = g.interpolate(0.5, normalized=True)
        out.append(any(Point(d["x"], d["y"]).distance(c) <= tol_m and abs(g.length - d["length_m"]) <= 0.25 * d["length_m"]
                       for d in drops))
    return out


def lines_to_2180(lines, t: "KzTransform") -> list:
    """Linie w pikselach obrazu -> EPSG:2180 przez transformację z GCP."""
    from shapely.geometry import LineString

    out = []
    for g in lines:
        xy = np.asarray(g.coords)
        x, y = t.px_to_2180(xy[:, 0], xy[:, 1])
        out.append(LineString(np.column_stack([x, y])))
    return out


def vertices_to_polygon(verts, t: "KzTransform"):
    """Wierzchołki obrysu (piksele obrazu) -> poprawny Polygon w EPSG:2180 (samoprzecięcia naprawione)."""
    from shapely.geometry import Polygon
    from shapely.validation import make_valid

    v = np.asarray(verts, float)
    if len(v) < 3:
        raise ValueError("obrys wymaga co najmniej 3 wierzchołków")
    x, y = t.px_to_2180(v[:, 0], v[:, 1])
    poly = Polygon(np.column_stack([x, y]))
    if not poly.is_valid:
        logging.getLogger(__name__).warning("vertices_to_polygon: naprawiono nieprawidłowy pierścień (samoprzecięcie), "
                                            "sprawdź kolejność wierzchołków")
        poly = make_valid(poly)
        if poly.geom_type != "Polygon":
            poly = max((g for g in getattr(poly, "geoms", [poly]) if g.geom_type == "Polygon"), key=lambda g: g.area)
    if poly.area <= 0:
        raise ValueError("obrys o zerowym polu")
    return poly


def load_qc_spots(ocr: "gpd.GeoDataFrame", qc: pd.DataFrame | None) -> "gpd.GeoDataFrame":
    """Punkty rzędnych mapy KŻ nadające się do użycia (wariant D, K5): po kontroli ręcznej, a bez niej po filtrze.

    Co robi: wiersze QC przypisuje do punktów OCR po kotwicy (`match_qc`: ≤ 3 px i ta sama `ocr_z`). Punkt z
      `qc = ok` zostaje z rzędną OCR, z `corrected` dostaje `z_qc`, z `rejected` odpada.
    Dlaczego tak: punkt nieoceniony (brak wiersza QC albo `skip`) dostaje regułę „bez kontroli”: zostaje tylko gdy
      kolor zgadza się z rzędną (`color_ok`) i pewność OCR ≥ `LOW_CONF` (czyli nie jest `is_suspect`). Gdy QC jest
      kompletne, nieocenionych nie ma i reguła nic nie dotyka; gdy QC jest częściowe albo go brak, działa tylko na
      nieocenionych, więc oceny ręczne zawsze wygrywają z filtrem.
    Wejście → wyjście: GeoDataFrame OCR (id, z, px, py, conf, color_ok, geometry) i QC (ocr_z, qc, z_qc, px, py)
      lub None -> GeoDataFrame tych punktów z kolumną `z` (po korekcie) i `z_source` in {ocr_ok, qc_ok, qc_corrected}.
    Jak to obronić: testy obu ścieżek; kolor i pewność to te same progi co warstwa „podejrzane” w kontroli."""
    out = ocr.copy()
    out["z_source"] = "unchecked"
    if qc is not None and len(qc):
        matched, _ = match_qc(qc, out)
        judged = matched[matched["qc"].isin(["ok", "corrected", "rejected"])].drop_duplicates("id", keep="last")
        verdict = judged.set_index("id")["qc"]
        zq = pd.to_numeric(judged.set_index("id")["z_qc"], errors="coerce")
        v = out["id"].map(verdict)
        out.loc[v == "ok", "z_source"] = "qc_ok"
        fixed = v == "corrected"
        out.loc[fixed, "z"] = out.loc[fixed, "id"].map(zq).to_numpy(float)
        out.loc[fixed, "z_source"] = "qc_corrected"
        out.loc[v == "rejected", "z_source"] = "qc_rejected"
    unchecked = out["z_source"] == "unchecked"
    keep_unchecked = unchecked & ~is_suspect(out)
    out.loc[keep_unchecked, "z_source"] = "ocr_ok"
    keep = out["z_source"].isin(["ocr_ok", "qc_ok", "qc_corrected"])
    return out[keep].reset_index(drop=True)
