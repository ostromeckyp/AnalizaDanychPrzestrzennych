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


def test_cv_raises_when_no_human_land_at_all(toy_df):
    toy_df.loc[toy_df.source == "human", "y"] = 1      # w ogóle brak lądu „human"
    with pytest.raises(ValueError, match="human"):
        grouped_cv(toy_df, "date")


@pytest.mark.filterwarnings("ignore:The least populated class")   # celowo 4 punkty lądu < 5 foldów
def test_cv_raises_when_exactly_one_fold_lacks_human_land(toy_df):
    # ląd „human" tylko w 4 punktach z 4 różnych bloków -> przy 5 foldach dokładnie jeden fold bez niego,
    # a reszta ma ląd: guard ma złapać fold bez lądu, choć ląd human w ogóle istnieje
    h_land = toy_df.index[(toy_df.source == "human") & (toy_df.y == 0)]
    keep = []
    for b in toy_df.loc[h_land, "block"].unique()[:4]:
        keep.append(toy_df.loc[h_land][toy_df.loc[h_land, "block"] == b].index[0])
    drop = [i for i in h_land if i not in keep]
    toy_df.loc[drop, "y"] = 1
    assert ((toy_df.source == "human") & (toy_df.y == 0)).sum() == 4
    with pytest.raises(ValueError, match="fold"):
        grouped_cv(toy_df, "block")


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
    for human_only in (False, True):
        imp = permutation_importance_table(toy_df, folds, human_only=human_only)
        assert set(imp.feature) == set(FEATURES) and {"mean", "std"} <= set(imp.columns)
        assert imp["mean"].is_monotonic_decreasing
    # mndwi niesie sygnał, więc na punktach human też jest na szczycie
    assert permutation_importance_table(toy_df, folds, human_only=True).feature[0] == "mndwi"


def test_mcnemar_by_class_splits_b_and_c():
    y = np.array([1, 1, 1, 0, 0, 0])
    a = np.array([1, 1, 0, 1, 0, 0], bool)
    b = np.array([0, 1, 1, 0, 1, 0], bool)
    r = rf.mcnemar_by_class(y, a, b)
    assert r == {"water": {"b": 1, "c": 1}, "land": {"b": 1, "c": 1}}
    tot = mcnemar_exact(a, b)
    assert tot["b"] == r["water"]["b"] + r["land"]["b"] and tot["c"] == r["water"]["c"] + r["land"]["c"]


def test_bundle_mask_description_matches_s2():
    from mielizna import s2
    assert s2.cloud_mask_description() == {"dilated": [8, 9, 10], "px": 2, "undilated": [3]}
    scl = np.full((20, 20), 4)
    scl[10, 10] = 9
    scl[2, 2] = 3
    d = s2.cloud_mask_description()
    m = s2.cloud_mask(scl)
    assert m[10 + d["px"], 10] and not m[10 + d["px"] + 1, 10] and m[2, 2] and not m[3, 2]


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
    imp_h = permutation_importance_table(toy_df, res["by_block"]["folds"], human_only=True)
    md = render_report(res, imp, table_counts(toy_df), imp_h, final_curve=np.linspace(.6, .9, 9))
    assert "Średnia krzywa BA(t) końcowa" in md and "0.50=0.600" in md
    for s in ("Tabela A", "Tabela B", "Tabela D", "Tabela E", "Tabela E2", "M2 (OA", "McNemar", "all-water",
              "wiersze lądu"):
        assert s in md
    a = md.index("Tabela A")
    rows = [l.split("|")[1].strip() for l in md[a:].splitlines()[4:10]]
    assert rows == ["all-water", "Otsu", "SCL==6", "RF", "RF t*", "RF auto-only"]
    assert "t* po foldach" in md


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
    g = gdf.set_index("id")
    for i in (0, 1, 4, 5):                      # blok z known x/y: GRID_T daje x ≈ 372 0xx, y ≈ 292 4xx
        assert d.loc[i, "block"] == f"{int(g.loc[i, 'x'] // 500)}_{int(g.loc[i, 'y'] // 500)}"
    assert d.loc[0, "block"] == "744_584"       # x = 372055 -> 744, y = 292445 -> 584
    assert df.date.map(type).eq(str).all() and not df[FEATURES].isna().any().any()
    assert df.attrs["dropped"] == {"unlabelled_or_skip": 2, "not_usable": 1, "not_ok": 1, "nan": 0}


# --- R18: zagnieżdżony jednostronny próg wody --------------------------------------------

def test_choose_threshold_known_optimum():
    # ląd human: P = .55, .62, .70 (te trzeba odrzucić progiem > .70); woda: .90, .95
    p = np.array([.55, .62, .70, .90, .95])
    y = np.array([0, 0, 0, 1, 1])
    t = rf._choose_threshold(p, y, np.ones(5, bool))
    assert t == 0.75        # pierwszy próg z siatki, przy którym BA = 1


def test_choose_threshold_tie_gives_smallest():
    p = np.array([.20, .95, .95])       # ląd i woda rozdzielone już przy 0,5
    t = rf._choose_threshold(p, np.array([0, 1, 1]), np.ones(3, bool))
    assert t == 0.5


def test_choose_threshold_is_one_sided_and_on_grid():
    assert min(rf.THRESHOLD_GRID) == 0.5 and max(rf.THRESHOLD_GRID) == 0.9 and len(rf.THRESHOLD_GRID) == 9
    p = np.array([.1, .2, .9, .9])
    assert rf._choose_threshold(p, np.array([0, 0, 1, 1]), np.ones(4, bool)) >= 0.5


def test_choose_threshold_ignores_non_human_and_no_land_gives_half():
    p = np.array([.6, .6, .9, .9])
    y = np.array([0, 0, 1, 1])
    only_water_human = np.array([False, False, True, True])
    assert rf._choose_threshold(p, y, only_water_human) == 0.5      # brak lądu human
    # wiersze nie-human nie wpływają na wybór
    assert rf._choose_threshold(p, y, np.array([True, False, True, True])) == 0.65


def test_threshold_choice_never_sees_outer_test_rows(toy_df, monkeypatch):
    seen = []
    orig = rf._oof_proba

    def spy(d, *a, **k):
        seen.append((set(d["id"]), k.get("seed")))
        return orig(d, *a, **k)

    monkeypatch.setattr(rf, "_oof_proba", spy)
    res = grouped_cv(toy_df, "block")
    k = rf.THRESHOLD_REPEATS
    assert k == 10 and len(seen) == k * len(res["folds"]) and len(res["thresholds"]) == len(res["folds"])
    for i, (tr, te) in enumerate(res["folds"]):
        chunk = seen[i * k:(i + 1) * k]
        assert [sd for _, sd in chunk] == list(range(rf.SEED, rf.SEED + k)) == list(range(42, 52))
        for ids, _ in chunk:
            assert ids == set(toy_df.id.iloc[tr])
            assert ids.isdisjoint(set(toy_df.id.iloc[te]))


def test_mean_curve_beats_single_seed_argmax(toy_df, monkeypatch):
    # seed 42 sam wskazuje 0,50; średnia z 10 powtórzeń wskazuje 0,70 (R22)
    y = toy_df["y"].to_numpy()
    hm = rf._human_mask(toy_df)

    def fake(d, n_splits=5, seed=rf.SEED):
        k = seed - rf.SEED
        p = np.where(d["y"].to_numpy() == 1, 0.95, 0.30)
        land = (d["y"].to_numpy() == 0)
        # ląd: P = 0,55 w powtórzeniu 0 (próg 0,55 wystarcza), w pozostałych 0,68 (potrzeba 0,70)
        p[land] = 0.30 if k == 0 else 0.68
        return p

    monkeypatch.setattr(rf, "_oof_proba", fake)
    sub = toy_df
    single = rf._choose_threshold(fake(sub, seed=rf.SEED), y, hm)
    assert single == 0.5
    assert rf.final_threshold(sub)[0] == 0.7
    assert rf._nested_threshold(sub, np.arange(len(sub)))[0] == 0.7


def test_choose_threshold_from_curve_tie_and_nan():
    grid = rf.THRESHOLD_GRID
    curve = np.array([.8, .9, .9 + 1e-13, .9, .5, .5, .5, .5, .5])
    assert rf._choose_threshold_from_curve(curve, grid) == grid[1]
    assert rf._choose_threshold_from_curve(np.full(len(grid), np.nan), grid) == 0.5


def test_grouped_cv_reports_rf_t(toy_df):
    res = grouped_cv(toy_df, "block")
    assert all(t in rf.THRESHOLD_GRID for t in res["thresholds"])
    assert {"oa", "bacc"} <= res["human"]["rf_t"].keys() and "rf_t" in res["oof"]


def test_final_threshold_on_grid(toy_df):
    t, curve = rf.final_threshold(toy_df)
    assert t in rf.THRESHOLD_GRID and len(curve) == len(rf.THRESHOLD_GRID)


def test_load_model_defaults_threshold_and_predict_water_uses_it(tmp_path, toy_df):
    model = train_final(toy_df)
    save_model(model, tmp_path / "m.joblib")
    b = load_model(tmp_path / "m.joblib")
    assert b["water_threshold"] == 0.5
    X = toy_df[FEATURES].to_numpy()
    assert (rf.predict_water(b, X) == (model.predict_proba(X)[:, 1] >= 0.5)).all()
    save_model(model, tmp_path / "m2.joblib", {"water_threshold": 0.9})
    b2 = load_model(tmp_path / "m2.joblib")
    assert b2["water_threshold"] == 0.9
    assert rf.predict_water(b2, X).sum() <= rf.predict_water(b, X).sum()
