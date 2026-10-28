"""02 - Skorowidze GUGiK, arkusze NMT (pierścień brzegowy) i wybrane arkusze LAZ jeziora.

Co robi: dla czterech epok skaningu (config `lidar.epochs`) pobiera ze skorowidzów WFS GUGiK listy
  arkuszy NMT i chmur punktów, wybiera arkusze LiDAR nad pierścieniem brzegowym (NMT) i nad jeziorem
  (LAZ, `laz_sheets_per_epoch` na epokę), wypisuje dry-run (liczby i rozmiary z HEAD), pobiera
  pliki strumieniowo z wznawianiem, NMT zamienia na GeoTIFF EPSG:2180 z tagiem `uklad_h`.
Dlaczego tak: NMT wystarcza na brzegu (tam wariant A próbkuje, tam jest strefa odsłonięta do
  walidacji), a LAZ jest ciężki i potrzebny tylko do daty nalotu i poziomu wody (klasa 8), więc
  bierzemy kilka arkuszy rozłożonych po obrysie. Dry-run przed pobraniem chroni przed
  niespodziewanymi dziesiątkami GB; limit w config `lidar.max_download_gb`.
Wejście → wyjście: data/processed/lake.gpkg + WFS GUGiK → data/raw/nmt/<rok>/<godlo>.<ext> (+ .tif),
  data/raw/lidar/<rok>/<godlo>.laz, data/processed/lidar/{index_*.gpkg, plan.csv, inventory.csv}.
Jak to obronić: lista arkuszy jest kompletna (stronicowanie) i filtrowana geometrią oraz błędem
  wysokości (<= 0,2 m, tylko LiDAR); nic nie jest zgadywane: epoka bez arkuszy LiDAR nad jeziorem
  jest wypisana i wpada do README, a nie zastępowana innym źródłem. Skrypt jest wznawialny.

Użycie: uv run python 02_fetch_nmt.py [--dry-run] [--refresh] [--force-size]
"""
import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import geopandas as gpd
import pandas as pd
import requests

from mielizna import gugik
from mielizna.config import data_path, load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("02_fetch_nmt")


def load_index(kind: str, src: str, year: int, cfg: dict, bbox, refresh: bool):
    """Skorowidz jednej warstwy rocznej (cache w processed/lidar); None, gdy serwis nie ma warstwy."""
    lc = cfg["lidar"]
    cache = data_path("processed", "lidar", f"index_{kind}_{src}_{year}.gpkg")
    if cache.exists() and not refresh:
        return gpd.read_file(cache)
    name = f"{lc['layer_prefix'][kind]}{year}"
    try:
        idx = gugik.fetch_index(lc["wfs"][f"{kind}_{src}"], bbox, lc["page_size"], typenames=name)
    except (gugik.GugikError, requests.HTTPError) as e:
        log.info("%s @ %s: brak warstwy (%s)", name, src, str(e)[:80])
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    idx.to_file(cache, driver="GPKG")
    return idx


def build_plan(cfg: dict, refresh: bool) -> pd.DataFrame:
    lc = cfg["lidar"]
    lake = gpd.read_file(data_path("processed", "lake.gpkg"), layer="lake").to_crs(gugik.CRS).geometry.union_all()
    band = lake.boundary.buffer(lc["shore_band_m"])
    bbox = band.bounds
    rows = []
    for year in lc["epochs"]:
        for kind in ("nmt", "laz"):
            frames = [i for src in ("evrf", "kron")
                      if (i := load_index(kind, src, year, cfg, bbox, refresh)) is not None and len(i)]
            if not frames:
                log.warning("epoka %d, %s: brak arkuszy w skorowidzach", year, kind)
                continue
            idx = pd.concat(frames, ignore_index=True)
            idx = gpd.GeoDataFrame(idx, geometry="geometry", crs=gugik.CRS)
            if kind == "nmt":
                sel = gugik.select_sheets(idx, band, [year])
            else:
                sel = gugik.pick_laz_sheets(gugik.select_sheets(idx, lake, [year]), lake,
                                            lc["laz_sheets_per_epoch"])
            # ten sam arkusz w dwóch układach: wybieramy EVRF2007 (ścieżka pliku zależy tylko od roku i godła)
            sel = (sel.assign(_pref=sel.uklad_h.str.contains("EVRF2007").map({True: 0, False: 1}))
                   .sort_values("_pref", kind="stable").drop_duplicates(["godlo", "akt_rok"]))
            for r in sel.itertuples():
                rows.append({"kind": kind, "year": year, "godlo": r.godlo, "uklad_h": r.uklad_h,
                             "blad_sr_wys": r.blad_sr_wys_m if hasattr(r, "blad_sr_wys_m") else r.blad_sr_wys,
                             "format": r.format, "url": r.url_do_pobrania})
    return pd.DataFrame(rows, columns=["kind", "year", "godlo", "uklad_h", "blad_sr_wys", "format", "url"])


def add_sizes(plan: pd.DataFrame, workers: int = 6) -> pd.DataFrame:
    """Rozmiary z HEAD; serwer odpowiada ok. 40 s na zapytanie, więc równolegle (kilka wątków)."""
    def one(u):
        try:
            return gugik.remote_size(u)
        except requests.RequestException as e:
            log.warning("HEAD %s: %s", u, e)
            return None
    with ThreadPoolExecutor(workers) as ex:
        return plan.assign(est_bytes=list(ex.map(one, plan.url)))


def print_summary(plan: pd.DataFrame, epochs) -> float:
    g = plan.groupby(["year", "kind"]).agg(sheets=("godlo", "count"), gb=("est_bytes", lambda s: s.sum() / 1e9),
                                           unknown=("est_bytes", lambda s: int(s.isna().sum())))
    print("\nPLAN POBIERANIA (arkusze, szacowany rozmiar z HEAD):")
    print(g.round(3).to_string())
    for y in epochs:
        for k in ("nmt", "laz"):
            if (y, k) not in g.index:
                print(f"UWAGA: epoka {y}, {k}: brak arkuszy LiDAR nad obszarem")
    total = plan.est_bytes.sum() / 1e9
    print(f"RAZEM: {len(plan)} arkuszy, ok. {total:.2f} GB\n")
    return total


def fetch(plan: pd.DataFrame) -> pd.DataFrame:
    inv = []
    for r in plan.itertuples():
        root = data_path("raw", "nmt" if r.kind == "nmt" else "lidar", r.year)
        ext = gugik.file_ext(r.url, r.godlo) if r.kind == "nmt" else "laz"
        path, n, status = gugik.download(
            r.url, root / f"{r.godlo}.{ext}", size=None if pd.isna(r.est_bytes) else int(r.est_bytes))
        log.info("%s %s %s: %s (%.1f MB)", r.kind, r.year, r.godlo, status, n / 1e6)
        out = path
        if r.kind == "nmt":
            out = root / f"{r.godlo}.tif"
            gugik.ensure_geotiff(path, out, r.uklad_h, force=status != "skipped")
        inv.append({"kind": r.kind, "year": r.year, "godlo": r.godlo, "uklad_h": r.uklad_h,
                    "blad_sr_wys": r.blad_sr_wys, "path": str(out), "bytes": out.stat().st_size})
        time.sleep(1.0)
    return pd.DataFrame(inv)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="tylko plan i rozmiary")
    ap.add_argument("--refresh", action="store_true", help="odśwież skorowidze (ignoruj cache)")
    ap.add_argument("--force-size", action="store_true", help="pobieraj mimo przekroczenia limitu GB")
    a = ap.parse_args()
    cfg = load_config()
    plan = add_sizes(build_plan(cfg, a.refresh))
    out_dir = data_path("processed", "lidar")
    out_dir.mkdir(parents=True, exist_ok=True)
    plan.to_csv(out_dir / "plan.csv", index=False)
    total = print_summary(plan, cfg["lidar"]["epochs"])
    if a.dry_run:
        return 0
    n_unknown = int(plan.est_bytes.isna().sum())
    if n_unknown and not a.force_size:
        print(f"STOP: {n_unknown} arkuszy bez znanego rozmiaru (HEAD nie zadziałał); użyj --force-size")
        return 2
    if total > cfg["lidar"]["max_download_gb"] and not a.force_size:
        print(f"STOP: {total:.1f} GB > limit {cfg['lidar']['max_download_gb']} GB (użyj --force-size)")
        return 2
    inv = fetch(plan)
    inv.to_csv(out_dir / "inventory.csv", index=False)
    print(inv.groupby(["year", "kind"]).agg(sheets=("godlo", "count"), gb=("bytes", lambda s: s.sum() / 1e9)).round(3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
