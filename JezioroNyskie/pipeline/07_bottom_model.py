"""07 - Model dna: przedziały zalania [z_min, z_max] z serii scen (okresy all / pre_flood / post_flood).

Co robi: dla wybranego okresu wczytuje maski RF i Otsu scen z poprawnym poziomem wody, łączy je w
  obserwacje woda/ląd (RF∧Otsu = woda), liczy dla każdego piksela przedział zalania i zapisuje rastery
  oraz model_meta.json. Potem wypisuje kontrole „verify" (niezmienniki, sprzeczności, brzeg, okresy).
Dlaczego tak: dno = linia wodna z wielu poziomów jeziora (patrz mielizna/bottom.py); okres pre_flood
  służy do porównania z mapą KŻ (do 08.2024), post_flood do wykrycia zmian dna po powodzi.
Wejście → wyjście: data/processed/{scenes.json, masks/, masks_otsu/, classify_stats.csv, lake.gpkg,
  model/rf_model.joblib} → data/processed/model/{okres}/{bottom_zmin,bottom_zmax,bottom_z,bottom_unc,
  obs_count,conflict_count,bottom_flags}.tif + model_meta.json oraz data/processed/qc/bottom_*_{okres}.png.
  Opcje: --period all|pre_flood|post_flood (powtarzalna; domyślnie wszystkie trzy).
Jak to obronić: twarde asercje (kod wyjścia 1 przy porażce): niezmiennik z_min ≤ z_min_raw < z_max_raw ≤
  z_max, monotoniczność mediany z względem odległości od brzegu, ≥ 85% rdzenia jeziora jako „zawsze woda".
  Pozostałe liczby (sprzeczności, zachodnia zatoka, wpływ U1, pre vs post) są tylko raportowane.
"""
import argparse
import hashlib
import json
import logging
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from scipy import ndimage

from mielizna import bottom, rf
from mielizna.classify import lake_core
from mielizna.config import data_path, load_config
from mielizna.grid import reference_grid
from mielizna.osm import aoi_mask, lake_mask

log = logging.getLogger("07")
W_BASIN_COL = 330            # kolumny < 330 (x < 375 300 m) = zachodnia płytka zatoka
DIST_BINS = [0, 20, 50, 100, 200, 400]
Z_BANDS = [(-np.inf, 195.0, "<195"), (195.0, 196.0, "195-196"), (196.0, np.inf, ">=196")]


def read_mask(sub: str, date: str) -> np.ndarray:
    path = data_path("processed", sub, f"{date}.tif")
    if not path.exists():
        raise FileNotFoundError(f"brak maski {path}")
    with rasterio.open(path) as ds:
        return ds.read(1)


def load_stacks(dates: list[str], aoi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Maski RF i Otsu (T,H,W), 255 poza AOI (zabezpieczenie; w plikach już tak jest)."""
    rf_s = np.stack([read_mask("masks", d) for d in dates])
    ot_s = np.stack([read_mask("masks_otsu", d) for d in dates])
    rf_s[:, ~aoi] = 255
    ot_s[:, ~aoi] = 255
    return rf_s, ot_s


def run_period(name: str, span: list[str], scenes: list[dict], aoi, k_sigma=1.0):
    """Wybiera sceny okresu, łączy maski RF i Otsu w dowody i liczy przedziały dna.

    Co robi: select_scenes → load_stacks → combine_evidence → compute_bounds (reguła C z R24 w środku).
    Dlaczego tak: jedno miejsce, gdzie okres zamienia się w wynik, wspólne dla zapisu i kontroli.
    Wejście → wyjście: nazwa i [start, koniec], lista scen, maska AOI, k_sigma → (sel, maski RF, dowody,
      is_c, wynik compute_bounds).
    Jak to obronić: otwierane są tylko maski scen wybranych przez select_scenes (kontrakt T8/T10).
    """
    sel = bottom.select_scenes(scenes, span[0], span[1])
    log.info("[%s] %s..%s: %d scen %s", name, span[0], span[1], len(sel), sel.h_method.value_counts().to_dict())
    rf_s, ot_s = load_stacks(sel.date.tolist(), aoi)
    ev = bottom.combine_evidence(rf_s, ot_s)
    is_c = (sel.h_method == "C").to_numpy()
    res = bottom.compute_bounds(ev, sel.h_t.to_numpy(), sel.h_sigma.to_numpy(), is_c=is_c, k_sigma=k_sigma)
    return sel, rf_s, ev, is_c, res


def pct(x) -> str:
    return f"{100 * x:.1f}%"


def plot_map(arr, path, title, cmap="viridis", vmin=None, vmax=None, special=None):
    fig, ax = plt.subplots(figsize=(9, 7), dpi=100)
    if special is not None:
        ax.imshow(np.where(special, 1.0, np.nan), cmap="Blues", vmin=0, vmax=2)
    im = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax)
    fig.colorbar(im, ax=ax, shrink=0.7)
    ax.set_title(title)
    ax.set_axis_off()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def verify_period(name, sel, rf_s, ev, is_c, res, version, aoi, lake, core, dist, grid, qc, check) -> None:
    """Kontrole „verify" jednego okresu: niezmienniki (ASSERT) i raport.

    Co robi: sprawdza niezmiennik z_min ≤ z_min_raw < z_max_raw ≤ z_max; dla okresu `all` także
      monotoniczność mediany z względem odległości od brzegu i ≥ 85% „zawsze woda" w rdzeniu jeziora.
      Reszta (sprzeczności, zachodnia zatoka, liczby klas, wpływ U1, reguła C/R24, h_min_obs/h_max_obs)
      jest tylko logowana.
    Dlaczego tak: twarde asercje łapią błędy metody; liczby raportowe ocenia człowiek, a dostrajanie ich
      do oczekiwań byłoby fałszowaniem wyniku.
    Wejście → wyjście: wyniki `run_period`, wersja, maski AOI/jeziora/rdzenia, odległość od brzegu [m],
      siatka, katalog QC, funkcja `check(cond, msg)` → linie logu i mapa różnic U1 (dla `all`).
    Jak to obronić: każdy ASSERT jest zapisany jako OK/FAIL, a porażka daje kod wyjścia 1.
    """
    fl = res["flags"]
    obs = res["obs_count"]
    ratio = np.where(aoi & (obs > 0), res["n_conflict"] / np.maximum(obs, 1), np.nan)
    log.info("=== verify [%s] version=%s ===", name, version)
    fin = np.isfinite(res["z_min"]) & np.isfinite(res["z_max"]) & aoi
    viol = int((~((res["z_min"][fin] <= res["z_min_raw"][fin]) & (res["z_min_raw"][fin] < res["z_max_raw"][fin])
                  & (res["z_max_raw"][fin] <= res["z_max"][fin]))).sum())
    check(viol == 0, f"[{name}] niezmiennik z_min<=z_min_raw<z_max_raw<=z_max, naruszeń {viol} z {int(fin.sum())}")
    observed = aoi & (obs > 0)
    nc = res["n_conflict"]
    lk = lake & observed
    log.info("[%s] 2. sprzeczności: n_conflict_px=%d = %s obserwowanych px AOI, %s px jeziora; >=3: %s; "
             "ratio>0.1: %s; p99 n_conflict=%d", name, int(((nc > 0) & observed).sum()),
             pct(((nc > 0) & observed).sum() / observed.sum()), pct(((nc > 0) & lk).sum() / lk.sum()),
             pct(((nc >= 3) & observed).sum() / observed.sum()),
             pct(((ratio > 0.1) & observed).sum() / observed.sum()), int(np.percentile(nc[observed], 99)))
    cols = np.arange(grid.width)[None, :] * np.ones((grid.height, 1))
    for lbl, sub in (("W (col<330)", lk & (cols < W_BASIN_COL)), ("E (reszta)", lk & (cols >= W_BASIN_COL))):
        log.info("[%s] 3. zatoka %s: n=%d conflict>0 %s, ratio>0.1 %s, zawsze woda %s", name, lbl, int(sub.sum()),
                 pct((nc[sub] > 0).mean()), pct((ratio[sub] > 0.1).mean()),
                 pct(((fl[sub] & bottom.FLAG_ALWAYS_WATER) > 0).mean()))
    cnt = dict(always_water=int((lake & ((fl & 1) > 0)).sum()), always_land=int((lake & ((fl & 2) > 0)).sum()),
               unresolved=int((lake & ((fl & 16) > 0)).sum()), unobserved=int((lake & (obs == 0)).sum()),
               interval=int((lake & np.isfinite(res["z_min"]) & np.isfinite(res["z_max"])).sum()))
    log.info("[%s] 6. jezioro (%d px): %s; h_min_obs=%.2f h_max_obs=%.2f (oczekiwane dla all: 192.90/197.92, "
             "tylko raport)", name, int(lake.sum()), cnt, sel.h_t.min(), sel.h_t.max())
    no_c = bottom.compute_bounds(ev, sel.h_t.to_numpy(), sel.h_sigma.to_numpy(), None)["z_max"]
    changed = aoi & (np.nan_to_num(res["z_max"], nan=-1) != np.nan_to_num(no_c, nan=-1))
    log.info("[%s] 7. C (R24): c_water_ignored_px=%d; px ze zmienionym z_max względem is_c=None: %d", name,
             int(((fl & bottom.FLAG_C_WATER_IGNORED) > 0).sum()), int(changed.sum()))
    if name != "all":
        return
    rf_only = bottom.compute_bounds(rf_s, sel.h_t.to_numpy(), sel.h_sigma.to_numpy(), is_c=is_c)
    both = aoi & np.isfinite(res["z_max_raw"]) & np.isfinite(rf_only["z_max_raw"])
    d = res["z_max_raw"] - rf_only["z_max_raw"]
    log.info("[all] 4. U1 vs RF-only (px z oboma z_max=%d): wyżej o >0.05 m: %s (średnio wśród podniesionych "
             "%+.3f m), niżej o >0.05 m: %s; na południu (wiersze>450) %s dodatnich", int(both.sum()),
             pct((d[both] > .05).mean()), float(d[both & (d > .05)].mean()), pct((d[both] < -.05).mean()),
             pct((np.argwhere(both & (d > .05))[:, 0] > 450).mean()))
    plot_map(np.where(both, d, np.nan), qc / "bottom_zmax_vs_rf_all.png",
             "z_max (RF∧Otsu) - z_max (tylko RF) [m]", "RdBu_r", -0.6, 0.6)
    meds = []
    for lo, hi in zip(DIST_BINS[:-1], DIST_BINS[1:]):
        s_ = lake & (dist > lo) & (dist <= hi)
        zs = res["z"][s_ & np.isfinite(res["z"])]
        meds.append(float(np.median(zs)) if zs.size else np.nan)
        log.info("[all] 5. %d-%d m od brzegu: n=%d mediana z=%.2f zawsze woda %s", lo, hi, int(s_.sum()),
                 meds[-1], pct(float(((fl[s_ & observed] & 1) > 0).mean())))
    check(all(b <= a + 0.05 for a, b in zip(meds, meds[1:])),
          f"mediana z nie rośnie z odległością: {np.round(meds, 2).tolist()}")
    aw_core = float(((fl[core & observed] & 1) > 0).mean())
    check(aw_core >= 0.85, f"zawsze woda w rdzeniu jeziora {pct(aw_core)} >= 85% (oczekiwane 92%)")


def compare_periods(pre, post, aoi) -> None:
    """Porównanie pre_flood i post_flood (spec §6a): tylko raport, bez zmiany serwowanego modelu.

    Co robi: na pikselach z przedziałem w obu modelach liczy medianę z_post − z_pre i udział |Δz| większych
      od sumy niepewności, ogółem i w pasmach z_pre.
    Dlaczego tak: to wejście do decyzji, który model serwować; post_flood nie widział niskich poziomów,
      więc porównanie nic nie mówi o głębszym dnie (ostrzeżenie w logu).
    Wejście → wyjście: pary (sel, wynik) obu okresów, maska AOI → linie logu.
    Jak to obronić: wspólny zbiór pikseli i jawne pasma; brak progów decyzyjnych.
    """
    (s0, r0), (s1, r1) = pre, post
    m = aoi & np.isfinite(r0["z_min_raw"]) & np.isfinite(r0["z_max_raw"]) & np.isfinite(r1["z_min_raw"]) & \
        np.isfinite(r1["z_max_raw"])
    dz = r1["z"] - r0["z"]
    big = np.abs(dz) > (r0["unc"] + r1["unc"])
    log.info("8. pre vs post (px z przedziałem w obu: %d): mediana dz=%+.3f m, |dz|>unc_pre+unc_post: %s",
             int(m.sum()), float(np.median(dz[m])), pct(big[m].mean()))
    for lo, hi, lbl in Z_BANDS:
        b = m & (r0["z"] >= lo) & (r0["z"] < hi)
        if b.any():
            log.info("8.   pasmo z_pre %s m: n=%d mediana dz=%+.3f, |dz|>sumy: %s", lbl, int(b.sum()),
                     float(np.median(dz[b])), pct(big[b].mean()))
    log.info("8. UWAGA: post_flood nie widział h < %.2f m (pre_flood: %.2f), porównanie nic nie mówi o głębszym dnie",
             s1.h_t.min(), s0.h_t.min())


def main(argv=None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--period", action="append", choices=sorted(cfg["periods"]),
                    help="okres (powtarzalny); domyślnie wszystkie")
    args = ap.parse_args(argv)
    periods = args.period or ["all", "pre_flood", "post_flood"]
    proc = data_path("processed")
    (proc / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(proc / "logs" / "07_bottom_model.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    grid = reference_grid(cfg)
    aoi, lake = aoi_mask(grid), lake_mask(grid)
    core = lake_core(lake)
    scenes_bytes = (proc / "scenes.json").read_bytes()
    scenes = json.loads(scenes_bytes)
    shas = set(pd.read_csv(proc / "classify_stats.csv").model_sha.dropna())
    if len(shas) != 1:
        raise ValueError(f"classify_stats.csv: oczekiwano jednego model_sha, jest {sorted(shas)}")
    sha = shas.pop()
    thr = rf.load_model(proc / "model" / "rf_model.joblib").get("water_threshold")
    dist = ndimage.distance_transform_edt(lake) * grid.transform.a   # m od brzegu, wewnątrz jeziora
    fails: list[str] = []

    def check(cond: bool, msg: str):
        log.info("ASSERT %s: %s", "OK" if cond else "FAIL", msg)
        if not cond:
            fails.append(msg)

    results = {}
    for name in periods:
        span = cfg["periods"][name]
        sel, rf_s, ev, is_c, res = run_period(name, span, scenes, aoi)
        version = bottom.model_version(scenes_bytes, sel.date.tolist())
        meta = bottom.build_meta(name, tuple(span), sel, res, aoi, version, 1.0, sha, thr)
        out = proc / "model" / name
        bottom.write_model(res, grid, out, meta, aoi)
        results[name] = (sel, res)
        qc = proc / "qc"
        fl = res["flags"]
        plot_map(np.where(aoi, res["z"], np.nan), qc / f"bottom_z_{name}.png", f"z dna [m] ({name}); jasnoniebieski = zawsze woda",
                 "viridis", 193, 196.5, special=aoi & ((fl & bottom.FLAG_ALWAYS_WATER) > 0))
        plot_map(np.where(aoi, res["unc"], np.nan), qc / f"bottom_unc_{name}.png", f"niepewność [m] ({name})",
                 "magma", 0, 1.5)
        obs = res["obs_count"]
        ratio = np.where(aoi & (obs > 0), res["n_conflict"] / np.maximum(obs, 1), np.nan)
        plot_map(ratio, qc / f"bottom_conflict_{name}.png", f"n_conflict / obs_count ({name})", "inferno", 0, 0.3)

        verify_period(name, sel, rf_s, ev, is_c, res, version, aoi, lake, core, dist, grid, qc, check)

    if "pre_flood" in results and "post_flood" in results:
        compare_periods(results["pre_flood"], results["post_flood"], aoi)
    log.info("9. kontrola QGIS (nałożenie bottom_z.tif na ortofotomapę) - ręczna, poza skryptem")
    if fails:
        log.error("NIEPOWODZENIE asercji: %s", fails)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
