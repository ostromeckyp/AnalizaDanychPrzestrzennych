"""01 - Sentinel-2 L2A: wyszukanie scen, ocena jakości i zapis stosów na siatkę wzorcową.

Co robi: wyszukuje kafle Sentinel-2 L2A (Earth Search) nad jeziorem, w przebiegu 1 ocenia każdą
  akwizycję samą warstwą SCL (wiersz w scenes_candidates.csv), w przebiegu 2 wczytuje 6 pasm
  tylko dla scen użytecznych i zapisuje je jako COG (7 pasm: 6 pasm odbicia + SCL).
Dlaczego tak: SCL jest mała i szybka, więc odrzucamy chmury, lód i częściowe kafle zanim
  pobierzemy 6 pasm; DN==0 to brak danych, a nodata jest uwzględniane przed interpolacją
  dwuliniową pasm 20 m -> 10 m (SCL: najbliższy sąsiad); kafle tej samej akwizycji są mozaikowane
  pierwszym ważnym pikselem, nigdy między platformami. Dane Earth Search są już zharmonizowane
  (offset 0), co pilnuje check_harmonized.
Wejście → wyjście: Earth Search STAC + COG na S3 → data/raw/s2_items.json (cache wyszukiwania),
  data/processed/scenes_candidates.csv, data/processed/s2/{YYYY-MM-DD}.tif,
  data/processed/logs/01_fetch_s2.log. Skrypt jest wznawialny (pomija gotowe wiersze i pliki).
Jak to obronić: każdy próg pochodzi z config.yaml, każda odrzucona scena ma liczby w CSV,
  a ewentualny offset +1000 wykryje test na medianie SWIR16 nad wodą zamiast zgadywania poprawki.
"""
import os

os.environ.update({
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_MAX_RETRY": "5",
    "GDAL_HTTP_RETRY_DELAY": "2", "AWS_NO_SIGN_REQUEST": "YES", "GDAL_HTTP_MULTIRANGE": "YES",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "VSI_CACHE": "TRUE",
})

import argparse
import logging
import sys
import time

import numpy as np
import pandas as pd
import rasterio
import rasterio.shutil

from mielizna import osm, s2
from mielizna.config import data_path, load_config
from mielizna.grid import reference_grid

COLUMNS = ["date", "platform", "acq_id", "tiles", "items", "tile_cloud", "processing_baseline",
           "boa_offset_applied", "offset_used", "valid_pct", "local_cloud_pct", "ice_pct",
           "lake_nodata_pct", "usable"]
log = logging.getLogger("01_fetch_s2")


def check_nodata_tags(items):
    """Pierwszy i ostatni item muszą mieć w plikach tag nodata=0 (inaczej interpolacja wycieka)."""
    for it in (items[0], items[-1]):
        for b in s2.BANDS[2:] + ["blue", "scl"]:
            with rasterio.open(it.assets[b].href) as ds:
                if ds.nodata != 0:
                    raise SystemExit(f"{it.id}/{b}: nodata={ds.nodata}, oczekiwano 0 - przerywam")


def pass1(groups, cfg, grid, aoi, lake, csv_path, max_days):
    """Przebieg 1: jakość każdej akwizycji z samego SCL; wiersz CSV dopisywany od razu."""
    done = set(pd.read_csv(csv_path, dtype=str)["acq_id"]) if csv_path.exists() else set()
    todo = [k for k in sorted(groups) if f"{k[0]}_{k[1]}" not in done]
    if max_days:
        todo = todo[:max_days]
    log.info("Przebieg 1: %d akwizycji do oceny (%d już w CSV)", len(todo), len(done))
    t0, n_err = time.time(), 0
    for n, (date, platform) in enumerate(todo, 1):
        items = groups[(date, platform)]
        try:
            scls = s2.load_scl(items, grid, pool=4)
        except Exception as e:  # brak wiersza -> kolejny start ponowi próbę
            n_err += 1
            log.error("%s %s: %s: %s", date, platform, type(e).__name__, e)
            continue
        valids = [~np.isin(s, (0, 1)) for s in scls]
        tile_valid = [100 * (v & aoi).sum() / aoi.sum() for v in valids]
        order = np.argsort(tile_valid, kind="stable")[::-1]
        items = [items[i] for i in order]
        scls = [scls[i] for i in order]
        _, scl = s2.mosaic_first_valid([{}] * len(items), scls, [s > 0 for s in scls])
        q = s2.scene_quality(date, scl, ~np.isin(scl, (0, 1)), aoi, lake)
        usable = s2.is_usable(q, cfg)
        row = {
            "date": date, "platform": platform, "acq_id": f"{date}_{platform}",
            "tiles": ";".join(s2._tile(i) for i in items), "items": ";".join(i.id for i in items),
            "tile_cloud": ";".join(f"{i.properties.get('eo:cloud_cover', float('nan')):.1f}" for i in items),
            "processing_baseline": ";".join(str(i.properties.get("s2:processing_baseline")) for i in items),
            "boa_offset_applied": ";".join(str(i.properties.get("earthsearch:boa_offset_applied")) for i in items),
            "offset_used": ";".join(str(s2.reflectance_offset(i)) for i in items),
            **{k: round(q[k], 3) for k in ("valid_pct", "local_cloud_pct", "ice_pct", "lake_nodata_pct")},
            "usable": usable,
        }
        pd.DataFrame([row], columns=COLUMNS).to_csv(csv_path, mode="a", header=not csv_path.exists(),
                                                    index=False)
        log.debug("%s %s SCL%%: %s", date, platform, {k: round(v, 1) for k, v in q["scl_pct"].items()})
        if n % 25 == 0 or n == len(todo):
            el = time.time() - t0
            log.info("P1 %d/%d (%.0f s, ~%.0f s do końca)", n, len(todo), el, el / n * (len(todo) - n))
    log.info("Przebieg 1 zakończony, błędów: %d", n_err)


def write_cog(path, bands, scl):
    """7 pasm float32 (BANDS + scl; scl 0 -> NaN), nodata NaN, COG deflate."""
    grid = reference_grid()
    stack = np.stack([bands[b] for b in s2.BANDS] + [np.where(scl > 0, scl, np.nan).astype(np.float32)])
    tmp_gtiff, tmp_cog = path.with_suffix(".tmp.tif"), path.with_suffix(".cog.tmp.tif")
    with rasterio.open(tmp_gtiff, "w", driver="GTiff", width=grid.width, height=grid.height,
                       count=7, dtype="float32", crs=grid.crs, transform=grid.transform,
                       nodata=np.nan) as ds:
        ds.write(stack)
        ds.descriptions = tuple(s2.BANDS + ["scl"])
    rasterio.shutil.copy(tmp_gtiff, tmp_cog, driver="COG", compress="deflate", predictor=3)
    tmp_gtiff.unlink()
    tmp_cog.replace(path)


def pass2(by_id, cfg, grid, aoi, lake, csv_path, out_dir, rejected_path, max_days):
    """Przebieg 2: 6 pasm dla najlepszej użytecznej akwizycji każdego dnia."""
    df = pd.read_csv(csv_path, dtype={"date": str, "platform": str})
    df["usable"] = [s2.is_usable(r, cfg) for r in df.to_dict("records")]  # uwzględnia exclude_dates
    rejected = set(pd.read_csv(rejected_path, dtype=str)["date"]) if rejected_path.exists() else set()
    best = (df[df["usable"]].sort_values(["date", "valid_pct", "local_cloud_pct"],
                                         ascending=[True, False, True]).groupby("date").head(1))
    todo = [r for r in best.to_dict("records")
            if not (out_dir / f"{r['date']}.tif").exists() and r["date"] not in rejected]
    if max_days:
        todo = todo[:max_days]
    log.info("Przebieg 2: %d dni użytecznych, %d do zapisu", len(best), len(todo))
    t0 = time.time()
    for n, r in enumerate(todo, 1):
        date = r["date"]
        try:
            items = [by_id[i] for i in r["items"].split(";")]
            bands, scl = s2.load_day(items, grid, cfg, pool=6)
            q = s2.scene_quality(date, scl, s2.valid_mask(bands, scl), aoi, lake)
            if not s2.is_usable(q, cfg):
                log.warning("%s: po pełnej walidacji nieużyteczna (valid %.1f, chmury %.1f) - pomijam",
                            date, q["valid_pct"], q["local_cloud_pct"])
                pd.DataFrame([{"date": date, "valid_pct": q["valid_pct"],
                               "local_cloud_pct": q["local_cloud_pct"]}]).to_csv(
                    rejected_path, mode="a", header=not rejected_path.exists(), index=False)
                continue
            write_cog(out_dir / f"{date}.tif", bands, scl)
        except Exception as e:  # bez pliku -> kolejny start ponowi próbę
            log.error("%s: %s: %s", date, type(e).__name__, e)
            continue
        el = time.time() - t0
        log.info("P2 %d/%d %s zapisano (~%.0f s do końca)", n, len(todo), date, el / n * (len(todo) - n))
    log.info("Przebieg 2 zakończony")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="odśwież cache wyszukiwania STAC")
    ap.add_argument("--max-days", type=int, default=0, help="limit akwizycji na przebieg (test)")
    ap.add_argument("--skip-pass1", action="store_true")
    a = ap.parse_args()

    log_path = data_path("processed", "logs", "01_fetch_s2.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(log_path, encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    for noisy in ("botocore", "boto3", "odc", "rasterio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg, grid = load_config(), reference_grid()
    aoi, lake = osm.aoi_mask(grid), osm.lake_mask(grid)
    items = s2.search_items(cfg, cache=data_path("raw", "s2_items.json"), refresh=a.refresh)
    groups = s2.group_acquisitions(items)
    log.info("Itemów po deduplikacji: %d, akwizycji: %d", len(items), len(groups))
    check_nodata_tags(items)

    csv_path = data_path("processed", "scenes_candidates.csv")
    out_dir = data_path("processed", "s2")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not a.skip_pass1:
        pass1(groups, cfg, grid, aoi, lake, csv_path, a.max_days)
    pass2({i.id: i for i in items}, cfg, grid, aoi, lake, csv_path, out_dir,
          data_path("processed", "scenes_pass2_rejected.csv"), a.max_days)


if __name__ == "__main__":
    main()
