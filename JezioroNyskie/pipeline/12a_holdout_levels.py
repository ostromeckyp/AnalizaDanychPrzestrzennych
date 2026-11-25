"""12a - Eksperyment: hold-out roczny modelu dna wg źródła poziomu wody scen treningowych.

Co robi: powtarza roczny hold-out z 12_holdout.py (`run_folds`) w trzech wariantach scen BUDUJĄCYCH model:
  `all` (wszystkie, jak serwowany), `no_c` (bez poziomów z krzywej C, σ≈0,49 m) i `b_r_only` (tylko B i R, bez A i C).
  Dla każdego wariantu liczy błąd pionowy na pikselach brzegowych scen testowych (ogółem i wg pasm rzędnej).
Dlaczego tak: hold-out MAE ≈ in-sample, więc błąd pochodzi z wejść, a podejrzanym jest poziom wody sceny (C to poziom
  zgadnięty z powierzchni wody). Eksperyment mierzy, czy model bez C/A ma mniejszy błąd poza próbą. Tylko mierzy:
  serwowany model, holdout.json i calibration.json pozostają bez zmian (skrypt ich nie pisze).
Wejście → wyjście: data/processed/{scenes.json, masks/, masks_otsu/} → data/processed/eval/holdout_level_sources.json.
  `n_train_scenes` = słownik rok folda → liczba scen treningowych (po filtrze). Użycie: uv run python 12a_holdout_levels.py
  (ok. 3 × czas 12_holdout.py).
Jak to obronić: sceny testowe (B/R) i foldy są identyczne we wszystkich wariantach (filtr dotyczy tylko treningu), więc
  różnica MAE wynika wyłącznie ze zbioru scen budujących; strefa IoU nie jest tu używana. Wariant `all` powinien
  odtworzyć liczby z holdout.json. Mniejsza liczba scen treningowych zawęża też pokrycie, co trzeba brać pod uwagę.
"""
import importlib
import json
import logging
import sys
import time

import numpy as np

from mielizna import bottom, budget, holdout
from mielizna.config import data_path, load_config
from mielizna.grid import reference_grid
from mielizna.osm import aoi_mask

log = logging.getLogger("12a")
h12 = importlib.import_module("12_holdout")

METHOD = ("Roczny hold-out (jak 12_holdout.py) w trzech wariantach scen budujących model dna: all (wszystkie), no_c "
          "(bez h_method C), b_r_only (tylko B i R, bez A i C). Test = sceny B/R roku folda, identyczne we wszystkich "
          "wariantach; filtr dotyczy wyłącznie treningu. Błąd pionowy z − h na pikselach brzegowych obu stron. "
          "n_train_scenes = liczba scen treningowych w każdym foldzie (rok).")


def _keep(methods):
    def f(sel, train_idx):
        m = sel["h_method"].to_numpy()[train_idx]
        return train_idx[np.isin(m, list(methods))]
    return f


def _not_c(sel, train_idx):
    return train_idx[sel["h_method"].to_numpy()[train_idx] != "C"]


TRAIN_FILTERS = {"all": h12.TRAIN_ALL, "no_c": _not_c, "b_r_only": _keep(("B", "R"))}


def summarize_variant(folds, h):
    """Zbiera rekordy testowe foldów w metryki wariantu: vertical i by_band (pasmo wg h sceny)."""
    idx = [i for f in folds for i in f["test"]]
    recs = [r for f in folds for r in f["rec_h"]]
    band = budget.band_of(h[np.asarray(idx, dtype=int)])
    by_band = {}
    for b in budget.BANDS:
        ix = [j for j in range(len(recs)) if band[j] == b]
        a = holdout.aggregate([recs[j] for j in ix])
        by_band[b] = {"n_scenes": len(ix), "vertical": a["vertical"] if a["vertical"]["n"] else {"n": 0}}
    return {"n_train_scenes": {str(f["year"]): f["n_train"] for f in folds},
            "n_test_scenes": len(recs), "vertical": holdout.aggregate(recs)["vertical"], "by_band": by_band}


def main() -> int:
    t0 = time.time()
    cfg = load_config()
    proc = data_path("processed")
    (proc / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
                        handlers=[logging.FileHandler(proc / "logs" / "12a_holdout_levels.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    grid = reference_grid(cfg)
    aoi = aoi_mask(grid)
    scenes = json.loads((proc / "scenes.json").read_bytes())
    span = cfg["periods"]["all"]
    sel = bottom.select_scenes(scenes, span[0], span[1])
    ev = h12.load_ev(sel, aoi)
    h, sig = sel.h_t.to_numpy(), sel.h_sigma.to_numpy()
    is_c = (sel.h_method == "C").to_numpy()
    served, _ = bottom.read_model(proc / "model" / "all")
    sb = served["flags"] != 255
    zone = sb & ((np.isfinite(served["z_min"]) & np.isfinite(served["z_max"])) | (served["n_conflict"] > 0)
                 & (served["n_conflict"] != 65535))
    variants = {}
    for name, filt in TRAIN_FILTERS.items():
        log.info("wariant %s", name)
        folds = h12.run_folds(sel, ev, h, sig, is_c, filt, zone=zone, lake_zone=aoi, transform=grid.transform, t0=t0)
        variants[name] = summarize_variant(folds, h)
        v = variants[name]["vertical"]
        log.info("%s: n=%d MAE=%.3f bias=%+.3f p90=%.3f in_bounds=%.3f", name, v["n"], v["mae"], v["bias"],
                 v["p90_abs"], v["share_in_bounds"])
    path = proc / "eval" / "holdout_level_sources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(holdout.jsonable({"variants": variants, "method": METHOD}), ensure_ascii=False, indent=1,
                               allow_nan=False), encoding="utf-8")
    log.info("zapisano %s (%.0f s)", path, time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
