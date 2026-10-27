"""05 - Linie brzegowe z masek RF i obrazki kontrolne (QC).

Co robi: z masek `masks/{data}.tif` buduje linię brzegową i powierzchnię wody każdej sceny,
  zapisuje je z miarami jakości do shorelines.gpkg i rysuje 5 obrazków kontrolnych.
Dlaczego tak: linia i powierzchnia to pierwszy wynik pipeline'u (powierzchnia z pikseli, nie z
  uproszczonej linii); obrazki z konturami RF i Otsu na zdjęciu RGB pozwalają oko-w-oko ocenić brzeg.
Wejście → wyjście: data/processed/{masks/*.tif, masks_otsu/*.tif, classify_stats.csv, s2/*.tif}
  → data/processed/shorelines.gpkg (warstwa `shorelines`: date, area_km2, lake_nodata_pct,
  otsu_threshold, local_cloud_pct, core_water_frac, rf_otsu_ratio, qc_ok, qc_reason, h_t (NaN),
  h_method (None), geometry; wszystkie sceny z usable_dates, także te z qc_ok False; Task 10
  uzupełnia h_*), data/processed/qc/{data}.png dla 5 scen qc_ok: najmniejsza i największa
  powierzchnia + 3 pośrednie (kwantyle 25/50/75) oraz qc/flagged/{data}.png dla każdej sceny
  z qc_ok False. Log: data/processed/logs/05_shorelines.log. Skrypt jest idempotentny
  (cały gpkg i obrazki przeliczane z masek; to sekundy).
Jak to obronić: geometria pochodzi z `shoreline.mask_to_shoreline` (testowanej), a powierzchnia jest
  liczona z pikseli maski == 1; obrazki pokazują maskę i zdjęcie, nie tylko liczby.
"""
import logging

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio

from mielizna.config import data_path, load_config
from mielizna.grid import reference_grid
from mielizna.labels import load_scene
from mielizna.osm import aoi_mask
from mielizna.s2 import usable_dates
from mielizna.shoreline import mask_to_shoreline

log = logging.getLogger("05_shorelines")


def pick_qc_dates(stats: pd.DataFrame) -> list[str]:
    """Najmniejsza i największa powierzchnia plus trzy pośrednie (kwantyle 25/50/75 wg rangi),
    tylko ze scen z qc_ok."""
    s = stats[stats.qc_ok.astype(bool)].sort_values("area_km2").reset_index(drop=True)
    idx = [0] + [round(q * (len(s) - 1)) for q in (0.25, 0.5, 0.75)] + [len(s) - 1]
    return [s.loc[i, "date"] for i in idx]


def render_qc(date: str, row: pd.Series, grid, aoi, out_path) -> None:
    """RGB sceny z konturem maski RF (czerwony) i Otsu (cyjan), przycięte do AOI."""
    proc = data_path("processed")
    bands, _ = load_scene(date, proc / "s2")
    rgb = np.dstack([bands["red"], bands["green"], bands["blue"]])
    rgb = np.clip(np.nan_to_num(rgb) / 0.12, 0, 1) ** (1 / 1.8)
    ys, xs = np.where(aoi)
    r0, r1, c0, c1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    fig, ax = plt.subplots(figsize=(12, 9), dpi=110)
    ax.imshow(rgb[r0:r1, c0:c1], interpolation="nearest")
    for folder, color, name in (("masks", "red", "RF"), ("masks_otsu", "cyan", "Otsu")):  # Otsu na wierzchu
        with rasterio.open(proc / folder / f"{date}.tif") as ds:
            m = ds.read(1)[r0:r1, c0:c1]
        ax.contour((m == 1).astype(float), levels=[0.5], colors=color, linewidths=0.8,
                   linestyles="dashed" if folder == "masks_otsu" else "solid")
        ax.contourf(((m == 255) & aoi[r0:r1, c0:c1]).astype(float), levels=[0.5, 1.5], colors=["yellow"], alpha=0.35)
        ax.plot([], [], color=color, label=f"{name}: woda")
    ax.plot([], [], color="yellow", alpha=0.5, lw=6, label="255 (nieznane)")
    ax.legend(loc="lower left")
    ax.set_title(f"{date}  RF {row.area_km2:.2f} km2, Otsu {row.area_otsu_km2:.2f} km2, "
                 f"nodata jeziora {row.lake_nodata_pct:.1f}%, próg Otsu {row.otsu_threshold:.2f}"
                 + ("" if row.qc_ok else f"  [QC: {row.qc_reason}]"))
    ax.axis("off")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def main():
    proc = data_path("processed")
    (proc / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(proc / "logs" / "05_shorelines.log", encoding="utf-8"),
                                  logging.StreamHandler()])
    grid = reference_grid()
    stats = pd.read_csv(proc / "classify_stats.csv", dtype={"date": str, "qc_reason": str},
                        keep_default_na=False, na_values=["nan", "NaN"])
    stats["qc_reason"] = stats["qc_reason"].fillna("")
    stats = stats[stats.date.isin(usable_dates(load_config()))].reset_index(drop=True)
    rows = []
    for r in stats.itertuples():
        with rasterio.open(proc / "masks" / f"{r.date}.tif") as ds:
            geom, area = mask_to_shoreline(ds.read(1), ds.transform)
        if abs(area - r.area_km2) > 1e-9:
            raise ValueError(f"{r.date}: powierzchnia z maski {area} != statystyki 04 {r.area_km2}")
        rows.append({"date": r.date, "area_km2": area, "lake_nodata_pct": r.lake_nodata_pct,
                     "otsu_threshold": r.otsu_threshold, "local_cloud_pct": r.local_cloud_pct,
                     "core_water_frac": r.core_water_frac, "rf_otsu_ratio": r.rf_otsu_ratio,
                     "qc_ok": bool(r.qc_ok), "qc_reason": r.qc_reason,
                     "h_t": np.nan, "h_method": None, "geometry": geom})
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=grid.crs)
    out = proc / "shorelines.gpkg"
    out.unlink(missing_ok=True)
    gdf.to_file(out, layer="shorelines", driver="GPKG")
    log.info("shorelines.gpkg: %d linii, powierzchnia %.2f-%.2f km2", len(gdf), gdf.area_km2.min(),
             gdf.area_km2.max())
    aoi = aoi_mask(grid)
    todo = [(d, proc / "qc" / f"{d}.png") for d in pick_qc_dates(stats)]
    todo += [(d, proc / "qc" / "flagged" / f"{d}.png") for d in stats[~stats.qc_ok.astype(bool)].date]
    for d, p in todo:
        render_qc(d, stats[stats.date == d].iloc[0], grid, aoi, p)
        log.info("QC: %s", p)


if __name__ == "__main__":
    main()
