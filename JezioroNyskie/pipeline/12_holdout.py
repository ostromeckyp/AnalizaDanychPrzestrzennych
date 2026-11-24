"""12 - Hold-out roczny: model dna zbudowany bez roku sceny testowej vs poziom wody tej sceny.

Co robi: dla każdego roku 2020-2026 buduje model dna z scen innych lat (`bottom.compute_bounds`), przewiduje maskę wody
  dla poziomu każdej sceny testowej tego roku (h_method B/R) i porównuje ją z obserwacją (RF∧Otsu): błąd pionowy na
  pikselach brzegowych (z − h), IoU, udział pikseli niepewnych, odległość linii brzegowych. To samo robi z serwowanym modelem
  `all` (in-sample, widział te sceny). Zapisuje eval/holdout.json i docs/img/eval-holdout.png.
Dlaczego tak: linia wodna sceny testowej leży na znanym poziomie spoza modelu, więc błąd pionowy mierzymy bez LiDAR-u
  i KŻ. Hold-out jest uczciwszy niż in-sample, ale nie w pełni: RF i krzywa C nie są trenowane od nowa na foldach
  (przeciek opisany w `leakage_note`).
Wejście → wyjście: data/processed/{scenes.json, masks/, masks_otsu/, model/all/} → data/processed/eval/holdout.json,
  docs/img/eval-holdout.png. Użycie: uv run python 12_holdout.py (ok. kilka minut: 7 × compute_bounds).
Jak to obronić: sanity check holdout.mae ≥ in_sample.mae (logowany); piksele bez obu granic idą do `share_no_pred`;
  sceny bez pikseli brzegowych są liczone w `n_skipped`, a JSON powstaje z `allow_nan=False`.
"""
import json
import logging
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from mielizna import bottom, budget, holdout
from mielizna.config import data_path, load_config
from mielizna.grid import reference_grid
from mielizna.osm import aoi_mask

log = logging.getLogger("12")
IMG = Path(__file__).resolve().parents[1] / "docs" / "img"
PERIODS = {"2020-2023": (2020, 2023), "2024": (2024, 2024), "2025-2026": (2025, 2026)}
METHOD = ("Roczny hold-out: dla każdego roku 2020-2026 model dna z scen pozostałych lat; test = sceny z poziomem z "
          "pomiaru (B/R). Błąd pionowy = z − h na pikselach brzegowych sceny (4-sąsiedztwo lądu), IoU wody i odległość "
          "linii brzegowych względem obserwacji RF∧Otsu. In-sample = serwowany model `all` na tych samych scenach.")
LEAKAGE = ("RF i krzywa C (poziomy wariantu C) nie są trenowane od nowa na foldach: maski scen i poziomy treningowe "
           "pochodzą z potoku, który widział też scenę testową, więc hold-out jest optymistyczny w tym zakresie.")


def load_ev(sel, aoi):
    from importlib import import_module
    m07 = import_module("07_bottom_model")
    rf_s, ot_s = m07.load_stacks(sel.date.tolist(), aoi)
    return bottom.combine_evidence(rf_s, ot_s)


def scene_record(model, ev_i, h, zone, lake_zone, transform, shore):
    """Metryki jednej sceny dla modelu `model` (fałdy albo serwowany)."""
    ve = holdout.vertical_errors(model, shore, h)
    pred, unc = holdout.predict_water(model, h)
    valid = zone & (ev_i != 255)
    sd = holdout.shoreline_distance(pred, ev_i, transform)
    return {"n_shore": ve["n_shore"], "err": ve["err"], "in_bounds": ve["in_bounds"],
            "iou_zone": holdout.iou(pred, ev_i, zone), "iou_lake": holdout.iou(pred, ev_i, lake_zone),
            "share_uncertain": float(unc[valid].mean()) if valid.any() else float("nan"),
            "shore_dist_median": sd["median"], "shore_dist_p90": sd["p90"]}


def subset_vertical(recs, idx):
    return holdout.aggregate([recs[i] for i in idx])["vertical"]


def plot(recs_h, recs_s, bands_of_scene, path):
    names = list(budget.BANDS)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    data, pos, cols = [], [], []
    for k, b in enumerate(names):
        for j, (recs, c) in enumerate(((recs_h, "#5aa3c8"), (recs_s, "#999999"))):
            e = [recs[i]["err"] for i in range(len(recs)) if bands_of_scene[i] == b and recs[i]["n_shore"] > 0]
            data.append(np.concatenate(e) if e else np.array([np.nan]))
            pos.append(k * 3 + j)
            cols.append(c)
    bp = ax.boxplot(data, positions=pos, widths=0.8, showfliers=False, patch_artist=True)
    for patch, c in zip(bp["boxes"], cols):
        patch.set_facecolor(c)
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xticks([k * 3 + 0.5 for k in range(len(names))], [f"h sceny {b} m" for b in names])
    ax.set_ylabel("błąd pionowy z − h [m]")
    ax.set_title("Błąd rzędnej dna na linii brzegowej: hold-out (niebieski) vs w próbie (szary)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> int:
    t0 = time.time()
    cfg = load_config()
    proc = data_path("processed")
    (proc / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
                        handlers=[logging.FileHandler(proc / "logs" / "12_holdout.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    grid = reference_grid(cfg)
    aoi = aoi_mask(grid)
    scenes = json.loads((proc / "scenes.json").read_bytes())
    span = cfg["periods"]["all"]
    sel = bottom.select_scenes(scenes, span[0], span[1])
    ev = load_ev(sel, aoi)
    h, sig = sel.h_t.to_numpy(), sel.h_sigma.to_numpy()
    is_c = (sel.h_method == "C").to_numpy()
    served, _ = bottom.read_model(proc / "model" / "all")
    sb = served["flags"] != 255
    zone = sb & ((np.isfinite(served["z_min"]) & np.isfinite(served["z_max"])) | (served["n_conflict"] > 0)
                 & (served["n_conflict"] != 65535))
    folds = holdout.year_folds(sel)
    log.info("%d scen, %d foldów, strefa IoU %d px", len(sel), len(folds), int(zone.sum()))

    n = len(sel)
    rec_h, rec_s = [None] * n, [None] * n
    year_of = sel.date.astype(str).str[:4].astype(int).to_numpy()
    for f in folds:
        res = bottom.compute_bounds(ev[f.train], h[f.train], sig[f.train], is_c=is_c[f.train], k_sigma=1.0)
        log.info("fold %d: train %d, test %d (%.0f s)", f.year, len(f.train), len(f.test), time.time() - t0)
        for i in f.test:
            shore = holdout.shore_pixels(ev[i])
            rec_h[i] = scene_record(res, ev[i], float(h[i]), zone, aoi, grid.transform, shore)
            rec_s[i] = scene_record(served, ev[i], float(h[i]), zone, aoi, grid.transform, shore)
        del res
    test_idx = [i for i in range(n) if rec_h[i] is not None]
    rh, rs = [rec_h[i] for i in test_idx], [rec_s[i] for i in test_idx]
    ah, as_ = holdout.aggregate(rh), holdout.aggregate(rs)

    def block(a):
        return {k: a[k] for k in ("vertical", "iou_zone", "iou_lake", "share_uncertain", "shore_dist_m")}

    yrs = year_of[test_idx]
    by_fold = {}
    for f in folds:
        ix = [j for j, i in enumerate(test_idx) if year_of[i] == f.year]
        a = holdout.aggregate([rh[j] for j in ix])
        by_fold[str(f.year)] = {"n_scenes": len(ix), "vertical": a["vertical"], "iou_zone_median": a["iou_zone"]["median"]}
    by_period = {}
    for name, (y0, y1) in PERIODS.items():
        ix = [j for j in range(len(test_idx)) if y0 <= yrs[j] <= y1]
        by_period[name] = {"n_scenes": len(ix), "vertical": holdout.aggregate([rh[j] for j in ix])["vertical"]}
    band_lbl = budget.band_of(h[test_idx])
    by_band = {}
    for b in budget.BANDS:
        ix = [j for j in range(len(test_idx)) if band_lbl[j] == b]
        a, s = holdout.aggregate([rh[j] for j in ix]), holdout.aggregate([rs[j] for j in ix])
        by_band[b] = {"n_scenes": len(ix), "vertical": a["vertical"] if a["vertical"]["n"] else {"n": 0},
                      "in_sample_vertical": s["vertical"] if s["vertical"]["n"] else {"n": 0}}

    out = {"method": METHOD, "leakage_note": LEAKAGE, "n_folds": len(folds), "n_test_scenes": ah["n_test_scenes"],
           "n_skipped": ah["n_skipped"], "holdout": block(ah), "in_sample": block(as_), "by_fold": by_fold,
           "by_period": by_period, "by_band": by_band}
    path = proc / "eval" / "holdout.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(holdout.jsonable(out), ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    IMG.mkdir(parents=True, exist_ok=True)
    plot(rh, rs, band_lbl, IMG / "eval-holdout.png")
    hv, sv = out["holdout"]["vertical"], out["in_sample"]["vertical"]
    log.info("hold-out: n=%d MAE=%.3f bias=%+.3f | in-sample MAE=%.3f (%.0f s)", hv["n"], hv["mae"], hv["bias"], sv["mae"],
             time.time() - t0)
    if not hv["mae"] >= sv["mae"]:
        log.warning("SANITY: hold-out MAE < in-sample MAE (%.3f < %.3f): podejrzane", hv["mae"], sv["mae"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
