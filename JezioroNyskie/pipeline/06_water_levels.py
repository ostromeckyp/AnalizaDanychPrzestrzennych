"""06 - Rzędna wody dla każdej sceny (warianty R, B, C) i scenes.json.

Co robi: łączy powierzchnie scen z shorelines.gpkg z komunikatami RZGW (bulletins.csv) i znanymi
  rzędnymi (known_levels.csv), dopasowuje krzywą powierzchnia -> rzędna i zapisuje h_t dla
  wszystkich scen (scenes.json, uzupełnione h_t/h_method w shorelines.gpkg, wykres kontrolny).
Dlaczego tak: poziom wody jest osią całej analizy (mielizny = f(poziom)); sceny bez komunikatu
  (2017-2019 i luki) dostają poziom z krzywej, a sceny odrzucone przez QC tylko z komunikatu.
Wejście → wyjście: data/processed/{shorelines.gpkg, bulletins.csv, scenes_candidates.csv},
  data/reference/known_levels.csv → {out-dir}/scenes.json, {out-dir}/model/area_level_curve.json,
  {out-dir}/qc/area_vs_level.png, shorelines.gpkg (kolumny h_t, h_method; reszta bez zmian).
  Opcje: --shorelines (domyślnie processed/shorelines.gpkg, ZAPISYWANY w miejscu) i --out-dir
  (domyślnie processed) pozwalają na próbny przebieg na kopii. Skrypt jest idempotentny.
Jak to obronić: patrz mielizna/levels.py; tu wypisujemy liczby scen na metodę, zakres h_t,
  resztę scen B względem krzywej osobno dla dwóch reżimów v_npp oraz kontrolę M3 (wrzesień 2024).
"""
import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mielizna import levels
from mielizna.config import data_path

log = logging.getLogger("06")


def build_scene_table(gdf: gpd.GeoDataFrame, cand: pd.DataFrame, lv: pd.DataFrame) -> pd.DataFrame:
    """Dokleja do wyniku `assign_levels` pola sceny (powierzchnia, QC, kafelki)."""
    tiles = cand.sort_values("usable", ascending=False).drop_duplicates("date").set_index("date").tiles
    meta = gdf.drop(columns=["geometry", "h_t", "h_method"], errors="ignore").copy()
    meta["date"] = pd.to_datetime(meta["date"]).dt.date
    out = lv.merge(meta, on="date", how="left")
    out["tiles"] = [tiles.get(d.isoformat(), "") for d in out.date]
    return out


def plot_curve(df: pd.DataFrame, curve: levels.AreaLevelCurve, otsu: dict, path: Path) -> None:
    """Wykres kontrolny (oś x: powierzchnia Otsu): B/R kropki, C krzyżyki, krzywa."""
    fig, ax = plt.subplots(figsize=(9, 6), dpi=110)
    df = df.assign(area_otsu=[otsu[d] for d in df.date])
    br = df[df.h_method.isin(["B", "R"])]
    c = df[df.h_method == "C"]
    ax.scatter(br.area_otsu, br.h_t, s=14, c="tab:blue", label=f"B/R ({len(br)})")
    ax.scatter(c.area_otsu, c.h_t, s=26, marker="x", c="tab:red", label=f"C ({len(c)})")
    xs = np.linspace(min(df.area_otsu.min(), curve.area_min), max(df.area_otsu.max(), curve.area_max), 200)
    ax.plot(xs, [curve(a)[0] for a in xs], c="k", lw=1, label=f"krzywa (RMSE LOO {curve.rmse:.2f} m, LOYO {curve.rmse_loyo:.2f} m)")
    ax.axvspan(curve.area_min, curve.area_max, color="grey", alpha=0.08, label="zakres dopasowania")
    ax.set_xlabel("powierzchnia Otsu [km2]")
    ax.set_ylabel("rzędna [m n.p.m.]")
    ax.legend()
    ax.grid(alpha=0.3)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def main(argv=None) -> int:
    proc = data_path("processed")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shorelines", type=Path, default=proc / "shorelines.gpkg")
    ap.add_argument("--out-dir", type=Path, default=proc)
    args = ap.parse_args(argv)
    out_dir = args.out_dir
    (out_dir / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(out_dir / "logs" / "06_water_levels.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    gdf = gpd.read_file(args.shorelines)
    dates = [date.fromisoformat(d) for d in gdf["date"]]
    bulls = pd.read_csv(proc / "bulletins.csv", dtype={"scene_date": str})
    overrides = levels.load_overrides(data_path("reference", "known_levels.csv"))
    cand = pd.read_csv(proc / "scenes_candidates.csv", dtype={"date": str})
    key = dict(zip(dates, gdf.index))
    cs = pd.read_csv(proc / "classify_stats.csv", dtype={"date": str})
    otsu = levels.curve_areas(cs, dates)
    lv = levels.assign_levels(
        dates, bulls, overrides, areas=otsu,
        qc_ok={d: bool(gdf.loc[i, "qc_ok"]) for d, i in key.items()},
        nodata_pct={d: gdf.loc[i, "lake_nodata_pct"] for d, i in key.items()})
    curve = lv.attrs["curve"]
    df = build_scene_table(gdf, cand, lv)
    df["area_otsu_km2"] = [otsu[d] for d in df.date]

    # gpkg: tylko h_t i h_method (kolumny QC bez zmian)
    gdf["h_t"] = [float(df.set_index("date").h_t[d]) for d in dates]
    gdf["h_method"] = [df.set_index("date").h_method[d] for d in dates]
    gdf.to_file(args.shorelines, layer="shorelines", driver="GPKG")
    levels.write_scenes_json(df, out_dir / "scenes.json")
    levels.save_area_level_curve(curve, out_dir / "model" / "area_level_curve.json")
    plot_curve(df[df.qc_ok], curve, otsu, out_dir / "qc" / "area_vs_level.png")

    log.info("sceny na metodę: %s", df.h_method.value_counts().to_dict())
    log.info("h_t: %.2f .. %.2f m", df.h_t.min(), df.h_t.max())
    log.info("krzywa: n_obs=%d n_points=%d zakres %.2f-%.2f km2 (Otsu) rmse_loo=%.3f m rmse_loyo=%.3f m",
             curve.n_obs, len(curve.area_km2), curve.area_min, curve.area_max, curve.rmse, curve.rmse_loyo)
    c = df[df.h_method == "C"]
    log.info("C: %d scen, ekstrapolowanych %d, area_biased %d; sprzed 2019-11-04: %d (ekstrap. %d)", len(c),
             int(c.extrapolated.sum()), int(c.area_biased.sum()), int((c.date < date(2019, 11, 4)).sum()),
             int(c[c.date < date(2019, 11, 4)].extrapolated.sum()))
    hi = c[c.rf_otsu_ratio > df[df.h_method.isin(["B", "R"]) & df.qc_ok].rf_otsu_ratio.max()]
    log.info("C o rf_otsu_ratio ponad maksimum zbioru dopasowania: %d %s", len(hi),
             [(str(d), round(float(x), 3)) for d, x in zip(hi.date, hi.rf_otsu_ratio)])
    log.info("qc_excluded: %d", int((df.h_method == "qc_excluded").sum()))
    fit = df[(df.h_method == "B") & df.qc_ok & (df.lake_nodata_pct <= 1)].copy()
    fit["regime"] = np.where(fit.capacity_curve_note.str.contains("66.3"), "v_npp=66.3", "v_npp<=65.7")
    summer20 = (fit.date >= date(2020, 7, 1)) & (fit.date <= date(2020, 9, 30))
    for name, areas_ in (("Otsu", otsu), ("RF", dict(zip(dates, gdf.area_km2)))):
        fit["resid"] = fit.h_t - [curve(areas_[d])[0] for d in fit.date]
        for reg, g in fit.groupby("regime"):
            log.info("reszta B - krzywa [%s, powierzchnia %s]: n=%d mediana %+.3f m, średnia %+.3f m", reg, name,
                     len(g), g.resid.median(), g.resid.mean())
            g2 = g[~summer20[g.index]]
            log.info("  bez lipca-września 2020 [%s, %s]: n=%d mediana %+.3f m", reg, name, len(g2), g2.resid.median())
    c18 = c[(c.date >= date(2018, 9, 1)) & (c.date <= date(2018, 12, 31))]
    for r in c18.itertuples():
        log.info("C jesień 2018 %s: h_t=%.2f sigma=%.2f", r.date, r.h_t, r.h_sigma)
    m3 = df[(df.date >= date(2024, 9, 5)) & (df.date <= date(2024, 9, 12))]
    for r in m3.itertuples():
        log.info("M3 %s: h_t=%.2f metoda=%s (cel 194.70+-0.3)", r.date, r.h_t, r.h_method)
    if m3.empty:
        log.info("M3: brak scen 2024-09-05..12")
    return 0


if __name__ == "__main__":
    sys.exit(main())
