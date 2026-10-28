"""10 - Porównanie z mapą KŻ: wariant D (kontrola poziomów wody z powierzchni dna KŻ); dalsze podkomendy w Task 9.

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
  data/processed/kz/{levels_d.csv (date, h_t_d, dist_m), kz_surface.tif} i data/processed/eval/variant_d.json
  (n_scenes, share_within_0_2, median_abs_diff, by_method, pokrycie powierzchni, pominięte sceny).
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

from mielizna import kz, variant_d
from mielizna.config import data_path
from mielizna.grid import reference_grid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("10_kz_compare")
PRE_FLOOD_END = "2024-08-31"


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
        rows.append({"date": r.date, "h_t_d": round(h, 2), "dist_m": round(d, 1)})
    fit = pd.DataFrame(rows, columns=["date", "h_t_d", "dist_m"])
    out_kz = proc / "kz"
    fit.to_csv(out_kz / "levels_d.csv", index=False)

    sc = pd.DataFrame(json.loads((proc / "scenes.json").read_text(encoding="utf-8")))
    summ = variant_d.summarize(fit, sc)
    pre = fit[fit.date <= PRE_FLOOD_END]
    summ["pre_flood"] = {k: v for k, v in variant_d.summarize(pre, sc).items() if k != "by_method"}
    # warstwa dopisana PO obejrzeniu wyniku (powierzchnia nie sięga ponad ok. 195 m, bo ląd ma 7 czarnych punktów):
    # sceny z h_t < 195,0 m, gdzie powierzchnia w ogóle opisuje brzeg; nie zastępuje liczb głównych
    low = sc[sc.h_t < 195.0]
    summ["h_t_below_195"] = {k: v for k, v in variant_d.summarize(fit, low).items() if k != "by_method"}
    summ.update({"n_fitted": int(len(fit)), "n_skipped": len(skipped), "skipped": skipped,
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
    ap.add_argument("cmd", choices=["variant-d"])
    args = ap.parse_args(argv)
    return {"variant-d": run_variant_d}[args.cmd]()


if __name__ == "__main__":
    sys.exit(main())
