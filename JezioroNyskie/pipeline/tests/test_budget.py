"""Testy budżetu błędu pionowego: pasma, łączenie źródeł, kontekst objętości, JSON bez NaN."""
import importlib
import json

import numpy as np

from mielizna import budget


def test_band_of_edges():
    z = np.array([192.89, 192.9, 194.79, 194.8, 200.0])
    assert budget.band_of(z).tolist() == ["<192.9", "192.9-194.8", "192.9-194.8", "194.8+", "194.8+"]


def test_combine_band_skips_empty_sources():
    r = budget.combine_band({"holdout": {"n": 100, "mae": 0.4, "bias": 0.1},
                             "lidar": {"n": 0},
                             "kz": {"n": 20, "mae": 0.6, "bias": -0.2}})
    assert r["range_m"] == [0.4, 0.6]
    assert r["dominant"] == "kz"
    assert set(r["sources"]) == {"holdout", "kz"}


def test_combine_band_all_empty():
    r = budget.combine_band({"holdout": {"n": 0}, "lidar": {"n": 0}, "kz": {"n": 0}})
    assert r["range_m"] is None and r["dominant"] is None


def test_combine_band_excludes_small_n():
    r = budget.combine_band({"holdout": {"n": 100, "mae": 0.5, "bias": 0.1},
                             "kz": {"n": 1, "mae": 0.9, "bias": 0.9}})
    assert r["range_m"] == [0.5, 0.5]
    assert r["dominant"] == "holdout"
    assert r["sources"]["kz"]["excluded"] == "n<5"
    assert "excluded" not in r["sources"]["holdout"]


def test_volume_context_partial_cover():
    layers = [{"h1": 193.3, "h2": 193.8, "dv_table": 6.5, "dv_model": 6.0},
              {"h1": 193.8, "h2": 194.3, "dv_table": 6.5, "dv_model": 7.0},
              {"h1": 194.8, "h2": 195.3, "dv_table": 6.5, "dv_model": 6.5}]
    v = budget.volume_context(layers, 192.9, 194.8)
    assert v["covered"] == [193.3, 194.3]
    assert abs(v["ratio"] - 13.0 / 13.0) < 1e-12
    assert budget.volume_context(layers, -np.inf, 192.9) is None


def test_budget_json_has_no_nan():
    mod = importlib.import_module("13_error_budget")
    vert = {"n": 100, "bias": -0.1, "mae": 0.5}
    ho = {"leakage_note": "x", "n_test_scenes": 3, "holdout": {"vertical": vert},
          "by_band": {b: {"vertical": vert} for b in budget.BANDS}}
    bvn = {"datum_note": "d", "all_by_band": {b: {"n": 0} for b in budget.BANDS}}
    kz = {"budget_bands": {b: {"n": 0} for b in budget.BANDS}}
    vol = {"layers": []}
    lv = {"h_sigma_by_method": {"B": {"median": 0.15}}, "a_vs_b": {"mae": 0.4, "bias": 0.0},
          "control_2024_09_12": {"scenes": []},
          "control_r_2025": {"by_method": {"A": {"n": 0, "mae": float("nan")}, "B": {"n": 2, "mae": 0.1, "bias": -0.1}}}}
    res = mod.build(ho, bvn, kz, vol, lv)
    json.dumps(res, allow_nan=False)
    assert res["bands"]["<192.9"]["range_m"] is None


def test_user_facing_text_has_no_raw_tokens():
    import re
    mod = importlib.import_module("13_error_budget")
    st = {"n": 896730, "bias": 0.31, "mae": 0.77}
    ho = {"leakage_note": "x", "n_test_scenes": 3, "holdout": {"vertical": {"n": 1234567, "bias": -0.16, "mae": 0.9}},
          "by_band": {b: {"vertical": st} for b in budget.BANDS}}
    bvn = {"datum_note": "d", "all_by_band": {b: {"n": 7320, "mae": 1.34, "bias": 1.21} for b in budget.BANDS}}
    kz = {"budget_bands": {b: {"n": 27, "mae": 0.65, "bias": 0.3} for b in budget.BANDS}}
    vol = {"layers": [{"h1": 193.3, "h2": 194.3, "dv_table": 1.0, "dv_model": 0.986}]}
    lv = {"h_sigma_by_method": {"B": {"median": 0.15}}, "a_vs_b": {"mae": 0.4, "bias": 0.0},
          "control_r_2025": {"by_method": {"B": {"n": 2, "mae": 0.1, "bias": -0.1}}}}
    res = mod.build(ho, bvn, kz, vol, lv)
    texts = [res["lidar_note"]] + [b["note"] for b in res["bands"].values()]
    for c in res["checks"]:
        texts += [c["name"], c["compared_with"], c["result"]]
    for t in texts:
        assert "`" not in t and "<->" not in t and ">=" not in t, t
        assert not re.search(r"\d\.\d", t), t
