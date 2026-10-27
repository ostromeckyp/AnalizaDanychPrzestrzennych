import warnings

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
import pytest
import rasterio
from affine import Affine
from shapely.geometry import Point
from sklearn.metrics import balanced_accuracy_score, cohen_kappa_score, f1_score

from mielizna import rf
from mielizna.features import FEATURES
from mielizna.rf import (build_table, grouped_cv, load_model, make_model, mcnemar_exact,
                         permutation_importance_table, render_report, save_model, table_counts,
                         train_final, wilson_ci)
from mielizna.s2 import BANDS


@pytest.fixture
def toy_df():
    """Rozdzielne dane: woda mndwi > 0, ląd < 0; 20 scen, 10 bloków, część punktów „human"."""
    rng = np.random.default_rng(0)
    n = 400
    y = (np.arange(n) % 2).astype(int)
    df = pd.DataFrame(rng.normal(size=(n, len(FEATURES))), columns=FEATURES)
    df["mndwi"] = np.where(y == 1, 0.5, -0.5) + rng.normal(0, 0.1, n)
    df["y"] = y
    df["date"] = [f"2020-01-{(i // 20) + 1:02d}" for i in range(n)]
    df["block"] = [f"{i % 10}_0" for i in range(n)]
    flip = rng.random(n) < 0.05
    df["otsu_pred"] = np.where(flip, 1 - y, y)
    df["scl_pred"] = np.where(rng.random(n) < 0.08, 1 - y, y)
    df["source"] = np.where(rng.random(n) < 0.4, "human", "auto")
    df["stratum"] = np.where(df.source == "human", "shore", "auto_water")
    df["id"] = np.arange(n)
    df["otsu_t"] = 0.0
    return df


# --- trzy testy z briefu -------------------------------------------------------------

def test_cv_metrics_on_separable_data(toy_df):
    m = grouped_cv(toy_df, "date")
    assert m["rf"]["oa"] > 0.95 and {"oa", "kappa", "f1_water", "confusion"} <= m["otsu"].keys()


def test_no_group_leakage(toy_df):
    for tr, te in grouped_cv(toy_df, "block")["folds"]:
        assert set(toy_df.block.iloc[tr]).isdisjoint(toy_df.block.iloc[te])


def test_saved_model_carries_feature_order(tmp_path, toy_df):
    save_model(train_final(toy_df), tmp_path / "m.joblib")
    assert joblib.load(tmp_path / "m.joblib")["features"] == FEATURES


# --- decyzje Opusa --------------------------------------------------------------------

def test_stratified_folds_each_contain_human_land(toy_df):
    for group in ("date", "block"):
        res = grouped_cv(toy_df, group)
        for _, te in res["folds"]:
            t = toy_df.iloc[te]
            assert ((t.source == "human") & (t.y == 0)).any()
        # każdy wiersz trafia do testu dokładnie raz
        assert sorted(np.concatenate([te for _, te in res["folds"]])) == list(range(len(toy_df)))


def test_cv_raises_with_too_few_groups(toy_df):
    toy_df["block"] = ["a", "b", "c"] * 133 + ["a"]
    with pytest.raises(ValueError, match="grup"):
        grouped_cv(toy_df, "block")


def test_cv_raises_when_a_fold_has_no_human_land(toy_df):
    toy_df.loc[toy_df.source == "human", "y"] = 1      # w ogóle brak lądu „human"
    with pytest.raises(ValueError, match="human"):
        grouped_cv(toy_df, "date")


def test_wilson_ci_hand_computed():
    lo, hi = wilson_ci(13, 21)
    assert lo == pytest.approx(0.409, abs=1e-3) and hi == pytest.approx(0.792, abs=1e-3)
    assert np.isnan(wilson_ci(0, 0)[0])


def test_mcnemar_exact_hand_computed():
    a = np.array([1] * 8 + [0] * 2 + [1] * 5, bool)    # b = 8 (a dobrze, b źle), c = 2
    b = np.array([0] * 8 + [1] * 2 + [1] * 5, bool)
    r = mcnemar_exact(a, b)
    assert (r["b"], r["c"]) == (8, 2)
    assert r["p"] == pytest.approx(2 * (1 + 10 + 45) / 1024)
    assert mcnemar_exact(a, a)["p"] == 1.0


def test_confusion_metrics_match_sklearn():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 200)
    p = np.where(rng.random(200) < 0.8, y, 1 - y)
    m = rf.metrics_from_labels(y, p)
    assert m["bacc"] == pytest.approx(balanced_accuracy_score(y, p))
    assert m["kappa"] == pytest.approx(cohen_kappa_score(y, p))
    assert m["f1_land"] == pytest.approx(f1_score(y, p, pos_label=0))
    assert m["f1_water"] == pytest.approx(f1_score(y, p, pos_label=1))


def test_human_block_has_ci_mcnemar_and_all_water_baseline(toy_df):
    h = grouped_cv(toy_df, "block")["human"]
    for k in ("rf", "otsu", "scl", "all_water", "rf_auto"):
        assert h[k]["ci"]["oa"][0] <= h[k]["oa"] <= h[k]["ci"]["oa"][1]
    assert h["all_water"]["recall_land"] == 0.0 and h["all_water"]["bacc"] == 0.5
    assert {"vs_otsu", "vs_scl"} == set(h["mcnemar"]) and {"b", "c", "p"} <= h["mcnemar"]["vs_otsu"].keys()


def test_per_stratum_when_shore_low_present(toy_df):
    h = toy_df.source == "human"
    toy_df.loc[h & (toy_df.index % 4 == 0), "stratum"] = "shore_low"
    res = grouped_cv(toy_df, "block")
    assert {"shore", "shore_low"} <= set(res["per_stratum"]) and "human_pooled" in res


def test_permutation_importance_lists_all_features(toy_df):
    folds = grouped_cv(toy_df, "block")["folds"]
    imp = permutation_importance_table(toy_df, folds)
    assert set(imp.feature) == set(FEATURES) and {"mean", "std"} <= set(imp.columns)
    assert imp["mean"].is_monotonic_decreasing


def test_load_model_checks_features_and_warns_on_sklearn(tmp_path, toy_df):
    path = tmp_path / "m.joblib"
    save_model(train_final(toy_df), path, {"n_rows": len(toy_df)})
    bundle = load_model(path)
    assert bundle["classes"] == {"0": "land", "1": "water"} and bundle["nodata"] == 255
    assert bundle["n_rows"] == len(toy_df) and "otsu" in bundle
    b = joblib.load(path)
    b["sklearn_version"] = "0.0.1"
    joblib.dump(b, path)
    with pytest.warns(UserWarning, match="sklearn"):
        load_model(path)
    b["features"] = FEATURES[::-1]
    joblib.dump(b, path)
    with pytest.raises(ValueError, match="features"):
        load_model(path)


def test_render_report_has_tables_and_m2_line(toy_df):
    res = {"by_block": grouped_cv(toy_df, "block"), "by_scene": grouped_cv(toy_df, "date")}
    imp = permutation_importance_table(toy_df, res["by_block"]["folds"])
    md = render_report(res, imp, table_counts(toy_df))
    for s in ("Tabela A", "Tabela B", "Tabela D", "Tabela E", "M2 (OA", "McNemar", "all-water"):
        assert s in md


# --- build_table na syntetycznych scenach ---------------------------------------------

N = 40
GRID_T = Affine(10, 0, 372000, 0, -10, 292500)


def _write_scene(path, water_left=True):
    """COG: lewa połowa woda (zielone wysoko, SWIR nisko), prawa ląd; SCL 6 / 4; chmura w rogu."""
    rr, cc = np.mgrid[:N, :N]
    water = cc < N // 2 if water_left else cc >= N // 2
    g = np.where(water, 0.08, 0.10)
    nir = np.where(water, 0.02, 0.30)
    swir = np.where(water, 0.01, 0.25)
    bands = {"blue": g * 0.8, "green": g, "red": g, "nir": nir, "swir16": swir, "swir22": swir}
    scl = np.where(water, 6, 4).astype(np.float32)
    scl[30:34, 30:34] = 9
    arr = np.stack([bands[b].astype(np.float32) for b in BANDS] + [scl])
    with rasterio.open(path, "w", driver="GTiff", height=N, width=N, count=7, dtype="float32",
                       crs="EPSG:2180", transform=GRID_T) as ds:
        ds.write(arr)


def _lab(i, date, row, col, label, source="human", stratum="shore"):
    x, y = GRID_T @ (col + 0.5, row + 0.5)
    return dict(id=i, date=date, row=row, col=col, x=x, y=y, stratum=stratum, label=label,
                source=source, label_v1=None, review=False, geometry=Point(x, y))


def test_build_table_filters_rows(tmp_path):
    for d in ("2020-01-01", "2020-02-01"):
        _write_scene(tmp_path / f"{d}.tif")
    rows = [
        _lab(0, "2020-01-01", 5, 5, "water"),
        _lab(1, "2020-01-01", 5, 35, "land"),
        _lab(2, "2020-01-01", 8, 8, "skip"),                          # skip -> pominięty
        _lab(3, "2020-01-01", 9, 9, None),                            # brak etykiety -> pominięty
        _lab(4, "2020-02-01", 10, 30, "land", "auto", "auto_land"),
        _lab(5, "2020-02-01", 12, 3, "water", "auto", "auto_water"),
        _lab(6, "2020-03-01", 5, 5, "water"),                         # data spoza `dates`
        _lab(7, "2020-02-01", 31, 31, "land"),                        # piksel pod chmurą
    ]
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:2180")
    aoi = np.ones((N, N), bool)
    df = build_table(gdf, tmp_path, ["2020-01-01", "2020-02-01"], aoi)
    assert list(df.columns) == FEATURES + ["y", "date", "block", "otsu_pred", "scl_pred", "source",
                                           "stratum", "id", "otsu_t"]
    assert sorted(df.id) == [0, 1, 4, 5]
    d = df.set_index("id")
    assert d.y.to_dict() == {0: 1, 1: 0, 4: 0, 5: 1}
    assert d.otsu_pred.to_dict() == {0: 1, 1: 0, 4: 0, 5: 1}
    assert d.scl_pred.to_dict() == {0: 1, 1: 0, 4: 0, 5: 1}
    assert d.loc[0, "block"] == f"{int(d.loc[0, 'block'].split('_')[0])}_{int(d.loc[0, 'block'].split('_')[1])}"
    x0 = gdf.set_index("id").loc[0, "x"]
    assert d.loc[0, "block"].startswith(f"{int(x0 // 500)}_")
    assert df.date.map(type).eq(str).all() and not df[FEATURES].isna().any().any()
    assert df.attrs["dropped"] == {"unlabelled_or_skip": 2, "not_usable": 1, "not_ok": 1, "nan": 0}
