"""Obrazy warstw dna i niepewności w EPSG:3857 dla źródeł `image` MapLibre.

Co robi: przelicza rastry modelu (EPSG:2180) do Web Mercatora (10 m, najbliższy sąsiad), wyznacza cztery
  narożniki obrazu w lon/lat oraz renderuje dwa PNG-i RGBA: dno (5 klas wg percentyli `z`) i kropki
  niepewności (`unc` ≥ 0,5 m), obraz 2×.
Dlaczego tak: MapLibre `image` rozciąga obraz między czterema narożnikami lon/lat, więc obraz musi być
  w układzie, w którym kafelki mapy są prostokątne (3857). Klasy wg percentyli dają równe powierzchnie
  klas niezależnie od rozkładu głębokości; kolory interpolowane w RGB od płytko (jasny) do głęboko
  (ciemny), osobna para dla motywu jasnego i ciemnego (brief §16.3). Kropki 1×1 w komórce 2×2 dają
  deseń, który nie zasłania dna. Powtórzone progi percentyli (np. mało różnych `z`) nie psują
  klasyfikacji: `np.searchsorted(..., side="left")` na progach wewnętrznych daje klasy 0-4 (wartość równa progowi trafia do klasy niższej), a puste klasy po prostu nie występują.
Wejście → wyjście: `Products` + motyw (`light`|`dark`) → bajty PNG; `to_web_mercator(arr, products)` →
  (tablica float32 z NaN poza danymi, `Affine`); `image_coordinates(transform, shape)` → 4×[lon, lat]
  (lewy górny, prawy górny, prawy dolny, lewy dolny); `bottom_breaks(products)` → 6 progów [m n.p.m.].
Jak to obronić: test sprawdza, że znaczniczny piksel ląduje w swoim lon/lat z dokładnością < 10 m, a
  kolejność narożników jest zgodna z MapLibre.
"""
import io

import numpy as np
import rasterio
from affine import Affine
from PIL import Image
from pyproj import Transformer
from rasterio.warp import Resampling, calculate_default_transform, reproject

MERCATOR = "EPSG:3857"
RESOLUTION_M = 10
UNC_MIN = 0.5                      # m; od tej niepewności rysujemy kropkę
UNC_SCALE = 2                      # obraz niepewności powiększony 2×
N_CLASSES = 5
BOTTOM_COLORS = {                  # (najpłycej, najgłębiej), brief §16.3
    "light": ("#C4DDE9", "#215C86"),
    "dark": ("#2A4C5E", "#1675AB"),
}
UNC_COLORS = {"light": "#0E2433", "dark": "#E6EEF3"}
UNC_ALPHA = int(round(0.6 * 255))


def _rgb(hex_color: str) -> np.ndarray:
    return np.array([int(hex_color[i:i + 2], 16) for i in (1, 3, 5)], np.float64)


def _mercator_grid(products) -> tuple[Affine, int, int]:
    h, w = products.shape
    bounds = rasterio.transform.array_bounds(h, w, products.transform)   # (west, south, east, north)
    return calculate_default_transform(products.crs, MERCATOR, w, h, *bounds, resolution=RESOLUTION_M)[:3]


def to_web_mercator(arr: np.ndarray, products) -> tuple[np.ndarray, Affine]:
    """Raster modelu → EPSG:3857 (10 m, najbliższy sąsiad); NaN = brak danych. Bool/uint przez kopię float32."""
    dst_transform, w, h = _mercator_grid(products)
    src = np.asarray(arr).astype(np.float32)
    dst = np.full((h, w), np.nan, np.float32)
    reproject(src, dst, src_transform=products.transform, src_crs=products.crs,
              dst_transform=dst_transform, dst_crs=MERCATOR, resampling=Resampling.nearest,
              src_nodata=np.nan, dst_nodata=np.nan)
    return dst, dst_transform


def image_coordinates(dst_transform: Affine, shape) -> list[list[float]]:
    """Narożniki obrazu [lon, lat]: lewy górny, prawy górny, prawy dolny, lewy dolny (kolejność MapLibre)."""
    rows, cols = shape
    corners = [dst_transform @ c for c in ((0, 0), (cols, 0), (cols, rows), (0, rows))]
    lon, lat = Transformer.from_crs(MERCATOR, 4326, always_xy=True).transform(
        [c[0] for c in corners], [c[1] for c in corners])
    return [[float(x), float(y)] for x, y in zip(lon, lat)]


def layer_coordinates(products) -> list[list[float]]:
    """Narożniki obu obrazów warstw (obraz niepewności ma ten sam zasięg, tylko większą rozdzielczość)."""
    transform, w, h = _mercator_grid(products)
    return image_coordinates(transform, (h, w))


def _model_z(products) -> np.ndarray:
    return np.where(products.in_model & np.isfinite(products.z), products.z, np.nan).astype(np.float32)


def bottom_breaks(products) -> list[float]:
    """Percentyle 0, 20, 40, 60, 80, 100 skończonego `z` w modelu, zaokrąglone do 0,01."""
    z = _model_z(products)
    z = z[np.isfinite(z)]
    return [round(float(v), 2) for v in np.percentile(z, [0, 20, 40, 60, 80, 100])]


def _png(rgba: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_bottom_png(products, theme: str) -> bytes:
    """Dno w 5 klasach wg `bottom_breaks`; poza modelem i NaN przezroczyste."""
    breaks = bottom_breaks(products)
    z, _ = to_web_mercator(_model_z(products), products)
    ok = np.isfinite(z)
    cls = np.searchsorted(breaks[1:-1], np.where(ok, z, 0.0), side="left")   # 0..4; z ≤ próg → klasa niższa, także przy powtórzonych progach
    shallow, deep = (_rgb(c) for c in BOTTOM_COLORS[theme])
    palette = np.array([shallow + (deep - shallow) * i / (N_CLASSES - 1) for i in range(N_CLASSES)])
    rgba = np.zeros(z.shape + (4,), np.uint8)
    rgba[..., :3] = np.rint(palette[cls]).astype(np.uint8)
    rgba[..., 3] = np.where(ok, 255, 0)
    rgba[~ok, :3] = 0
    return _png(rgba)


def render_uncertainty_png(products, theme: str) -> bytes:
    """Kropki 1×1 w komórkach 2×2 (obraz 2×) tam, gdzie `unc` ≥ 0,5 m; reszta przezroczysta.

    Dlaczego 2×, nie 4×: na prawdziwej siatce obraz 4× ma 5748×4536 px (≈100 MB zdekodowanego RGBA),
    zbyt dużo dla telefonu; 2× to ≈26 MB, a deseń kropek nadal jest czytelny.
    """
    unc = np.where(products.in_model, products.unc, np.nan)
    flag = np.where(np.isfinite(unc), (unc >= UNC_MIN).astype(np.float32), np.nan)
    dst, _ = to_web_mercator(flag, products)
    dots = np.nan_to_num(dst, nan=0.0) > 0.5
    h, w = dots.shape
    big = np.zeros((h * UNC_SCALE, w * UNC_SCALE), bool)
    big[::UNC_SCALE, ::UNC_SCALE] = dots                      # kropka 1×1 w lewym górnym rogu komórki 2×2
    rgba = np.zeros(big.shape + (4,), np.uint8)
    rgba[big, :3] = _rgb(UNC_COLORS[theme]).astype(np.uint8)
    rgba[big, 3] = UNC_ALPHA
    return _png(rgba)
