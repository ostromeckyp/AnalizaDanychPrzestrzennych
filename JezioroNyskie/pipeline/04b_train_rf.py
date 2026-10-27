"""04b - Trening i ocena klasyfikatora wody Random Forest.

Co robi: buduje tabelę uczenia z etykiet (`rf.build_table`), ocenia RF walidacją z grupami
  (by_scene i by_block), liczy ważność cech, trenuje model końcowy i zapisuje trzy pliki:
  rf_model.joblib (bundle), rf_metrics.json i rf_report.md (tabele A–E).
Dlaczego tak: wynik główny to punkty ręczne (`human`, warstwa `shore`) w podziale po blokach 500 m,
  bo tam model musi poradzić sobie z brzegiem, a nie ze środkiem jeziora; reszta jest pomocnicza.
Wejście → wyjście: data/reference/labels.gpkg, data/processed/{s2/*.tif, scenes_candidates.csv}
  → data/processed/model/{rf_model.joblib, rf_metrics.json, rf_report.md}.
  Opcje: --labels (inny plik etykiet), --out-dir (inny katalog wyników), np. do próby na kopii.
Jak to obronić: hiperparametry zamrożone, seed 42, sceny z `s2.usable_dates` (CSV + config), a
  kryterium M2 jest raportowane (MET/NOT MET) bez strojenia na zbiorze testowym.
"""
import argparse
import json
import logging
import math
from pathlib import Path

import numpy as np

from mielizna import labels as L
from mielizna import rf
from mielizna.config import DEFAULT_CONFIG, data_path, load_config
from mielizna.grid import reference_grid
from mielizna.osm import aoi_mask
from mielizna.s2 import usable_dates

log = logging.getLogger("04b_train_rf")


def _clean(o):
    """Obiekty numpy/NaN -> typy JSON (NaN -> null)."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and math.isnan(o):
        return None
    return o


def _public(res: dict) -> dict:
    return {k: v for k, v in res.items() if k not in ("folds", "oof")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--labels", default=None, help="plik etykiet (domyślnie data/reference/labels.gpkg)")
    ap.add_argument("--out-dir", default=None, help="katalog wyników (domyślnie data/processed/model)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config()
    grid = reference_grid(cfg)
    labels_path = args.labels or data_path("reference", "labels.gpkg")
    out = Path(args.out_dir) if args.out_dir else data_path("processed", "model")
    out.mkdir(parents=True, exist_ok=True)

    lab = L.load(labels_path)
    pending = lab[lab.stratum.isin(L.HUMAN_STRATA) & lab.label.isna()]
    if len(pending):
        log.warning("%d punktów human (shore/shore_low) nie ma jeszcze etykiety; model NIE jest końcowy",
                    len(pending))
    df = rf.build_table(lab, data_path("processed", "s2"), usable_dates(cfg), aoi_mask(grid))
    counts = rf.table_counts(df)
    log.info("Tabela: %s", counts)

    res = {"by_scene": rf.grouped_cv(df, "date"), "by_block": rf.grouped_cv(df, "block")}
    imp = rf.permutation_importance_table(df, res["by_block"]["folds"])
    imp_h = rf.permutation_importance_table(df, res["by_block"]["folds"], human_only=True)
    report = rf.render_report(res, imp, counts, imp_h)

    model = rf.train_final(df)
    t_final = rf.final_threshold(df)
    log.info("water_threshold (5-fold block OOF, wszystkie wiersze) = %.2f", t_final)
    h = res["by_block"]["human"]["rf"]
    human = df[df.source == "human"]
    meta = {"grid": {"crs": grid.crs, "transform": list(grid.transform)[:6], "width": grid.width,
                     "height": grid.height},
            "labels_sha": rf.file_sha256(labels_path), "config_sha": rf.file_sha256(DEFAULT_CONFIG),
            "n_rows": int(len(df)), "n_human": int(len(human)),
            "label_counts": counts["rows_by_source_class"],
            "water_threshold": t_final,
            "cv_human_by_block": {"oa": h["oa"], "bacc": h["bacc"], "kappa": h["kappa"]}}
    rf.save_model(model, out / "rf_model.joblib", _clean(meta))

    metrics = {"by_scene": _public(res["by_scene"]), "by_block": _public(res["by_block"]),
               "importance": imp.to_dict("records"),
               "importance_human": imp_h.to_dict("records"), "counts": counts, "water_threshold": t_final, "report_md": report}
    (out / "rf_metrics.json").write_text(json.dumps(_clean(metrics), ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    (out / "rf_report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
