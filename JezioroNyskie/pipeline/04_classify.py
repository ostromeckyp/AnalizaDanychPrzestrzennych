"""04 - Klasyfikacja wszystkich scen modelem Random Forest (i progiem Otsu dla porównania).

Co robi: dla każdej sceny z `s2.usable_dates` liczy maskę wody RF (0/1/255), maskę Otsu po tych
  samych regułach, mapę P(woda) (uint8) i statystyki sceny.
Dlaczego tak: maski zostają na dysku, bo dalsze kroki (linie brzegowe, poziom wody, mapa mielizn)
  potrzebują pikseli brzegu, nie uproszczonych linii; chmura/cień/brak danych to 255, nie ląd.
Wejście → wyjście: data/processed/{s2/*.tif, model/rf_model.joblib, lake.gpkg}
  → data/processed/masks/{data}.tif, masks_otsu/{data}.tif, proba/{data}.tif (uint8, nodata 255)
  oraz classify_stats.csv (data, otsu_threshold, area_km2, area_otsu_km2, lake_nodata_pct,
  local_cloud_pct, core_usable_frac, core_water_frac, rf_otsu_ratio, qc_ok, qc_reason, model_sha).
  Log: data/processed/logs/04_classify.log. Powtórne uruchomienie pomija sceny gotowe (trzy pliki
  + wiersz statystyk z tym samym sha256 modelu); `--force` liczy od nowa. Wiersze i pliki scen,
  które nie są już w `usable_dates`, są usuwane. Każda scena przechodzi `check_radiometry`
  (uszkodzona scena przerywa skrypt) i `scene_qc` (flagi w CSV, ostrzeżenie w logu).
Jak to obronić: cała logika jest w `mielizna.classify` (testowana), skrypt tylko iteruje i zapisuje;
  zapis jest atomowy (plik tymczasowy), więc przerwanie nie zostawia uciętego pliku.
"""
import argparse
import hashlib
import logging

import numpy as np
import pandas as pd
import rasterio

from mielizna import rf
from mielizna.classify import analyze_scene, lake_core
from mielizna.config import data_path, load_config
from mielizna.grid import reference_grid
from mielizna.labels import load_scene
from mielizna.osm import aoi_mask, lake_mask
from mielizna.s2 import usable_dates

log = logging.getLogger("04_classify")
COLUMNS = ["date", "otsu_threshold", "area_km2", "area_otsu_km2", "lake_nodata_pct", "local_cloud_pct",
           "core_usable_frac", "core_water_frac", "rf_otsu_ratio", "qc_ok", "qc_reason", "model_sha"]
KINDS = ("masks", "masks_otsu", "proba")


def write_mask(path, arr, grid):
    """Zapisuje uint8 (nodata 255) jako GeoTIFF z kompresją; atomowo przez plik tymczasowy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with rasterio.open(tmp, "w", driver="GTiff", width=grid.width, height=grid.height, count=1,
                       dtype="uint8", crs=grid.crs, transform=grid.transform, nodata=255,
                       compress="deflate", tiled=True) as ds:
        ds.write(arr, 1)
    tmp.replace(path)


def save_stats(stats: dict, path) -> None:
    """Zapisuje statystyki scen (słownik data -> wiersz) jako CSV w kolejności COLUMNS."""
    pd.DataFrame.from_dict(stats, orient="index").rename_axis("date").sort_index().reset_index()[COLUMNS] \
        .to_csv(path, index=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="przelicz także gotowe sceny")
    args = ap.parse_args()
    proc = data_path("processed")
    (proc / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(proc / "logs" / "04_classify.log", encoding="utf-8"),
                                  logging.StreamHandler()])
    cfg = load_config()
    grid = reference_grid(cfg)
    aoi, lake = aoi_mask(grid), lake_mask(grid)
    core = lake_core(lake)
    model_path = proc / "model" / "rf_model.joblib"
    model_sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
    bundle = rf.load_model(model_path)
    log.info("Model: water_threshold=%.2f, jezioro %d px, rdzeń %d px", bundle["water_threshold"],
             lake.sum(), core.sum())
    dates = usable_dates(cfg)
    stats_path = proc / "classify_stats.csv"
    keep = set(dates)
    stats = (pd.read_csv(stats_path, dtype={"date": str}).set_index("date").to_dict("index")
             if stats_path.exists() and not args.force else {})
    stats = {d: v for d, v in stats.items() if d in keep}
    for kind in KINDS:                       # osierocone pliki dat spoza usable_dates
        for p in sorted((proc / kind).glob("*.tif")) if (proc / kind).exists() else []:
            if p.stem not in keep:
                p.unlink()
                log.info("usunięto osierocony plik %s/%s", kind, p.name)
    paths = lambda d: [proc / k / f"{d}.tif" for k in KINDS]
    for i, d in enumerate(dates, 1):
        if d in stats and stats[d].get("model_sha") == model_sha and all(p.exists() for p in paths(d)):
            continue
        bands, scl = load_scene(d, proc / "s2")
        r = analyze_scene(bands, scl, d, bundle, aoi, lake, core)
        stats[d] = {k: v for k, v in r.items() if k not in ("mask", "mask_otsu", "proba")} \
            | {"model_sha": model_sha}
        for p, arr in zip(paths(d), (r["mask"], r["mask_otsu"], r["proba"])):
            write_mask(p, arr, grid)
        save_stats(stats, stats_path)
        if not stats[d]["qc_ok"]:
            log.warning("%s: QC niezaliczone (%s): core_water %.3f, rf/otsu %.3f, core_usable %.2f", d,
                        stats[d]["qc_reason"], stats[d]["core_water_frac"], stats[d]["rf_otsu_ratio"],
                        stats[d]["core_usable_frac"])
        log.info("[%d/%d] %s: RF %.3f km2, Otsu %.3f km2, nodata %.1f%%", i, len(dates), d,
                 stats[d]["area_km2"], stats[d]["area_otsu_km2"], stats[d]["lake_nodata_pct"])
    save_stats(stats, stats_path)
    log.info("Gotowe: %d scen", len(dates))


if __name__ == "__main__":
    main()
