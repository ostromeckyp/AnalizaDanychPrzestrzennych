"""08 - Ocena dokładności (spec §7) i wybór modelu dna dla aplikacji.

Co robi: (1) porównuje dno modelu (`all`, a gdzie to sensowne `pre_flood`/`post_flood`) z NMT każdej epoki LiDAR w blokach
  „valid" na siatce 10 m; (2) porównuje poziomy wody metod A, B, C z punktami kontrolnymi (R 2025, 12.09.2024) i A z B;
  (3) liczy zmianę dna po powodzi (pre_flood vs post_flood); (4) wybiera okres modelu dla aplikacji; (5) przepisuje metryki
  masek z rf_metrics.json; (6) rysuje cztery rysunki do docs/img/eval-*.png.
Dlaczego tak: wariant A kalibrował poziom wody tylko w blokach „calib", więc walidacja w blokach „valid" nie jest krążąca.
  NMT w KRON86 (2011, 2017) sprowadzamy do EVRF2007 poprawką z epochs.csv (raz, tutaj); poziomy modelu pochodzą głównie
  z układu RZGW (nieznany), więc zmierzony bias zawiera ewentualne przesunięcie RZGW <-> EVRF2007 - raportujemy go, nie korygujemy.
  Model `all` porównujemy z każdą epoką (epoka 2011 poprzedza serię Sentinel-2, więc mierzy też realne zmiany dna i żwirownię).
Wejście → wyjście: data/processed/{scenes.json, bulletins.csv, lidar/epochs.csv, model/{all,pre_flood,post_flood}/,
  model/rf_metrics.json}, data/raw/nmt/<rok>/*.tif → data/processed/eval/{bottom_vs_nmt,levels,bottom_change,model_choice,mask}.json
  oraz docs/img/eval-*.png. Nie nadpisuje eval/variant_d.json (to wynik 10_kz_compare.py).
Jak to obronić: patrz mielizna/evaluate.py; liczby i ich interpretacja w docs/nauka/M7-lidar-kz.md (sekcja „Ocena dokładności").
  Użycie: uv run python 08_evaluate.py
"""
import json
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio

from mielizna import bottom, evaluate, levels
from mielizna.blocks import block_role
from mielizna.config import data_path, load_config
from mielizna.grid import reference_grid

log = logging.getLogger("08")
IMG = Path(__file__).resolve().parents[1] / "docs" / "img"
R_WINDOW = ("2025-04-28", "2025-05-12")
POINT_0912 = ("2024-09-12", 194.70)
EVRF = "PL-EVRF2007-NH"
MIN_STD = 0.03            # [m] piksel 10 m, którego komórki 1 m mają mniejsze odchylenie, uznajemy za płaski (woda) i pomijamy
Z_SPLIT = 196.0           # [m] granica pasm rzędnych: poniżej model all ~ pre_flood, powyżej pierścień dodany przez all
IN_PRE = {"2011", "2017", "2022", "2024"}   # NMT 2024 z 06.09.2024 = PRZED powodzią (połowa września): pre_flood jest modelem właściwym


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=float) + "\n", encoding="utf-8")


def load_dem(epoch: int, offset: float, uklad_h: str, grid):
    """NMT epoki uśredniony do siatki 10 m (bez wody arkusza i płaskich pikseli); poprawka datum raz; kontrola `uklad_h`.

    Zwraca (dem, powierzchnie wody arkuszy {nazwa: rzędna natywna lub None})."""
    tiles, names = [], []
    for p in sorted(data_path("raw", "nmt", str(epoch)).glob("*.tif")):
        with rasterio.open(p) as ds:
            tag = ds.tags().get("uklad_h")
            if tag != uklad_h:
                raise SystemExit(f"{p.name}: uklad_h={tag!r}, epochs.csv: {uklad_h!r}")
            tiles.append((ds.read(1).astype("float32"), ds.transform, ds.nodata))
            names.append(p.stem)
    log.info("epoka %s: %d arkuszy, poprawka datum %+.3f m", epoch, len(tiles), offset)
    dem, waters = evaluate.dem_to_grid(tiles, grid, offset=offset, water_margin=evaluate.WATER_MARGIN,
                                       min_std=MIN_STD, return_info=True)
    return dem, {n: (None if not np.isfinite(w) else float(w)) for n, w in zip(names, waters)}


def eval_bottom(proc: Path, grid, models: dict, gravel: np.ndarray):
    epochs = pd.read_csv(proc / "lidar" / "epochs.csv")
    ii, jj = np.meshgrid(np.arange(grid.width), np.arange(grid.height))
    x = grid.transform.c + (ii + 0.5) * grid.transform.a
    y = grid.transform.f + (jj + 0.5) * grid.transform.e
    roles = block_role(x, y, grid)
    out = {"method": "z modelu (środek przedziału) vs NMT uśredniony do 10 m; bloki valid; NMT > h_water_evrf + 0,1 m",
           "min_cover": evaluate.MIN_COVER, "min_pixel_std": MIN_STD,
           "water_filter": "per arkusz: dominanta NMT = płaska woda; komórki <= woda + 0,1 m pomijane; piksele 10 m z std < 0,03 m pomijane; żwirownia wyłączona",
           "datum_note": "NMT w EVRF2007; model głównie w układzie RZGW (nieznany) - bias zawiera ewentualne przesunięcie RZGW<->EVRF2007",
           "by_epoch": {}}
    pooled = {"all": [], "pre_flood": [], "all_on_pre": []}   # piksele wszystkich epok (all), epok sprzed powodzi (pre_flood)
    pre_cover = gravel | ~np.isfinite(models["pre_flood"]["z"])   # wyklucza piksele bez z w pre_flood (do all_on_pre_pixels)
    errs_for_plot = {}
    dems = {}
    for e in epochs.itertuples():
        offset = float(e.datum_offset) if e.uklad_h != EVRF else 0.0
        dem, waters = load_dem(e.epoch, offset, e.uklad_h, grid)
        dems[str(e.epoch)] = dem
        row = {"h_water_evrf": float(e.h_water_evrf), "date": e.date, "uklad_h": e.uklad_h,
               "datum_offset_applied": offset, "sheet_water_native": waters, "dem_px": int(np.isfinite(dem).sum())}
        row["all"] = evaluate.bottom_vs_dem(models["all"], dem, e.h_water_evrf, roles, gravel)
        pooled["all"].append(evaluate.bottom_pairs(models["all"], dem, e.h_water_evrf, roles, gravel))
        if str(e.epoch) in IN_PRE:
            row["pre_flood"] = evaluate.bottom_vs_dem(models["pre_flood"], dem, e.h_water_evrf, roles, gravel)
            pooled["pre_flood"].append(evaluate.bottom_pairs(models["pre_flood"], dem, e.h_water_evrf, roles, gravel))
            pooled["all_on_pre"].append(evaluate.bottom_pairs(models["all"], dem, e.h_water_evrf, roles, pre_cover))
        if e.epoch == 2024:      # informacyjnie: NMT sprzed powodzi vs model po powodzi
            row["post_flood_informational"] = evaluate.bottom_vs_dem(models["post_flood"], dem, e.h_water_evrf, roles, gravel)
        out["by_epoch"][str(e.epoch)] = row
        errs_for_plot[str(e.epoch)] = evaluate.bottom_errors(models["all"], dem, e.h_water_evrf, roles, gravel)
        log.info("epoka %s all: %s", e.epoch, {k: round(v, 3) for k, v in row["all"].items()})
    # pule epok: piksele z różnych epok liczone osobno
    out["all"] = {**evaluate.pooled_bottom(pooled["all"]), "note": "model all, piksele ze wszystkich epok razem"}
    out["pre_flood"] = {**evaluate.pooled_bottom(pooled["pre_flood"]),
                        "note": "model pre_flood, piksele z epok NMT sprzed powodzi (2011, 2017, 2022, 2024) razem"}
    # Rozbicie różnicy all vs pre_flood: (1) model all na tych samych pikselach co pre_flood (efekt wartości),
    # (2) model all w pasmach rzędnych modelu (pierścień >= 196 m pokrywa tylko all - efekt populacji pikseli)
    out["all_on_pre_pixels"] = {**evaluate.pooled_bottom(pooled["all_on_pre"]),
                                "note": "model all tylko na pikselach, gdzie pre_flood ma z; epoki NMT sprzed powodzi (jak pre_flood)"}
    lt, ge = evaluate.split_pairs_by_z(pooled["all"], Z_SPLIT)
    out["all_z_lt_196"] = {**evaluate.pooled_bottom(lt), "note": f"model all, piksele z z modelu < {Z_SPLIT} m, wszystkie epoki"}
    out["all_z_ge_196"] = {**evaluate.pooled_bottom(ge), "note": f"model all, piksele z z modelu >= {Z_SPLIT} m, wszystkie epoki"}
    out["all_vs_pre_flood_models"] = {**evaluate.compare_models(models["all"], models["pre_flood"]),
                                      "note": "rastry modeli (cały akwen, bez filtra bloków/NMT): diff = z_all - z_pre_flood na pikselach "
                                              "wspólnych; z_a_only = rzędne pikseli, które ma tylko model all"}
    return out, errs_for_plot, roles, dems


def eval_levels(proc: Path, scenes: pd.DataFrame, bulletins: pd.DataFrame):
    sc = scenes.copy()
    ok = sc[sc.qc_ok]
    res = {}
    det = pd.read_csv(proc / "levels_a_detail.csv")
    ep_of = dict(zip(det.date.astype(str), det.epoch))
    ab = sc[sc.h_t_a.notna() & sc.h_t_b.notna()]
    res["a_vs_b"] = {**evaluate.metrics(ab.h_t_a.to_numpy(float), ab.h_t_b.to_numpy(float)), "n_scenes": len(ab),
                     "by_lidar_epoch": {str(y): evaluate.metrics(g.h_t_a.to_numpy(float), g.h_t_b.to_numpy(float))
                                        for y, g in ab.assign(epoch=ab.date.map(ep_of).astype(int)).groupby("epoch")},
                     "note": "bias = A - B; różnica to mieszanka układu (A: EVRF2007, B: RZGW nieznany) i błędu metod; niekorygowane"}
    # krzywa C refitowana bez scen R (inaczej C 'widzi' punkt kontrolny w dopasowaniu)
    fit = ok[ok.h_method.isin(["B"]) & (ok.lake_nodata_pct <= 1.0)]
    curve = levels.fit_area_level(fit.area_otsu_km2.to_numpy(float), fit.h_t.to_numpy(float),
                                  groups=pd.to_datetime(fit.date).dt.year.to_numpy())
    bmap = levels.variant_b(bulletins).set_index("scene_date").h_t
    bmap.index = [str(d) for d in bmap.index]

    def c_level(r):
        return float(curve(r.area_otsu_km2)[0])

    def methods_for(r):
        return {"A": None if pd.isna(r.h_t_a) else float(r.h_t_a),
                "B": float(bmap[r.date]) if r.date in bmap.index else None, "C": c_level(r)}

    # R 2025
    r_rows = []
    for r in sc[(sc.h_method == "R") & (sc.date >= R_WINDOW[0]) & (sc.date <= R_WINDOW[1])].itertuples():
        m = methods_for(r)
        r_rows.append({"date": r.date, "ref": float(r.h_t), **{k: v for k, v in m.items()},
                       **{f"d{k}": (None if v is None else v - float(r.h_t)) for k, v in m.items()}})
    res["control_r_2025"] = {"ref_source": "known_levels.csv (R, RZGW piętrzenie 2025)", "scenes": r_rows,
                             "C_curve": f"krzywa powierzchnia-rzędna refitowana na scenach B (bez R), RMSE LOYO {curve.rmse_loyo:.2f} m",
                             "by_method": {k: evaluate.metrics(np.array([x[k] for x in r_rows if x[k] is not None], float),
                                                               np.array([x["ref"] for x in r_rows if x[k] is not None], float))
                                           for k in "ABC"}}
    # 12.09.2024: brak sceny tego dnia; porównanie ze scenami 03.09-12.09 (przed falą powodziową)
    pts = []
    for r in sc[(sc.date >= "2024-09-01") & (sc.date <= POINT_0912[0])].itertuples():
        m = methods_for(r)
        pts.append({"date": r.date, **m, **{f"d{k}": (None if v is None else v - POINT_0912[1]) for k, v in m.items()}})
    res["control_2024_09_12"] = {"ref": POINT_0912[1], "scenes": pts,
                                 "note": "brak sceny S-2 12.09.2024; porównanie ze scenami 1-12.09.2024 (poziom ~stały przed falą powodziową); "
                                         "A z epoki LiDAR 2024 (EVRF2007), B/C w układzie RZGW"}
    res["h_sigma_by_method"] = {m: evaluate.describe(ok[ok.h_method == m].h_sigma.to_numpy(float)) for m in ["A", "B", "C", "R"]}
    res["n_scenes_by_method"] = ok.h_method.value_counts().to_dict()
    return res, curve


def plot_bottom_hist(errs: dict, path: Path):
    fig, ax = plt.subplots(figsize=(8, 4.8), dpi=130)
    bins = np.arange(-3, 3.01, 0.1)
    for (ep, e), c in zip(errs.items(), ["#6b7280", "#d97706", "#2563eb", "#059669"]):
        if e.size:
            ax.hist(np.clip(e, -3, 3), bins=bins, histtype="step", lw=1.6, color=c, density=True,
                    label=f"NMT {ep} (n={e.size}, bias {e.mean():+.2f} m)")
    ax.axvline(0, c="k", lw=0.8)
    ax.set_xlabel("błąd dna: model − NMT [m] (obcięte do ±3 m)")
    ax.set_ylabel("gęstość")
    ax.set_title("Dno z satelity vs NMT, bloki walidacyjne")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_level_area(scenes: pd.DataFrame, curve, path: Path):
    ok = scenes[scenes.qc_ok]
    fig, ax = plt.subplots(figsize=(8, 5.2), dpi=130)
    style = {"B": ("#2563eb", "o", "B (komunikaty RZGW)"), "R": ("#dc2626", "D", "R (kontrola 2025)"),
             "C": ("#9ca3af", "x", "C (z powierzchni)")}
    for m, (c, mk, lab) in style.items():
        g = ok[ok.h_method == m]
        ax.scatter(g.area_otsu_km2, g.h_t, s=14 if m != "R" else 40, c=c, marker=mk, label=f"{lab} ({len(g)})", zorder=3 if m == "R" else 2)
    a = ok[ok.h_t_a.notna()]
    ax.scatter(a.area_otsu_km2, a.h_t_a, s=22, facecolors="none", edgecolors="#059669", label=f"A (LiDAR, {len(a)} scen, także gdy wygrywa B)", zorder=4)
    xs = np.linspace(curve.area_min, curve.area_max, 200)
    ax.plot(xs, [curve(v)[0] for v in xs], c="k", lw=1, label="krzywa (dopasowana do B)")
    ax.set_xlabel("powierzchnia jeziora (Otsu) [km²]")
    ax.set_ylabel("poziom wody [m n.p.m.]")
    ax.set_title("Poziom wody a powierzchnia, metody A / B / C / R")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_map(arr, title, label, path, cmap, vmin=None, vmax=None, grid=None):
    xmin, ymin, xmax, ymax = grid.bounds()
    fig, ax = plt.subplots(figsize=(8, 6.2), dpi=130)
    im = ax.imshow(arr, extent=(xmin, xmax, ymin, ymax), cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    cb = fig.colorbar(im, ax=ax, shrink=0.8)
    cb.set_label(label)
    ax.set_title(title)
    ax.set_xlabel("E (EPSG:2180) [m]")
    ax.set_ylabel("N (EPSG:2180) [m]")
    ax.ticklabel_format(style="plain", useOffset=False)
    ax.tick_params(axis="x", labelrotation=30, labelsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    proc = data_path("processed")
    out = proc / "eval"
    out.mkdir(exist_ok=True)
    IMG.mkdir(parents=True, exist_ok=True)
    grid = reference_grid()
    models = {p: bottom.read_model(proc / "model" / p)[0] for p in ("all", "pre_flood", "post_flood")}

    import geopandas as gpd
    from rasterio.features import rasterize
    gpoly = gpd.read_file(data_path("reference", "zwirownia.gpkg")).to_crs(grid.crs).geometry.union_all()
    gravel = rasterize([(gpoly, 1)], out_shape=(grid.height, grid.width), transform=grid.transform, fill=0,
                       dtype="uint8").astype(bool)
    res, errs, roles, dems = eval_bottom(proc, grid, models, gravel)
    _dump(out / "bottom_vs_nmt.json", res)

    scenes = pd.DataFrame(json.loads((proc / "scenes.json").read_text(encoding="utf-8")))
    bulletins = pd.read_csv(proc / "bulletins.csv")
    lv, curve = eval_levels(proc, scenes, bulletins)
    _dump(out / "levels.json", lv)

    both = np.isfinite(models["pre_flood"]["z"]) & np.isfinite(models["post_flood"]["z"])
    obs_both = (models["pre_flood"]["obs_count"] > 0) & (models["post_flood"]["obs_count"] > 0) \
        & (models["pre_flood"]["flags"] != 255) & (models["post_flood"]["flags"] != 255)
    ch = evaluate.bottom_change(models["pre_flood"], models["post_flood"], common=obs_both)
    ch["n_common_observed"] = int(obs_both.sum())
    ch["share_of_common_observed"] = float(both.sum() / max(obs_both.sum(), 1))
    ch["note"] = ("share_significant = piksele z |Δz| > unc_pre + unc_post / akwen wspólny (obserwowany w obu okresach, wg ograniczenia "
                  "projektu); share_significant_overlap = ten sam licznik / piksele z z w obu modelach; Δz = post - pre")
    _dump(out / "bottom_change.json", ch)
    choice = evaluate.choose_model(ch["share_significant"])
    _dump(out / "model_choice.json", choice)

    rfm = json.loads((proc / "model" / "rf_metrics.json").read_text(encoding="utf-8"))
    keep = ("oa", "kappa", "f1_water", "bacc", "n")
    _dump(out / "mask.json", {"water_threshold": rfm.get("water_threshold"),
                              "note": "metryki masek na etykietach ręcznych (rf_metrics.json); rf_t = RF z progiem wody; scl = maska SCL Sentinel-2",
                              **{grp: {m: {k: rfm[grp][m][k] for k in keep} for m in ("rf", "rf_t", "otsu", "scl")}
                                 for grp in ("by_scene", "by_block")}})

    plot_bottom_hist(errs, IMG / "eval-dno-vs-nmt-histogram.png")
    plot_level_area(scenes, curve, IMG / "eval-poziom-powierzchnia.png")
    unc = np.where(np.isfinite(models["all"]["z"]), models["all"]["unc"], np.nan)
    plot_map(unc, "Niepewność dna (model all, tam gdzie jest z)", "niepewność [m]", IMG / "eval-niepewnosc-mapa.png",
             "viridis", 0, 1.5, grid)
    dz = np.where(both, models["post_flood"]["z"] - models["pre_flood"]["z"], np.nan)
    plot_map(dz, "Zmiana dna po powodzi (post_flood − pre_flood)", "Δz [m]", IMG / "eval-zmiana-dna-mapa.png",
             "RdBu_r", -1, 1, grid)
    log.info("model_choice: %s", choice)
    return 0


if __name__ == "__main__":
    sys.exit(main())
