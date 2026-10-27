"""04a - Kandydaci do etykiet woda/ląd (częstość wody ze wszystkich scen + losowanie punktów).

Co robi: dla każdej sceny użytecznej liczy MNDWI i próg Otsu, zlicza w ilu scenach piksel jest wodą
  (`water_freq`) i losuje punkty `shore` (do ręcznej oceny) oraz `auto_water` / `auto_land`
  (etykiety automatyczne); zapisuje data/reference/labels.gpkg.
Dlaczego tak: ręczne etykiety są drogie, więc kierujemy je tam, gdzie brzeg się zmienia (częstość
  wody 5–95%), a oczywiste piksele etykietujemy automatycznie. Sceny wybiera CSV + exclude_dates
  (`labels.usable_dates`), a nie zawartość katalogu s2/. Częstość służy tylko do losowania i nie jest
  cechą modelu, więc nie przecieka odpowiedzi.
Wejście → wyjście: data/processed/{scenes_candidates.csv, s2/*.tif, lake.gpkg} →
  data/reference/labels.gpkg (kolumny: id, date, row, col, x, y, stratum, label, source).
  Odmawia nadpisania pliku, w którym są już etykiety `human` (użyj --force).
  Runda 2 (dopisuje, nie nadpisuje): `--mark-suspect` (ręczne water o MNDWI − Otsu < −0,3 → ponowna
  ślepa ocena, stara etykieta w `label_v1`) i `--append-low` (100 punktów `shore_low`).
Jak to obronić: stały seed (42) i deterministyczne sceny = ten sam zestaw punktów przy każdym
  uruchomieniu; próg Otsu to standardowa `skimage.filters.threshold_otsu`.
"""
import argparse
import logging

import numpy as np
import pandas as pd

from mielizna import labels as L
from mielizna.config import data_path, load_config
from mielizna.features import indices
from mielizna.grid import reference_grid
from mielizna.osm import aoi_mask, lake_mask
from mielizna.otsu import otsu_mask, otsu_threshold, scene_threshold
from mielizna.s2 import cloud_mask, usable_dates, valid_mask

MIN_OBSERVATIONS = 10  # pikseli z mniejszą liczbą ważnych scen nie losujemy jako brzeg
log = logging.getLogger("04a_label_candidates")


def water_frequency(dates, aoi):
    """(water_freq, {data: maska ważna i bez chmur}, {data: próg Otsu}); NaN poza AOI/bez obserwacji."""
    shape = aoi.shape
    water = np.zeros(shape, np.int32)
    seen = np.zeros(shape, np.int32)
    ok_masks, thresholds = {}, {}
    for i, d in enumerate(dates, 1):
        bands, scl = L.load_scene(d)
        ok = valid_mask(bands, scl) & ~cloud_mask(scl)
        mndwi = indices(bands)["mndwi"]
        t = otsu_threshold(mndwi, aoi & ok)
        w = otsu_mask(mndwi, t) == 1
        water += (w & ok)
        seen += ok
        ok_masks[d], thresholds[d] = ok, t
        log.info("[%d/%d] %s otsu=%.3f", i, len(dates), d, t)
    freq = np.where((seen >= MIN_OBSERVATIONS) & aoi, water / np.maximum(seen, 1), np.nan)
    return freq.astype(np.float32), ok_masks, thresholds


def suspect_margins(gdf, aoi):
    """MNDWI − Otsu sceny w punkcie, dla ręcznych „water” (Series indeksowana jak `gdf`)."""
    rows = gdf[(gdf.source == "human") & (gdf.label == "water")]
    margin = {}
    for d, s in rows.groupby("date"):
        bands, scl = L.load_scene(d)
        t = scene_threshold(bands, scl, aoi)
        mndwi = indices(bands)["mndwi"]
        for i, r in s.iterrows():
            margin[i] = float(mndwi[r.row, r.col]) - t
    return pd.Series(margin, dtype=float)


def mark_suspect(out, cfg):
    """Zeruje i oznacza do przeglądu ręczne „water” wyglądające jak ląd (R17); nic nie gubi."""
    old = L.load(out)
    if old.review.any() or old.label_v1.notna().any():
        raise SystemExit("--mark-suspect był już wykonany (label_v1/review są ustawione)")
    margin = suspect_margins(old, aoi_mask(reference_grid(cfg)))
    new, ids = L.mark_suspect(old, margin)
    L.save(new, out)
    print(f"Podejrzanych: {len(ids)}; id: {ids}")


def append_low(out, cfg):
    """Dopisuje 100 punktów `shore_low` (częstość wody 0,05–0,30, seed 43); istniejące wiersze bez zmian."""
    old = L.load(out)
    if (old.stratum == "shore_low").any():
        raise SystemExit("warstwa shore_low już istnieje; nic nie dopisano")
    grid = reference_grid(cfg)
    aoi, lake = aoi_mask(grid), lake_mask(grid)
    dates = usable_dates(cfg)
    freq, ok_masks, _ = water_frequency(dates, aoi)
    new = L.sample_extra(old, dates, freq, lake, grid, ok_fn=ok_masks.__getitem__)
    L.save(pd.concat([old, new], ignore_index=True), out)
    log.info("Dopisano %d punktów shore_low, miesiące %s", len(new),
             new.date.str[5:7].value_counts().sort_index().to_dict())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="nadpisz plik mimo istniejących etykiet human")
    ap.add_argument("--mark-suspect", action="store_true",
                    help="ręczne water z MNDWI − Otsu < −0,3 oddaj do ponownej oceny (review)")
    ap.add_argument("--append-low", action="store_true", help="dopisz 100 punktów shore_low (seed 43)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    out = data_path("reference", "labels.gpkg")
    if args.mark_suspect:
        return mark_suspect(out, load_config())
    if args.append_low:
        return append_low(out, load_config())
    if out.exists() and not args.force:
        old = L.load(out)
        if (old.source == "human").any():
            raise SystemExit(f"{out} ma {int((old.source == 'human').sum())} etykiet human; --force nadpisze")
    cfg = load_config()
    grid = reference_grid(cfg)
    aoi, lake = aoi_mask(grid), lake_mask(grid)
    dates = usable_dates(cfg)
    log.info("Sceny użyteczne: %d", len(dates))
    freq, ok_masks, _ = water_frequency(dates, aoi)
    g = L.sample_candidates(dates, freq, lake, grid, ok_fn=ok_masks.__getitem__)
    L.save(g, out)
    log.info("Zapisano %s: %s", out, g.stratum.value_counts().to_dict())
    shore = g[g.stratum == "shore"]
    log.info("shore: scen %d, miesiące %s", shore.date.nunique(),
             shore.date.str[5:7].value_counts().sort_index().to_dict())


if __name__ == "__main__":
    main()
