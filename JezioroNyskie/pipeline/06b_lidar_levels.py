"""06b - Epoki LiDAR: data nalotu, poziom wody i poprawka układu wysokości KRON86 -> EVRF2007.

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

Użycie: uv run python 06b_lidar_levels.py [--epochs-only]
"""
import argparse
import logging
import sys

import geopandas as gpd
import pandas as pd
import pyproj

from mielizna import datum, lidar
from mielizna.config import data_path

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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--epochs-only", action="store_true", help="tylko część epok (obecnie jedyna)")
    ap.parse_args()
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


if __name__ == "__main__":
    main()
