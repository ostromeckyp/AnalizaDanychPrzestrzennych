"""04 - Klasyfikacja wszystkich scen modelem Random Forest (i progiem Otsu dla porównania).

Co robi: dla każdej sceny z `s2.usable_dates` liczy maskę wody RF (0/1/255), maskę Otsu po tych
  samych regułach, mapę P(woda) (uint8) i statystyki sceny.
Dlaczego tak: maski zostają na dysku, bo dalsze kroki (linie brzegowe, poziom wody, mapa mielizn)
  potrzebują pikseli brzegu, nie uproszczonych linii; chmura/cień/brak danych to 255, nie ląd.
Wejście → wyjście: data/processed/{s2/*.tif, model/rf_model.joblib, lake.gpkg}
  → data/processed/masks/{data}.tif, masks_otsu/{data}.tif, proba/{data}.tif (uint8, nodata 255)
  oraz classify_stats.csv (data, otsu_threshold, area_km2, area_otsu_km2, lake_nodata_pct,
  local_cloud_pct). Log: data/processed/logs/04_classify.log. Powtórne uruchomienie pomija
  sceny gotowe (trzy pliki + wiersz statystyk); `--force` liczy od nowa.
Jak to obronić: cała logika jest w `mielizna.classify` (testowana), skrypt tylko iteruje i zapisuje;
  zapis jest atomowy (plik tymczasowy), więc przerwanie nie zostawia uciętego pliku.
"""
import argparse
import logging

import numpy as np
import pandas as pd
import rasterio

from mielizna import rf
from mielizna.classify import PIXEL_KM2, classify_scene_full, lake_core, otsu_scene_mask
from mielizna.config import data_path, load_config
from mielizna.grid import reference_grid
from mielizna.labels import load_scene
from mielizna.osm import aoi_mask, lake_mask
from mielizna.s2 import scene_quality, usable_dates, valid_mask

log = logging.getLogger("04_classify")
COLUMNS = ["date", "otsu_threshold", "area_km2", "area_otsu_km2", "lake_nodata_pct", "local_cloud_pct"]


def write_mask(path, arr, grid):
    """Zapisuje uint8 (nodata 255) jako GeoTIFF z kompresją; atomowo przez plik tymczasowy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with rasterio.open(tmp, "w", driver="GTiff", width=grid.width, height=grid.height, count=1,
                       dtype="uint8", crs=grid.crs, transform=grid.transform, nodata=255,
                       compress="deflate", tiled=True) as ds:
        ds.write(arr, 1)
    tmp.replace(path)


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
    bundle = rf.load_model(proc / "model" / "rf_model.joblib")
    log.info("Model: water_threshold=%.2f, jezioro %d px, rdzeń %d px", bundle["water_threshold"],
             lake.sum(), core.sum())
    dates = usable_dates(cfg)
    stats_path = proc / "classify_stats.csv"
    stats = (pd.read_csv(stats_path, dtype={"date": str}).set_index("date").to_dict("index")
             if stats_path.exists() and not args.force else {})
    paths = lambda d: [proc / k / f"{d}.tif" for k in ("masks", "masks_otsu", "proba")]
    for i, d in enumerate(dates, 1):
        if d in stats and all(p.exists() for p in paths(d)):
            continue
        bands, scl = load_scene(d, proc / "s2")
        mask, proba, t = classify_scene_full(bands, scl, d, bundle, aoi, core)
        m_otsu = otsu_scene_mask(bands, scl, aoi, core, t)
        q = scene_quality(d, scl, valid_mask(bands, scl), aoi, lake)
        stats[d] = {"otsu_threshold": t, "area_km2": (mask == 1).sum() * PIXEL_KM2,
                    "area_otsu_km2": (m_otsu == 1).sum() * PIXEL_KM2,
                    "lake_nodata_pct": 100 * float(((mask == 255) & lake).sum() / lake.sum()),
                    "local_cloud_pct": q["local_cloud_pct"]}
        for p, arr in zip(paths(d), (mask, m_otsu, proba)):
            write_mask(p, arr, grid)
        pd.DataFrame.from_dict(stats, orient="index").rename_axis("date").sort_index().reset_index()[COLUMNS] \
            .to_csv(stats_path, index=False)
        log.info("[%d/%d] %s: RF %.3f km2, Otsu %.3f km2, nodata %.1f%%", i, len(dates), d,
                 stats[d]["area_km2"], stats[d]["area_otsu_km2"], stats[d]["lake_nodata_pct"])
    log.info("Gotowe: %d scen", len(dates))


if __name__ == "__main__":
    main()
