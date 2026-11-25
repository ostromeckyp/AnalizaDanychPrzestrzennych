import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

from mielizna import bottom

_P = Path(__file__).parents[1]


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, _P / fname)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


s12 = _load("holdout12", "12_holdout.py")
s12a = _load("holdout12a", "12a_holdout_levels.py")


def _setup(monkeypatch):
    sel = pd.DataFrame({"date": ["2019-05-01", "2019-06-01", "2020-05-01", "2020-06-01", "2021-05-01", "2021-06-01"],
                        "h_method": ["C", "A", "B", "R", "B", "B"]})
    n = len(sel)
    ev = np.zeros((n, 2, 2), "uint8")
    h, sig = np.full(n, 194.0), np.full(n, 0.1)
    is_c = (sel.h_method == "C").to_numpy()
    seen = []

    def fake_bounds(ev_t, h_t, sig_t, is_c=None, k_sigma=1.0):
        seen.append(np.asarray(is_c).copy())
        return {"n": len(h_t)}

    monkeypatch.setattr(bottom, "compute_bounds", fake_bounds)
    monkeypatch.setattr(s12, "scene_record", lambda model, *a, **k: {"n_train": model["n"]})
    return sel, ev, h, sig, is_c, seen


def _run(sel, ev, h, sig, is_c, filt):
    return s12.run_folds(sel, ev, h, sig, is_c, filt, zone=None, lake_zone=None, transform=None)


def test_no_c_filter_keeps_c_out_of_compute_bounds_and_tests_equal(monkeypatch):
    sel, ev, h, sig, is_c, seen = _setup(monkeypatch)
    all_f = _run(sel, ev, h, sig, is_c, s12.TRAIN_ALL)
    assert any(s.any() for s in seen)                    # wariant "all" przekazuje C
    seen.clear()
    no_c = _run(sel, ev, h, sig, is_c, s12a.TRAIN_FILTERS["no_c"])
    assert seen and not any(s.any() for s in seen)      # żadna scena C nie trafia do compute_bounds
    seen.clear()
    br = _run(sel, ev, h, sig, is_c, s12a.TRAIN_FILTERS["b_r_only"])
    assert [f["year"] for f in all_f] == [f["year"] for f in no_c] == [f["year"] for f in br]
    for a, b, c in zip(all_f, no_c, br):
        assert a["test"].tolist() == b["test"].tolist() == c["test"].tolist()
    # b_r_only: bez A i C -> w foldzie 2020 uczy się tylko z B/R roku 2021 (2 sceny)
    assert br[0]["n_train"] == 2 and no_c[0]["n_train"] == 3 and all_f[0]["n_train"] == 4
