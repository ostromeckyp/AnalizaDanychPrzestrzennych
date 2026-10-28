"""10 - Porównanie z mapą KŻ: wariant D (kontrola poziomów wody) oraz K5: punkty, poziomice, nakładka.

Podkomendy K5 (`points`, `contours`, `overlay`; `compare` = points + contours + kz_compare.json): porównują dno modelu
  `pre_flood` z rzędnymi punktowymi i poziomicami mapy KŻ (mielizna/kz_compare.py), zapisują
  data/processed/eval/{kz_points,kz_contours,kz_compare}.json i docs/img/kz-overlay.png (mapa KŻ pod strefami modelu).
  Wynik jest orientacyjny: mapa KŻ jest amatorska, a poziomice to próbka „precision-first” (patrz kz_contours_stats.json).
  Układ wysokości KŻ jest nieznany: bias jest zestawiany z `datum_offset` i biasami LiDAR, bez korekt (go_no_go.notes).
  Punkty bez ręcznej kontroli (jeśli są) wchodzą po filtrze koloru i pewności; `ocr_error_rate` jest ważony warstwami.
  Użycie: uv run python 10_kz_compare.py {points|contours|overlay|compare}

Co robi (`variant-d`): z punktów rzędnych KŻ (po kontroli ręcznej, a bez niej po filtrze koloru i pewności OCR;
  `kz.load_qc_spots`) i poziomic 192,5 oraz 195,0 m buduje powierzchnię dna (TIN na siatce modelu, NaN poza otoczką
  i w żwirowni), potem dla każdej sceny z shorelines.gpkg szuka rzędnej h (siatka 192,5-198,0 co 0,05 m), przy której
  poziomica powierzchni leży najbliżej linii brzegowej sceny (punkty co 10 m).
Dlaczego tak: to niezależna kontrola `h_t` z innego źródła niż komunikaty RZGW, LiDAR i krzywa powierzchnia-rzędna;
  wynik NIGDY nie jest źródłem `h_t`. Skrypt nie dotyka scenes.json: `h_t_d` i `h_diff_d` dokleja 06_water_levels.py
  z pliku levels_d.csv (inaczej ponowne uruchomienie 06 gubiłoby D). Sceny z mniej niż `variant_d.MIN_POINTS` punktów
  brzegu z powierzchnią są pomijane z powodem w variant_d.json.
Wejście → wyjście: data/processed/kz/{kz_spot_ocr.gpkg, kz_contours.gpkg}, data/reference/{zwirownia.gpkg,
  kz_spot_qc.csv (opcjonalnie, tylko odczyt)}, data/processed/{shorelines.gpkg, scenes.json, lake.gpkg} →
  data/processed/kz/{levels_d.csv (date, h_t_d, dist_m, d_valid), kz_surface.tif} i data/processed/eval/variant_d.json
  (n_scenes, share_within_0_2, median_abs_diff, by_method, pokrycie powierzchni, pominięte sceny).
Dziedzina: `in_domain` i `d_valid` używają `h_t` ze scenes.json z chwili uruchomienia (czyli poziomu odniesienia, który
  D kontroluje; zmiana h_t przez ponowne 06 zmienia dziedzinę, więc po 06 uruchom wariant D jeszcze raz).
Jak to obronić: patrz mielizna/variant_d.py; liczby i ich interpretacja w docs/nauka/M7-lidar-kz.md (sekcja wariant D).
  Użycie: uv run python 10_kz_compare.py variant-d
"""
import argparse
import json
import logging
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.features import rasterize

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import textwrap
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from pathlib import Path

from mielizna import bottom, kz, kz_compare, variant_d
from mielizna.config import data_path
from mielizna.grid import reference_grid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("10_kz_compare")
PRE_FLOOD_END = "2024-08-31"
IMG = Path(__file__).resolve().parents[1] / "docs" / "img"
UWAGA = ("UWAGA: 1. Dane zawarte w obrysie zbiornika pozyskano i odwzorowano sposobem amatorskim, toteż mogą być obarczone błędami. "
         "2. Niniejszą mapkę udostępnia się nieodpłatnie, zatem nie może służyć celom komercyjnym. "
         "3. CAŁOŚĆ RYZYKA związanego z ewentualnymi stratami powstałymi wskutek decyzji korzystania z mapki PONOSI UŻYTKOWNIK. "
         "KAŻDA KOPIA MAPKI MUSI ZAWIERAĆ POWYŻSZE WARUNKI. DNO ZBIORNIKA PONIŻEJ RZĘDNEJ 192.5 ODWZOROWANO ORIENTACYJNIE "
         "Z POWODU NIEWYSTARCZAJĄCEJ ILOŚCI DANYCH.")
SOURCE = ("Tło: Wiktor Wróblewski, KŻ Nysa, „Jezioro Nyskie (amatorska mapka dla wodniaków)”, aktualizacja 23.05.2023; "
          "dane otoczenia: OpenStreetMap.org. Źródło i warunki: data/reference/KZ_ZRODLO_I_WARUNKI.md")
SOURCE_REF = "data/reference/KZ_ZRODLO_I_WARUNKI.md"
DRAFT, MARGIN = 0.5, 0.3      # parametry ilustracyjne stref nakładki (zanurzenie, zapas); to nie jest wynik oceny


def _qc_spots():
    proc = data_path("processed")
    ocr = gpd.read_file(proc / "kz" / "kz_spot_ocr.gpkg")
    qc_path = data_path("reference", "kz_spot_qc.csv")
    qc = pd.read_csv(qc_path) if qc_path.exists() else None
    return ocr, qc, kz.load_qc_spots(ocr, qc)


def _clean(o):
    """NaN/inf -> None (JSON bez NaN, bo backend i przeglądarka go nie przyjmą)."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    return o


def _write(name: str, obj) -> None:
    obj = _clean(obj)
    out = data_path("processed", "eval")
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_points() -> dict:
    proc = data_path("processed")
    grid = reference_grid()
    ocr, qc, spots = _qc_spots()
    meta = _json(proc / "kz" / "kz_meta.json")
    gravel = gpd.read_file(data_path("reference", "zwirownia.gpkg")).geometry.union_all()
    model, _ = bottom.read_model(proc / "model" / "pre_flood")
    npp = kz_compare.npp_level(pd.read_csv(data_path("reference", "kz_pojemnosc_rzedna.csv")))
    res = kz_compare.compare_points(spots, model, gravel, npp=npp, grid=grid, verdict=meta["verdict"])
    res.update({"georef_verdict": meta["verdict"], "georef_rmse_check_m": meta["rmse_check"], "model": "pre_flood",
                "n_spots_used": int(len(spots)), "n_spots_checked": int(spots.checked.sum()),
                "spots_source": spots.z_source.value_counts().to_dict(),
                "gravel_excluded": int(shapely.contains_xy(gravel, spots.geometry.x, spots.geometry.y).sum()),
                "bias_definition": "bias = średnia(model z - KŻ z)", "indicative": True, "source": SOURCE_REF})
    if qc is not None and len(qc):
        matched, n_unmatched = kz.match_qc(qc, ocr)                          # QC z kotwicą -> id punktu OCR
        matched = matched.merge(ocr[["id", "color_ok", "conf"]], on="id", how="left")
        rate, n_ev = kz.ocr_error_rate(matched, ocr)
        res["ocr_error_rate"] = {"rate_weighted": rate, "n_judged": n_ev, "n_population": int(len(ocr)), "n_unmatched_qc_rows": n_unmatched,
                                 "qc_counts": qc.qc.value_counts().to_dict(),
                                 "note": "ważony warstwami (podejrzane vs pewne); próg roboczy <= 10 % na próbie >= 200"}
    _write("kz_points.json", res)
    p = res["pooled"]
    log.info("punkty: pooled n=%d rmse=%.2f bias=%+.2f in_bounds=%.2f; pasma %s", p["n"], p["rmse"], p["bias"], p["share_in_bounds"],
             {k: (res[k]["n"], round(res[k]["bias"], 2) if res[k]["n"] else None) for k in kz_compare.BAND_KEYS})
    return res


def run_contours() -> dict:
    proc = data_path("processed")
    grid = reference_grid()
    model, _ = bottom.read_model(proc / "model" / "pre_flood")
    kzc = gpd.read_file(proc / "kz" / "kz_contours.gpkg")
    res = {"model": "pre_flood", "indicative": True, "source": SOURCE_REF,
           "note": "poziomice KŻ to próbka precision-first (nie cała poziomica); wynik orientacyjny"}
    for level in (192.5, 195.0):
        kz_geom = shapely.union_all(kzc[kzc.level == level].geometry.to_numpy())
        r = kz_compare.compare_contours(kz_geom, kz_compare.model_contour(model["z"], grid, level))
        r["n_kz_lines"] = int((kzc.level == level).sum())
        res[f"{level:.1f}"] = r
        log.info("poziomica %.1f: %s", level, {k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()})
    _write("kz_contours.json", res)
    return res


def compare_inputs() -> tuple[float, dict]:
    """Wejścia `compare` spoza KŻ: poprawka KRON86->EVRF2007 z lidar/epochs.csv i eval/bottom_vs_nmt.json (bias all, pre_flood).

    Brak pliku lub klucza kończy skrypt czytelnym komunikatem (SystemExit) z poleceniem, które go tworzy, zamiast KeyError."""
    proc = data_path("processed")
    ep_path, nmt_path = proc / "lidar" / "epochs.csv", proc / "eval" / "bottom_vs_nmt.json"
    if not ep_path.exists():
        raise SystemExit(f"brak {ep_path}: najpierw `make lidar-epochs` (06b_lidar_levels.py --epochs-only)")
    if not nmt_path.exists():
        raise SystemExit(f"brak {nmt_path}: najpierw `make evaluate` (08_evaluate.py)")
    ep = pd.read_csv(ep_path)
    kron = ep.loc[ep.uklad_h != "PL-EVRF2007-NH", "datum_offset"] if {"uklad_h", "datum_offset"} <= set(ep.columns) else []
    if len(kron) == 0:
        raise SystemExit(f"{ep_path}: brak epoki w KRON86 z kolumną datum_offset; odtwórz plik: `make lidar-epochs`")
    nmt = _json(nmt_path)
    missing = [k for k in ("all", "pre_flood") if not isinstance(nmt.get(k), dict) or "bias" not in nmt[k]]
    if missing:
        raise SystemExit(f"{nmt_path}: brak {missing}.bias (stary format?); odtwórz plik: `make evaluate` (08_evaluate.py)")
    return float(kron.iloc[0]), nmt


def run_compare() -> int:
    offset, nmt = compare_inputs()          # przed długimi krokami: brak wejść = szybki, czytelny błąd
    pts = run_points()
    con = run_contours()
    others = {"wszystkie epoki, model all": nmt["all"]["bias"], "pre_flood zbiorczo": nmt["pre_flood"]["bias"]}
    p = pts["pooled"]
    gng = kz_compare.go_no_go(p["bias"], offset, others)
    out = {"points": {k: p[k] for k in ("rmse", "bias", "mae", "n", "bands", "share_in_bounds", "n_spots")},
           "go_no_go": gng, "ocr_error_rate": pts.get("ocr_error_rate"), "bands": {k: pts[k] for k in kz_compare.BAND_KEYS},
           "contours": {k: v for k, v in con.items() if k[0].isdigit()}, "georef_verdict": pts["georef_verdict"],
           "unit": pts["unit"], "npp": pts["npp"], "indicative": True,
           "source": SOURCE_REF}
    _write("kz_compare.json", out)
    log.info("go/no-go: %s (bias %+.2f)", gng["decision"], p["bias"])
    return 0


def run_overlay() -> int:
    proc = data_path("processed")
    grid = reference_grid()
    model, _ = bottom.read_model(proc / "model" / "pre_flood")
    npp = kz_compare.npp_level(pd.read_csv(data_path("reference", "kz_pojemnosc_rzedna.csv")))
    zl, zh, z = model["z_min"], model["z_max"], model["z"]
    obs, flags = model["obs_count"], model["flags"]
    in_model = ~((obs == 0) | (obs == 65535) | (flags == 255))     # jak backend/app/data.py
    lo = np.where(in_model, np.where(np.isnan(zl), -np.inf, zl), np.nan)   # NaN w z_min = zawsze woda, w z_max = zawsze ląd
    hi = np.where(in_model, np.where(np.isnan(zh), np.inf, zh), np.nan)
    with np.errstate(invalid="ignore"):
        cls = np.full(z.shape, 2, int)                          # 2 = ryzyko
        cls[npp - hi >= DRAFT + MARGIN] = 1                     # 1 = bezpiecznie (jak backend/app/zones.py)
        cls[npp - lo < DRAFT] = 3                               # 3 = zbyt płytko
    cls = np.where(in_model & (npp > lo), cls, 0)                # tylko woda przy NPP (jak zone_stats: h > z_lo)
    cmap = ListedColormap([(0, 0, 0, 0), (0.1, 0.65, 0.25, 0.5), (0.95, 0.75, 0.1, 0.5), (0.85, 0.15, 0.15, 0.5)])
    with rasterio.open(proc / "kz" / "kz_map_2180.tif") as ds:
        img = np.moveaxis(ds.read(), 0, -1)
        b = ds.bounds
    rgba = img.astype(float) / 255.0
    rgba[..., 3] = 0.55 * rgba[..., 3]                          # mapa KŻ półprzezroczysta
    fig, ax = plt.subplots(figsize=(13, 7.4))
    ax.imshow(rgba, extent=(b.left, b.right, b.bottom, b.top), interpolation="bilinear")
    xmin, ymin, xmax, ymax = grid.bounds()
    ax.imshow(cls, extent=(xmin, xmax, ymin, ymax), cmap=cmap, vmin=0, vmax=3, interpolation="nearest")
    for level, col in ((192.5, "#7b3294"), (195.0, "#d7301f")):        # 192,5 m: model go nie ma (z_min = 192,94), pętla nic nie rysuje
        for g in kz_compare.model_contour(z, grid, level).geoms:
            ax.plot(*g.xy, color=col, lw=1.0)
    kzc = gpd.read_file(proc / "kz" / "kz_contours.gpkg")
    for level, col in ((192.5, "#7b3294"), (195.0, "#d7301f")):
        for g in kzc[kzc.level == level].geometry:
            ax.plot(*g.xy, color=col, lw=1.0, ls=(0, (1, 2)), alpha=0.9)
    _, _, spots = _qc_spots()
    ax.scatter(spots.geometry.x, spots.geometry.y, s=3, c="k", alpha=0.6, zorder=5)
    ax.set_xlim(b.left, b.right); ax.set_ylim(b.bottom, b.top); ax.set_aspect("equal"); ax.axis("off")
    ax.legend(handles=[Patch(color=(0.1, 0.65, 0.25, 0.6), label=f"strefa bezpieczna (zanurzenie {DRAFT} m + zapas {MARGIN} m)"),
                       Patch(color=(0.95, 0.75, 0.1, 0.6), label="strefa ryzyka"), Patch(color=(0.85, 0.15, 0.15, 0.6), label="zbyt płytko"),
                       Line2D([], [], color="#7b3294", ls=":", label="poziomica 192,5 m: KŻ (model nie ma tej poziomicy)"),
                       Line2D([], [], color="#d7301f", label="poziomica 195,0 m: model (ciągła) / KŻ (kropkowana)"),
                       Line2D([], [], marker="o", color="k", ls="", ms=3, label="rzędne punktowe KŻ użyte w ocenie")],
              loc="upper left", fontsize=7.5, framealpha=0.9)
    ax.set_title(f"Model dna (pre_flood) na tle mapy KŻ Nysa; strefy przy NPP = {npp:.2f} m n.p.m. (ilustracja, nie ocena)", fontsize=10)
    fig.text(0.01, 0.01, "\n".join(textwrap.wrap(SOURCE, 190) + textwrap.wrap(UWAGA, 190)), fontsize=6, va="bottom", ha="left")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.14)
    IMG.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMG / "kz-overlay.png", dpi=130)
    log.info("zapisano %s", IMG / "kz-overlay.png")
    return 0


def run_points_cmd() -> int:
    run_points()
    return 0


def run_contours_cmd() -> int:
    run_contours()
    return 0


def run_variant_d() -> int:
    proc = data_path("processed")
    grid = reference_grid()
    ocr = gpd.read_file(proc / "kz" / "kz_spot_ocr.gpkg")
    qc_path = data_path("reference", "kz_spot_qc.csv")
    qc = pd.read_csv(qc_path) if qc_path.exists() else None            # tylko odczyt
    spots = kz.load_qc_spots(ocr, qc)
    log.info("punkty KŻ: %d z %d OCR (%s)", len(spots), len(ocr), spots.z_source.value_counts().to_dict())
    contours = gpd.read_file(proc / "kz" / "kz_contours.gpkg")
    gravel = gpd.read_file(data_path("reference", "zwirownia.gpkg")).geometry.union_all()
    surf = variant_d.kz_surface(spots, contours, grid, gravel=gravel)

    lake = gpd.read_file(proc / "lake.gpkg", layer="lake").geometry.union_all()
    lake_mask = rasterize([(lake, 1)], out_shape=(grid.height, grid.width), transform=grid.transform,
                          fill=0, dtype="uint8").astype(bool)
    cover = float(np.isfinite(surf[lake_mask]).mean())
    log.info("pokrycie powierzchni: %.1f %% obszaru jeziora", 100 * cover)
    with rasterio.open(proc / "kz" / "kz_surface.tif", "w", driver="GTiff", height=grid.height, width=grid.width,
                       count=1, dtype="float32", crs=grid.crs, transform=grid.transform, nodata=np.nan,
                       compress="deflate") as dst:
        dst.write(surf.astype("float32"), 1)

    hmax = variant_d.h_max_valid(surf, grid, variant_d.LEVELS)
    log.info("h_max_valid = %.2f m (poziomica >= %.0f %% długości na %.1f m)", hmax, 100 * variant_d.MIN_LENGTH_FRAC,
             variant_d.REF_LEVEL)
    sc = pd.DataFrame(json.loads((proc / "scenes.json").read_text(encoding="utf-8")))
    h_ref = dict(zip(sc.date, sc.h_t.astype(float)))                    # poziom odniesienia: tylko do określenia dziedziny
    trees = variant_d.level_trees(surf, grid, variant_d.LEVELS)
    shores = gpd.read_file(proc / "shorelines.gpkg")
    rows, skipped = [], []
    for r in shores.itertuples():
        if not bool(r.qc_ok):
            skipped.append({"date": r.date, "reason": "scena odrzucona przez QC"})
            continue
        shore = r.geometry.difference(gravel) if gravel is not None else r.geometry   # brzeg przy żwirowni pomijamy
        if shore.is_empty:
            skipped.append({"date": r.date, "reason": "pusta linia brzegowa"})
            continue
        h, d = variant_d.fit_level(shore, surf, grid, variant_d.LEVELS, trees=trees)
        if not np.isfinite(h):
            skipped.append({"date": r.date, "reason": f"mniej niż {variant_d.MIN_POINTS} punktów brzegu z powierzchnią"})
            continue
        rows.append({"date": r.date, "h_t_d": round(h, 2), "dist_m": round(d, 1),
                     "d_valid": variant_d.is_valid(h, d, hmax, variant_d.LEVELS, h_ref=h_ref.get(r.date, np.nan)),
                     "in_domain": bool(h_ref.get(r.date, np.nan) < hmax)})
    fit = pd.DataFrame(rows, columns=["date", "h_t_d", "dist_m", "d_valid", "in_domain"])
    out_kz = proc / "kz"
    fit.to_csv(out_kz / "levels_d.csv", index=False)

    sc = pd.DataFrame(json.loads((proc / "scenes.json").read_text(encoding="utf-8")))
    # metryki główne tylko na fitach ważnych (d_valid): poza zakresem powierzchni D jest "nasycone" i nic nie mówi
    valid = fit[fit.d_valid]
    summ = variant_d.summarize(valid, sc)
    summ["population"] = "h_t < h_max_valid and d_valid"            # metryki główne dotyczą tylko tej populacji
    pre = valid[valid.date <= PRE_FLOOD_END]
    summ["pre_flood"] = {k: v for k, v in variant_d.summarize(pre, sc).items() if k != "by_method"}
    summ["all_fits_unfiltered"] = variant_d.summarize(fit, sc)      # dla porównania z wersją sprzed poprawki
    summ.update({"n_fitted": int(len(fit)), "n_valid": int(len(valid)), "n_out_of_domain": int((~fit.in_domain).sum()), "h_max_valid": hmax, "n_skipped": len(skipped), "skipped": skipped,
                 "surface_coverage_lake": cover, "n_spots": int(len(spots)), "spots_source": spots.z_source.value_counts().to_dict(),
                 "median_dist_m": float(fit.dist_m.median()) if len(fit) else None,
                 "levels": [float(variant_d.LEVELS[0]), float(variant_d.LEVELS[-1]), 0.05],
                 "min_points": variant_d.MIN_POINTS})
    out_eval = proc / "eval"
    out_eval.mkdir(parents=True, exist_ok=True)
    (out_eval / "variant_d.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("D: dopasowano %d scen, pominięto %d; ±0,2 m: %s; mediana |D-h_t| %s m",
             len(fit), len(skipped), summ["share_within_0_2"], summ["median_abs_diff"])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["variant-d", "points", "contours", "overlay", "compare"])
    args = ap.parse_args(argv)
    return {"variant-d": run_variant_d, "points": run_points_cmd, "contours": run_contours_cmd,
            "overlay": run_overlay, "compare": run_compare}[args.cmd]()


if __name__ == "__main__":
    sys.exit(main())
