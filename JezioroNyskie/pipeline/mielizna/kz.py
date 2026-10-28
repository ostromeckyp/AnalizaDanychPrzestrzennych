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
  zakres wiarygodny 185-200 m, kotwica = kropka po LEWEJ stronie liczby (brak kropki = wartość odrzucona),
  reguła koloru: niebieski <=> z < 195,0 (czarne to rzędne lądu/wysp). Błąd OCR szacujemy z próby kontrolnej
  (`ocr_error_rate`) z wagami warstw, bo próba nadreprezentuje punkty podejrzane.
"""
import csv
import io
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


def _dot_candidates(img: np.ndarray, box, others) -> list[tuple[float, float, str, float]]:
    """Izolowane kropki (ciemne bloby 2-12 px) w promieniu 1,5 x wysokość od ramki: (x, y, strona, odległość).

    Cyfry to składowe o wysokości 0,5-1,25 wysokości ramki wewnątrz ramki; kropka wewnątrz ramki liczy się tylko
    na lewo od pierwszej cyfry (przecinek i cyfry dziesiętne są pomijane). Kropka musi mieć 2 px czystego tła
    wokół (koniec izobaty nie jest kropką) i nie może leżeć w ramce innego słowa z cyfrą (przecinek sąsiada)."""
    from scipy.ndimage import find_objects, label

    left, top, width, height = (int(round(v)) for v in box)
    r = int(np.ceil(ANCHOR_RADIUS_FACTOR * height))
    x0, x1 = max(left - r, 0), min(left + width + r, img.shape[1])
    y0, y1 = max(top - r, 0), min(top + height + r, img.shape[0])
    if x1 <= x0 or y1 <= y0:
        return []
    lab, _ = label(_dark_mask(img[y0:y1, x0:x1]), structure=np.ones((3, 3)))
    comps = []
    for i, sl in enumerate(find_objects(lab), start=1):
        if sl is not None:
            comps.append((i, sl, sl[0].stop - sl[0].start, sl[1].stop - sl[1].start, int((lab[sl] == i).sum())))
    digits = [c for c in comps if 0.5 * height <= c[2] <= 1.25 * height and 3 <= c[3] <= 0.8 * height
              and x0 + c[1][1].start >= left - 3 and x0 + c[1][1].stop <= left + width + 3]
    if not digits:
        return []
    first_left = x0 + min(c[1][1].start for c in digits)
    out = []
    for i, sl, ch, cw, area in comps:
        if not (DOT_MIN_PX <= ch <= DOT_MAX_PX and DOT_MIN_PX <= cw <= DOT_MAX_PX) or area < 0.5 * ch * cw:
            continue
        ring = lab[max(sl[0].start - 2, 0):sl[0].stop + 2, max(sl[1].start - 2, 0):sl[1].stop + 2]
        if np.any((ring != 0) & (ring != i)):
            continue
        cx, cy = x0 + (sl[1].start + sl[1].stop) / 2, y0 + (sl[0].start + sl[0].stop) / 2
        inside = left <= cx <= left + width and top <= cy <= top + height
        if inside and x0 + sl[1].stop > first_left + 1:
            continue                      # przecinek albo cyfra dziesiętna własnej liczby
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
        out.append((float(cx), float(cy), side, dist))
    return out


def spot_anchors(img: np.ndarray, boxes, others=None) -> list[tuple[float, float, str] | None]:
    """Kotwice (x, y, strona) dla wielu liczb naraz: najbliższa izolowana kropka z dowolnej strony, jeden do jednego.

    Zasady (R14): (1) każda liczba proponuje najbliższą kropkę w promieniu 1,5 x wysokość ramki; (2) dwie kropki
    o stosunku odległości < 1,3 = niejednoznaczne, liczba odrzucona; (3) kropka kotwiczy tylko jedną liczbę:
    gdy chcą jej dwie, wygrywa bliższa (o ile stosunek odległości >= 1,3, inaczej odpadają obie), a przegrana
    liczba jest odrzucona. `others` = ramki słów z cyframi (domyślnie same `boxes`); ramka własna jest pomijana."""
    boxes = [tuple(b) for b in boxes]
    pool = [tuple(int(round(v)) for v in o) for o in (others if others is not None else boxes)]
    res: list = [None] * len(boxes)
    proposals: dict[tuple[int, int], list[tuple[float, int, tuple]]] = {}
    for n, box in enumerate(boxes):
        own = tuple(int(round(v)) for v in box)
        cands = sorted(_dot_candidates(img, box, [o for o in pool if o != own]), key=lambda c: c[3])
        if not cands:
            continue
        if len(cands) > 1 and (cands[1][3] + 1) / (cands[0][3] + 1) < ANCHOR_AMBIGUITY:
            continue
        c = cands[0]
        proposals.setdefault((int(round(c[0] * 2)), int(round(c[1] * 2))), []).append((c[3], n, c))
    for props in proposals.values():
        props.sort(key=lambda p: p[0])
        if len(props) > 1 and (props[1][0] + 1) / (props[0][0] + 1) < ANCHOR_AMBIGUITY:
            continue
        _, n, c = props[0]
        res[n] = (c[0], c[1], c[2])
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
    r, g, b = np.median(dark, axis=0)
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
