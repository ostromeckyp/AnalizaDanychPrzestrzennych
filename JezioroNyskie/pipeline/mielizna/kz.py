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
"""
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
