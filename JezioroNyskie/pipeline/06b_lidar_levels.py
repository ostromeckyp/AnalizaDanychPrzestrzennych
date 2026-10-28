"""06b - Wariant A poziomu wody z LiDAR: epoki (data, poziom, KRON86 -> EVRF2007) i poziom każdej sceny.

Co robi: dla każdej epoki (arkusze LAZ z inventory.csv) odczytuje daty nalotu z czasu GPS, ustala
  klasę wody, liczy medianę rzędnej wody w rdzeniu jeziora (obrys - 200 m) i - dla epok w KRON86 -
  dodaje przesunięcie do EVRF2007 z siatek quasi-geoidy GUGiK (`mielizna.datum`).
Dlaczego tak: to wariant A poziomu wody (pomiar z chmury punktów w znanej dacie). Rzędne z różnych
  układów porównujemy dopiero po sprowadzeniu do EVRF2007; epoki 2022 i 2024 są już w EVRF2007
  (przesunięcie 0). Siatek nie zgadujemy: bez nich skrypt kończy się błędem z instrukcją.
  Sieć włączamy tylko tu (jednorazowe pobranie siatek), nigdy w testach.
Wejście → wyjście: data/processed/lidar/inventory.csv + data/raw/lidar/<rok>/*.laz + lake.gpkg →
  data/processed/lidar/epochs.csv (epoch, date, date_span_days, h_water, h_water_evrf, h_iqr,
  n_points, water_class, uklad_h, datum_offset).
Jak to obronić: każda epoka ma jedną datę albo zakres <= 14 dni i poziom w 192-199 m (kontrola
  w logu, ostrzeżenie zamiast cichej poprawki); klasa wody pochodzi z danych (ASPRS: 9); arkusze
  z GPS week time nie dają daty i są wypisane jako takie.

Część „sceny” (--scenes-only; domyślnie obie części):
Co robi: dla każdej sceny wybiera epokę LiDAR (woda niższa o >= 0,2 m niż szacunek h_t sceny z B/R/C,
  najbliższa w czasie), próbkuje NMT tej epoki co 5 m wzdłuż linii brzegowej sceny i bierze medianę
  rzędnych > poziom wody nalotu + 0,10 m (`mielizna.variant_a`).
Dlaczego tak: brzeg ze zdjęcia leży na rzędnej wody z dnia zdjęcia; NMT mówi, ile to m n.p.m.
  Układ: rzędne NMT z epok w KRON86 (2011, 2017) są sprowadzane do EVRF2007 jedną stałą
  `datum_offset` z epochs.csv (przesunięcie w środku jeziora; zmienność nad jeziorem ~1 cm, poniżej
  błędu NMT 0,08-0,15 m). Poziom wody nalotu = `h_water_evrf`. Wyłączone z próbkowania: bloki „valid”
  (szachownica 500 m - unikanie przecieku do walidacji dna), bufor 150 m wokół zapory (OSM, warstwa
  `dam` w lake.gpkg z 03) i piksele NMT bez danych (epoki 2017 i 2022 pokrywają tylko część pasa
  brzegowego, więc zwykle odpadają na bramce min_n / min_sectors - powód w levels_a_detail.csv).
Wejście → wyjście: epochs.csv, data/raw/nmt/<rok>/*.tif, shorelines.gpkg, bulletins.csv,
  known_levels.csv, classify_stats.csv, lake.gpkg → data/processed/levels_a.csv (format known_levels.csv,
  method=A) i levels_a_detail.csv (date, epoch, n, sectors, h_sigma, rejected_reason, h_t, h_guess).
Jak to obronić: mediana + MAD odporne na koronę zapory/pomosty/trzciny; bramki n >= 50 i >= 3 z 8
  sektorów; h_sigma < 0,3 m (M3, bramka z briefu - bez niej ok. 1/3 scen A ma rozrzut brzegu do 0,7 m); A nie jest uzgadniane z B (różnicę A - B raportuje scenes.json jako `h_diff_ab`).

Użycie: uv run python 06b_lidar_levels.py [--epochs-only | --scenes-only]
"""
import argparse
import logging
import sys

from datetime import date

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import shapely

from mielizna import blocks, datum, levels, lidar, variant_a
from mielizna.config import data_path
from mielizna.grid import reference_grid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("06b_lidar_levels")

CORE_BUFFER_M = -200
MAX_SPAN_DAYS = 14
LEVEL_RANGE = (192.0, 199.0)
HINT = ("Brak siatek GUGiK. Pobierz: projsync --file pl_gugik_geoid2011-PL-KRON86-NH --file "
        "pl_gugik_geoid2021-PL-EVRF2007-NH  (albo skopiuj z https://cdn.proj.org/ do katalogu danych PROJ)")


def kron_offset(x: float, y: float) -> float:
    """Przesunięcie KRON86 -> EVRF2007; przy braku siatek jednorazowo włącza sieć PROJ, potem kończy błędem."""
    try:
        return datum.kron86_to_evrf2007(x, y)
    except datum.GridsMissing:
        log.info("brak siatek lokalnie - włączam sieć PROJ (jednorazowe pobranie)")
        pyproj.network.set_network_enabled(True)
        datum._geoid_transformer.cache_clear()
        try:
            return datum.kron86_to_evrf2007(x, y)
        except datum.GridsMissing as e:
            sys.exit(f"{e}\n{HINT}")


def epoch_row(epoch: int, paths: list, uklad_h: str, core) -> dict:
    dates = sorted({d for p in paths for d in lidar.flight_dates(p)})
    cls = lidar.water_class(paths, core)
    h, iqr, n = lidar.water_level(paths, core, cls)
    c = core.representative_point()
    off = kron_offset(c.x, c.y) if "KRON86" in uklad_h else 0.0
    span = (dates[-1] - dates[0]).days if dates else None
    return {"epoch": epoch, "date": dates[0].isoformat() if dates else "", "date_span_days": span,
            "h_water": round(h, 3), "h_water_evrf": round(h + off, 3), "h_iqr": round(iqr, 3),
            "n_points": n, "water_class": cls, "uklad_h": uklad_h, "datum_offset": round(off, 3)}


def check(row: dict) -> list[str]:
    """Ostrzeżenia z kontroli sensowności epoki (nic nie jest poprawiane po cichu)."""
    w = []
    if row["date_span_days"] is None:
        w.append("brak daty nalotu (GPS week time)")
    elif row["date_span_days"] > MAX_SPAN_DAYS:
        w.append(f"zakres dat {row['date_span_days']} dni > {MAX_SPAN_DAYS}")
    if not LEVEL_RANGE[0] <= row["h_water"] <= LEVEL_RANGE[1]:
        w.append(f"poziom {row['h_water']} m poza {LEVEL_RANGE}")
    return w


def epochs_part():
    lake = gpd.read_file(data_path("processed", "lake.gpkg"), layer="lake").to_crs(2180).geometry.union_all()
    core = lake.buffer(CORE_BUFFER_M)
    inv = pd.read_csv(data_path("processed", "lidar", "inventory.csv"))
    inv = inv[inv["kind"] == "laz"]
    rows = []
    for year, g in inv.groupby("year"):
        row = epoch_row(int(year), list(g["path"]), g["uklad_h"].iloc[0], core)
        for msg in check(row):
            log.warning("epoka %s: %s", year, msg)
        log.info("%s", row)
        rows.append(row)
    out = data_path("processed", "lidar", "epochs.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    log.info("zapisano %s", out)


DAM_BUFFER_M = variant_a.DAM_BUFFER_M
MAX_SIGMA = 0.3  # kryterium M3: h_sigma wariantu A < 0,3 m; scena powyżej nie dostaje A (rozrzut brzegu za duży)


def scene_guesses(proc) -> tuple[gpd.GeoDataFrame, dict]:
    """h_t każdej sceny z B/R/C (bez A) = szacunek do wyboru epoki; ta sama kolejność wejść co w 06."""
    gdf = gpd.read_file(proc / "shorelines.gpkg")
    dates = [date.fromisoformat(d) for d in gdf["date"]]
    bulls = pd.read_csv(proc / "bulletins.csv", dtype={"scene_date": str})
    ov = levels.load_overrides(data_path("reference", "known_levels.csv"))
    cs = pd.read_csv(proc / "classify_stats.csv", dtype={"date": str})
    key = dict(zip(dates, gdf.index))
    lv = levels.assign_levels(dates, bulls, ov, areas=levels.curve_areas(cs, dates),
                              qc_ok={d: bool(gdf.loc[i, "qc_ok"]) for d, i in key.items()},
                              nodata_pct={d: gdf.loc[i, "lake_nodata_pct"] for d, i in key.items()})
    return gdf, dict(zip(lv.date, lv.h_t))


def scenes_part():
    proc = data_path("processed")
    epochs = pd.read_csv(proc / "lidar" / "epochs.csv", dtype={"date": str}).fillna({"date": ""})
    gdf, guess = scene_guesses(proc)
    lake = gpd.read_file(proc / "lake.gpkg", layer="lake").to_crs(2180).geometry.union_all()
    center = (lake.centroid.x, lake.centroid.y)
    dam = gpd.read_file(proc / "lake.gpkg", layer="dam").to_crs(2180)
    dam_zone = dam.geometry.union_all().buffer(DAM_BUFFER_M) if len(dam) else None
    grid = reference_grid()
    nmt_cache: dict[int, variant_a.Nmt] = {}
    rows, out = [], []
    for r in gdf.itertuples():
        d = date.fromisoformat(r.date)
        h_guess = guess.get(d, np.nan)
        row = {"date": d, "epoch": "", "n": 0, "sectors": 0, "h_sigma": np.nan, "rejected_reason": "",
               "h_t": np.nan, "h_guess": h_guess}
        rows.append(row)
        if not np.isfinite(h_guess):
            row["rejected_reason"] = "brak szacunku h_t sceny (qc_excluded)"
            continue
        ep = variant_a.choose_epoch(epochs, d, float(h_guess))
        if ep is None:
            row["rejected_reason"] = "brak epoki z woda < h_guess - 0.2 m"
            continue
        year = int(ep.epoch)
        row["epoch"] = year
        xy = variant_a.sample_shoreline(r.geometry, 5)
        n0 = len(xy)
        xy = xy[blocks.block_role(xy[:, 0], xy[:, 1], grid) == "calib"]
        if dam_zone is not None and len(xy):
            xy = xy[~shapely.contains_xy(dam_zone, xy[:, 0], xy[:, 1])]
        if year not in nmt_cache:
            nmt_cache[year] = variant_a.Nmt(sorted((data_path("raw", "nmt") / str(year)).glob("*.tif")))
        z = nmt_cache[year].sample(xy) + float(ep.datum_offset)  # KRON86 -> EVRF2007 (0 dla 2022/2024)
        cov = np.isfinite(z)
        s = variant_a.diagnose(xy[cov], z[cov], float(ep.h_water_evrf), center=center)
        row.update(n=s["n"], sectors=s["sectors"], h_sigma=s["h_sigma"], h_t=s["h_t"])
        res = variant_a.level_from_dem(xy[cov], z[cov], float(ep.h_water_evrf), max_sigma=MAX_SIGMA, center=center)
        if res is None:
            why = []
            if s["n"] < 50:
                why.append(f"n={s['n']} < 50 (próbki brzegu {n0}, calib {len(xy)}, z NMT {int(cov.sum())})")
            if s["sectors"] < 3:
                why.append(f"sektory={s['sectors']} < 3")
            if s["h_sigma"] >= MAX_SIGMA:
                why.append(f"h_sigma={s['h_sigma']:.2f} >= {MAX_SIGMA} (M3)")
            row["rejected_reason"] = "; ".join(why)
            continue
        h, sig, n = res
        out.append({"start": d.isoformat(), "end": d.isoformat(), "h": round(h, 3), "sigma": round(sig, 3),
                    "method": "A", "source": f"LiDAR {year} NMT, n={n}"})
    pd.DataFrame(out, columns=["start", "end", "h", "sigma", "method", "source"]).to_csv(proc / "levels_a.csv", index=False)
    det = pd.DataFrame(rows)
    det.to_csv(proc / "levels_a_detail.csv", index=False)
    log.info("sceny: %d, z wariantem A: %d", len(det), len(out))
    log.info("powody odrzuceń:\n%s", det[det.rejected_reason != ""].groupby(["epoch", "rejected_reason"]).size().to_string()
             if (det.rejected_reason != "").any() else "brak")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--epochs-only", action="store_true", help="tylko epoki LiDAR (epochs.csv)")
    g.add_argument("--scenes-only", action="store_true", help="tylko poziomy scen (levels_a.csv); wymaga epochs.csv")
    a = ap.parse_args()
    if not a.scenes_only:
        epochs_part()
    if not a.epochs_only:
        scenes_part()


if __name__ == "__main__":
    main()
