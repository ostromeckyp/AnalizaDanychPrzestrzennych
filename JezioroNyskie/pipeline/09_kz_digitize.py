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

Co robi (`spots`): OCR rzędnych punktowych z pełnej mapy (kafle 1200 px, tesseract), parsowanie wzorca
  `.?ddd,d` w zakresie 185-200 m, kotwica = najbliższa izolowana kropka z dowolnej strony liczby, jeden do jednego (brak albo niejednoznaczna = odrzucenie), punkty poza obrysem jeziora + 100 m (legenda) odpadają, kolor
  tekstu i reguła niebieski <=> z < 195,0; georeferencja kotwicy transformacją odtworzoną z GCP i `kind` z
  kz_meta.json. Wejście → wyjście: data/raw/kz/kz_full.png → data/processed/kz/kz_spot_ocr.gpkg
  (id, z, color, conf, color_ok, px, py, anchor_side + tekst i ramka OCR; EPSG:2180) oraz kz_spot_ocr_raw.csv (wszystkie słowa).
  Jak to obronić: błędy OCR nie wchodzą do metryk bez kontroli (`ocr_error_rate` z próby ręcznej, `make kz-qc-ui`).

Co robi (`contours`): poziomice 192,5 i 195,0 m z pełnej mapy: maska koloru linii, poziom z sąsiedniego wypełnienia
  (config `kz.contour_colors`), szkielet -> linie, odrzucenie krótkich (kreski „orientacyjne”), transformacja
  do EPSG:2180, poziom 195,0 weryfikowany większością próbek (ląd | woda) wzdłuż linii, zewnętrzna z pary równoległych odpada,
  `kz.contour_drop` (środek+długość) usuwa fragmenty ewidentnie błędne. Wejście → wyjście: kz_full.png →
  data/processed/kz/kz_contours.gpkg (id, level, length_m; EPSG:2180) + qc_contours.png.
Co robi (`gravel`): obrys rejonu eksploatacji kruszywa (różowa linia przerywana na mapie) z wierzchołków
  data/reference/zwirownia_vertices.csv (piksele mapy, wskazane ręcznie) -> data/reference/zwirownia.gpkg
  (Polygon EPSG:2180, `source`, `licence_ref`). Wierzchołki są punktami z oglądu mapy: dokładność rzędu kilku metrów.

Użycie: uv run python 09_kz_digitize.py georef | spots | contours | gravel
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
LAKE_ZONE_BUFFER_M = 100.0   # punkty dalej niż 100 m od obrysu jeziora (legenda, opisy) odpadają
OCR_SCALES = (1.0, 2.0)   # przebieg 1x + przebieg na kaflach powiększonych 2x (R15)


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


def spots() -> int:
    """OCR rzędnych: wszystkie słowa -> filtr wzorca/zakresu -> kotwica (kropka) -> kolor -> georeferencja."""
    outdir = data_path("processed", "kz")
    meta = json.loads((outdir / "kz_meta.json").read_text())
    t = kz.fit_transform(load_gcp(), meta["kind"])      # ta sama transformacja co w georef (kind z kz_meta.json)
    Image.MAX_IMAGE_PIXELS = None
    img = np.asarray(Image.open(data_path("raw", "kz") / "kz_full.png").convert("RGB"))
    words = kz.ocr_tiles(img, scales=OCR_SCALES)
    words.to_csv(outdir / "kz_spot_ocr_raw.csv", index=False)
    words["z"] = words["text"].map(kz.parse_spot)
    cand = words[words["z"].notna()].reset_index(drop=True)
    log.info("słów OCR: %d, pasujących do wzorca i zakresu: %d", len(words), len(cand))
    digit_boxes = [tuple(b) for b in words.loc[words.text.str.contains(r"\d"), ["left", "top", "width", "height"]].to_numpy()]
    boxes = [(r.left, r.top, r.width, r.height) for r in cand.itertuples()]
    anchors = kz.spot_anchors(img, boxes, others=digit_boxes)   # najbliższa kropka z dowolnej strony, jeden do jednego
    rows, no_dot = [], 0
    for r, box, anchor in zip(cand.itertuples(), boxes, anchors):
        if anchor is None:
            no_dot += 1
            continue
        color = kz.text_color(img, box)
        rows.append({"z": r.z, "color": color, "conf": r.conf, "color_ok": kz.color_consistent(r.z, color),
                     "px": anchor[0], "py": anchor[1], "anchor_side": anchor[2], "text": r.text,
                     "left": r.left, "top": r.top, "width": r.width, "height": r.height})
    df = pd.DataFrame(rows).sort_values(["py", "px"]).reset_index(drop=True)
    df.insert(0, "id", np.arange(len(df)))
    x, y = t.px_to_2180(df["px"].to_numpy(), df["py"].to_numpy())
    lake = gpd.read_file(data_path("processed", "lake.gpkg"), layer="lake").geometry.union_all()
    in_zone = kz.in_lake_zone(x, y, lake, LAKE_ZONE_BUFFER_M)     # bez legendy i opisów poza zbiornikiem
    n_outside = int((~in_zone).sum())
    df, x, y = df[in_zone].reset_index(drop=True), x[in_zone], y[in_zone]
    df["id"] = np.arange(len(df))
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(x, y), crs="EPSG:2180")
    gdf.to_file(outdir / "kz_spot_ocr.gpkg", driver="GPKG", layer="spots",
                metadata={"source": "data/reference/KZ_ZRODLO_I_WARUNKI.md (mapa KŻ Nysa, W. Wróblewski 2023; "
                                    "nieodpłatnie, bez celów komercyjnych, kopia musi zawierać warunki)"})
    stats = {"words": len(words), "matched": len(cand), "no_dot_rejected": no_dot, "outside_lake_zone_dropped": n_outside,
             "accepted": len(df),
             "color_ok_share": round(float(df.color_ok.mean()), 3),
             "conf_quantiles": {q: round(float(df.conf.quantile(q)), 1) for q in (0.05, 0.25, 0.5, 0.75)},
             "conf_below_80": int((df.conf < kz.LOW_CONF).sum()), "colors": df.color.value_counts().to_dict(),
             "suspect_share": round(float(kz.is_suspect(df).mean()), 3),
             "anchor_sides": df.anchor_side.value_counts().to_dict(),
             "dot_decimal_words": int(words.text.str.fullmatch(r"\.?\d{3}\.\d").sum()),
             "source": "data/reference/KZ_ZRODLO_I_WARUNKI.md"}
    (outdir / "kz_spot_ocr_stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))
    log.info("spots: %s", stats)
    return 0


def contours() -> int:
    """Poziomice 192,5 / 195,0: maski poziomów -> linie -> EPSG:2180 -> GPKG + obrazek kontrolny."""
    from mielizna.config import load_config

    cfg = load_config()["kz"]
    outdir = data_path("processed", "kz")
    meta = json.loads((outdir / "kz_meta.json").read_text())
    t = kz.fit_transform(load_gcp(), meta["kind"])
    Image.MAX_IMAGE_PIXELS = None
    img = np.asarray(Image.open(data_path("raw", "kz") / "kz_full.png").convert("RGB"))
    masks = kz.contour_level_masks(img, cfg["contour_colors"])
    lake = gpd.read_file(data_path("processed", "lake.gpkg"), layer="lake").geometry.union_all()
    rows, geoms = [], []
    shore = lake.boundary
    for level in (192.5, 195.0):
        px_lines = kz.mask_to_lines(masks[level], cfg["contour_min_len_px"])
        votes = {"checked": len(px_lines), "not_shore": 0}
        kept_px = []
        for g in px_lines:
            if kz.is_axis_aligned(np.asarray(g.coords)):      # linie siatki wzdłuż osi obrazu
                votes["axis_aligned"] = votes.get("axis_aligned", 0) + 1
                continue
            if kz.is_straight(np.asarray(g.coords)):          # drogi, wały, granice użytków (cięciwa/długość >= 0,985)
                votes["straight"] = votes.get("straight", 0) + 1
                continue
            if level == 195.0:      # poziom z ziaren pikselowych bywa błędny: ostatecznie decyduje większość próbek wzdłuż linii
                frac, n_ok = kz.line_side_votes(img, np.asarray(g.coords), cfg.get("side_offset_px", 8))
                if n_ok < 3 or frac < cfg.get("shore_vote_min", 0.5):
                    votes["not_shore"] += 1
                    continue
            kept_px.append(g)
        lines2180 = [g for g in kz.lines_to_2180(kept_px, t)
                     if kz.in_lake_zone(*np.asarray(g.coords).T, lake, LAKE_ZONE_BUFFER_M).mean() >= 0.9]   # legenda, ramka, opisy
        if level == 195.0:
            keep = kz.drop_outer_parallels(lines2180, shore, cfg.get("parallel_tol_m", 12))
            votes["outer_parallel_dropped"] = int(len(keep) - sum(keep))
            lines2180 = [g for g, k in zip(lines2180, keep) if k]
        for g in lines2180:
            rows.append({"level": level, "length_m": round(g.length, 1)})
            geoms.append(g)
        log.info("poziom %.1f: %s, po filtrach: %d", level, votes, len(lines2180))
    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:2180")
    gdf = gdf.sort_values(["level", "length_m"], ascending=[True, False], kind="stable").reset_index(drop=True)
    gdf.insert(0, "id", np.arange(len(gdf)))              # id tylko do podglądu (numery na qc_contours.png)
    drops = cfg.get("contour_drop") or []
    hit = np.array(kz.match_drops(list(gdf.geometry), drops, tol_m=20.0), bool)   # po środku i długości, nie po numerze
    unmatched = [d for d in drops if not any(kz.match_drops([g], [d], 20.0)[0] for g in gdf.geometry)]
    if unmatched:
        log.warning("contour_drop: %d wpisów bez pasującej linii (mapa lub maski się zmieniły): %s", len(unmatched), unmatched)
    gdf = gdf[~hit].reset_index(drop=True)
    gdf["id"] = np.arange(len(gdf))
    gdf.to_file(outdir / "kz_contours.gpkg", driver="GPKG", layer="contours",
                metadata={"source": "data/reference/KZ_ZRODLO_I_WARUNKI.md (mapa KŻ Nysa, W. Wróblewski 2023)"})
    stats = {str(l): {"n": int((gdf.level == l).sum()), "length_km": round(float(gdf[gdf.level == l].length.sum()) / 1000, 2)}
             for l in (192.5, 195.0)}
    stats["dropped_by_centroid"] = int(hit.sum())
    (outdir / "kz_contours_stats.json").write_text(json.dumps(stats, indent=2))
    log.info("contours: %s", stats)
    contours_qc(img, t, gdf, outdir / "qc_contours.png")
    return 0


def contours_qc(img, t, gdf, out: Path):
    """Linie na mapie KŻ w pikselach (odwrotna transformacja), z numerami id."""
    fig, ax = plt.subplots(figsize=(24, 12), dpi=100)
    ax.imshow(img[::2, ::2], extent=(0, img.shape[1], img.shape[0], 0))
    for r in gdf.itertuples():
        xy = np.asarray(r.geometry.coords)
        px, py = t.inverse_2180(xy[:, 0], xy[:, 1])
        ax.plot(px, py, color="red" if r.level == 195.0 else "magenta", lw=1.0)
        m = len(px) // 2
        ax.text(px[m], py[m], str(r.id), fontsize=6, color="black", bbox=dict(fc="yellow", ec="none", pad=0.3, alpha=0.7))
    ax.set_title("QC poziomic KŻ: czerwone = 195,0 m, różowe = 192,5 m (numery = id). Źródło: data/reference/KZ_ZRODLO_I_WARUNKI.md")
    ax.set_xlim(2600, img.shape[1])
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def gravel() -> int:
    """Obrys rejonu eksploatacji kruszywa z ręcznie wskazanych wierzchołków (piksele mapy)."""
    outdir = data_path("processed", "kz")
    meta = json.loads((outdir / "kz_meta.json").read_text())
    t = kz.fit_transform(load_gcp(), meta["kind"])
    verts = pd.read_csv(data_path("reference", "zwirownia_vertices.csv"), comment="#")
    poly = kz.vertices_to_polygon(verts[["px", "py"]].to_numpy(), t)
    lake = gpd.read_file(data_path("processed", "lake.gpkg"), layer="lake").geometry.union_all()
    inside = poly.intersection(lake).area / poly.area
    gdf = gpd.GeoDataFrame({"name": ["rejon eksploatacji kruszywa (2023)"], "source": ["mapa KŻ Nysa, W. Wróblewski 2023"],
                            "licence_ref": ["data/reference/KZ_ZRODLO_I_WARUNKI.md"]}, geometry=[poly], crs="EPSG:2180")
    out = data_path("reference", "zwirownia.gpkg")
    out.unlink(missing_ok=True)
    gdf.to_file(out, driver="GPKG", layer="zwirownia",
                metadata={"licence_ref": "data/reference/KZ_ZRODLO_I_WARUNKI.md"})
    log.info("żwirownia: %d wierzchołków, pole %.0f ha, %.0f%% w obrysie jeziora", len(verts), poly.area / 1e4, 100 * inside)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("georef")
    sub.add_parser("spots")
    sub.add_parser("contours")
    sub.add_parser("gravel")
    args = ap.parse_args(argv)
    return {"georef": georef, "spots": spots, "contours": contours, "gravel": gravel}[args.cmd]()


if __name__ == "__main__":
    sys.exit(main())
