"""09 - Mapa KŻ: georeferencja skanu (K1); kolejne podkomendy (OCR, izobaty) w następnych zadaniach.

Co robi (`georef`): wyciąga obraz z docs/JN_2023_05_23__KZ.pdf (PNG w data/raw/kz/, poza gitem), wczytuje GCP
  z data/reference/kz_gcp.csv, dopasowuje transformację afiniczną i wielomianową 2. stopnia, wybiera tę
  z mniejszym RMSE na punktach wstrzymanych (`check`), zapisuje raster RGBA 2 m w EPSG:2180, metadane
  (RMSE, werdykt, `dam_offset_m`) i nakładkę kontrolną qc_georef.png.
Dlaczego tak: siatka stopni/minut na mapie daje punkty niezależne od OSM; wstrzymane punkty mierzą błąd
  uczciwie (RMSE dopasowania przy wielomianie bywa zbyt optymistyczny). `dam_offset_m` jest kontrolą
  zewnętrzną: korona zapory na mapie (ciemna linia) kontra linia zapory z OSM (warstwa `dam` w lake.gpkg).
  Raster powstaje odwrotnym mapowaniem (dla piksela wyniku liczymy piksel źródła; `map_coordinates`, order=1).
Wejście → wyjście: docs/JN_2023_05_23__KZ.pdf, data/reference/kz_gcp.csv, lake.gpkg →
  data/processed/kz/kz_map_2180.tif, kz_meta.json (kind, rmse_fit, rmse_check, n_fit, n_check,
  dam_offset_m, dam_offset_spread_m, dam_offset_n, verdict, rmse_scope, rmse_by_kind), qc_georef.png. Pliki pochodne z mapy: patrz
  data/reference/KZ_ZRODLO_I_WARUNKI.md (nie do commitu, data/processed jest w .gitignore).
Jak to obronić: werdykt z progów briefu (5/10 m); porównanie dwóch rodzajów transformacji na tych samych
  punktach wstrzymanych; nakładka oglądana wzrokowo; zapora jako kontrola niezależna od GCP.

Użycie: uv run python 09_kz_digitize.py georef
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
import shapely
from PIL import Image
from rasterio.transform import from_origin
from scipy.ndimage import map_coordinates

from mielizna import kz
from mielizna.config import data_path

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("09_kz_digitize")

PDF = Path(__file__).resolve().parent.parent / "docs" / "JN_2023_05_23__KZ.pdf"
RES_M = 2.0
DAM_SEARCH_M = 30.0
DAM_PROFILE_M = 100.0
DAM_LAKE_DIST_M = 50.0
DAM_BAND_WIDTH_M = 46.0


def load_gcp() -> pd.DataFrame:
    return pd.read_csv(data_path("reference", "kz_gcp.csv"), comment="#")


def warp_image(img: np.ndarray, t: kz.KzTransform, res: float = RES_M):
    """Raster RGBA w EPSG:2180: obwiednia obrazu przeniesiona wprzód, piksele wyniku przez odwrotne mapowanie."""
    h, w = img.shape[:2]
    cx, cy = np.array([0, w - 1, 0, w - 1.0]), np.array([0, 0, h - 1, h - 1.0])
    ex, ey = t.px_to_2180(cx, cy)
    x0, x1 = np.floor(ex.min() / res) * res, np.ceil(ex.max() / res) * res
    y0, y1 = np.floor(ey.min() / res) * res, np.ceil(ey.max() / res) * res
    nx, ny = int((x1 - x0) / res), int((y1 - y0) / res)
    gx = x0 + (np.arange(nx) + 0.5) * res
    gy = y1 - (np.arange(ny) + 0.5) * res
    X, Y = np.meshgrid(gx, gy)
    sx, sy = t.inverse_2180(X.ravel(), Y.ravel())
    sx, sy = sx.reshape(X.shape), sy.reshape(X.shape)
    out = np.zeros((4, ny, nx), np.uint8)
    for b in range(3):
        out[b] = np.clip(map_coordinates(img[..., b].astype(np.float32), [sy, sx], order=1, cval=0), 0, 255)
    out[3] = ((sx >= 0) & (sx <= w - 1) & (sy >= 0) & (sy <= h - 1)) * 255
    return out, from_origin(x0, y1, res, res)


def dam_offset(rgba: np.ndarray, transform, dam: gpd.GeoDataFrame, lake_geom) -> dict:
    """Przesunięcie pasa zapory na mapie względem linii OSM `dam` (strona wodna).

    Odniesienie: warstwa `dam` to 5 zamkniętych pierścieni (obrysy obszarów zapory, nie linie korony), więc
    pełny pierścień zawiera też skarpę od lądu. Bierzemy tylko części brzegów pierścieni w 50 m od obrysu
    jeziora (`kz.lake_facing_edges`): krawędź od strony wody. Wzdłuż normalnych (co 25 m, profil ±100 m)
    środek pasa estymuje `kz.band_centre` (szablon o szerokości DAM_BAND_WIDTH_M = 46 m, wartość z mediany
    profilów w pierwszej wersji kontroli). Znak: dodatnie = środek pasa na mapie leży dalej od jeziora niż
    linia OSM. Zwraca medianę, rozrzut 1,4826·MAD i liczbę profili."""
    gray = rgba[:3].astype(np.float32).mean(0)
    res = transform.a
    d = np.arange(-DAM_PROFILE_M, DAM_PROFILE_M + 1, res)
    offs = []
    for geom in kz.lake_facing_edges(list(dam.geometry), lake_geom, DAM_LAKE_DIST_M):
        for s in np.arange(30, geom.length - 30, 25.0):
            p, q = geom.interpolate(s), geom.interpolate(s + 5)
            tx, ty = q.x - p.x, q.y - p.y
            n = np.hypot(tx, ty)
            nx_, ny_ = -ty / n, tx / n
            if lake_geom.distance(shapely.Point(p.x + nx_ * 5, p.y + ny_ * 5)) < lake_geom.distance(p):
                nx_, ny_ = -nx_, -ny_   # normalna ma wskazywać od jeziora
            cols = ((p.x + nx_ * d - transform.c) / res).astype(int)
            rows = ((transform.f - (p.y + ny_ * d)) / res).astype(int)
            if (cols < 1).any() or (rows < 1).any() or (cols >= gray.shape[1] - 1).any() or (rows >= gray.shape[0] - 1).any():
                continue
            c = kz.band_centre(gray[rows, cols], d, DAM_BAND_WIDTH_M, DAM_SEARCH_M)
            if c is not None:
                offs.append(c)
    offs = np.array(offs)
    if len(offs) < 10:
        return {"dam_offset_m": None, "dam_offset_spread_m": None, "dam_offset_n": int(len(offs))}
    med = float(np.median(offs))
    spread = float(1.4826 * np.median(np.abs(offs - med)))
    out = {"dam_offset_m": round(med, 1), "dam_offset_spread_m": round(spread, 1), "dam_offset_n": int(len(offs))}
    if spread > 10:
        out["dam_offset_note"] = "qualitative"
    return out


def qc_overlay(rgba, transform, lake: gpd.GeoDataFrame, dam: gpd.GeoDataFrame, out: Path):
    h, w = rgba.shape[1:]
    ext = (transform.c, transform.c + w * transform.a, transform.f - h * transform.a, transform.f)
    fig, ax = plt.subplots(figsize=(14, 7), dpi=110)
    ax.imshow(np.moveaxis(rgba[:3], 0, -1), extent=ext, alpha=0.55)
    lake.boundary.plot(ax=ax, color="red", linewidth=0.8)
    dam.plot(ax=ax, color="magenta", linewidth=1.0)
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_title("QC georeferencji KŻ (półprzezroczysta) + obrys jeziora OSM (czerwony) + zapora OSM (magenta)\n"
                 "Źródło mapy: data/reference/KZ_ZRODLO_I_WARUNKI.md", fontsize=9)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def georef() -> int:
    outdir = data_path("processed", "kz")
    raw = data_path("raw", "kz")
    png = raw / "kz_full.png"
    if not png.exists():
        size = kz.extract_image(PDF, png)
        log.info("obraz %s", size)
    Image.MAX_IMAGE_PIXELS = None
    img = np.asarray(Image.open(png).convert("RGB"))
    gcp = load_gcp()
    fits = {k: kz.fit_transform(gcp, k) for k in ("affine", "poly2")}
    for k, t in fits.items():
        log.info("%s: rmse_fit=%.2f m, rmse_check=%.2f m (n_fit=%d, n_check=%d)", k, t.rmse_fit, t.rmse_check, t.n_fit, t.n_check)
    kind = min(fits, key=lambda k: fits[k].rmse_check)
    t = fits[kind]
    rgba, transform = warp_image(img, t)
    outdir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(outdir / "kz_map_2180.tif", "w", driver="GTiff", height=rgba.shape[1], width=rgba.shape[2],
                       count=4, dtype="uint8", crs="EPSG:2180", transform=transform, compress="deflate") as dst:
        dst.update_tags(source="data/reference/KZ_ZRODLO_I_WARUNKI.md")
        dst.write(rgba)
    lake_path = data_path("processed", "lake.gpkg")
    lake = gpd.read_file(lake_path, layer="lake")
    dam = gpd.read_file(lake_path, layer="dam")
    d = dam_offset(rgba, transform, dam, lake.geometry.union_all())
    meta = {"kind": kind, "rmse_fit": round(t.rmse_fit, 2), "rmse_check": round(t.rmse_check, 2),
            "n_fit": t.n_fit, "n_check": t.n_check, **d, "verdict": kz.verdict(t.rmse_check),
            "rmse_scope": "graticule-internal",
            "rmse_by_kind": {k: {"rmse_fit": round(v.rmse_fit, 2), "rmse_check": round(v.rmse_check, 2)} for k, v in fits.items()},
            "source": "data/reference/KZ_ZRODLO_I_WARUNKI.md"}
    (outdir / "kz_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    qc_overlay(rgba, transform, lake, dam, outdir / "qc_georef.png")
    log.info("meta: %s", meta)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_subparsers(dest="cmd", required=True).add_parser("georef")
    args = ap.parse_args(argv)
    return georef() if args.cmd == "georef" else 2


if __name__ == "__main__":
    sys.exit(main())
