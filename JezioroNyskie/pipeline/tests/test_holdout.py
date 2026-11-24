import numpy as np
import pandas as pd
import pytest
from affine import Affine

from mielizna import budget, holdout


def _model(z, zmin, zmax, flags=None):
    z, zmin, zmax = (np.array(a, dtype="float32") for a in (z, zmin, zmax))
    return {"z": z, "z_min": zmin, "z_max": zmax,
            "flags": np.zeros(z.shape, "uint8") if flags is None else np.array(flags, "uint8")}


def test_year_folds_split():
    sel = pd.DataFrame({"date": ["2019-05-01", "2020-05-01", "2020-06-01", "2021-05-01"],
                        "h_method": ["C", "B", "A", "R"]})
    folds = holdout.year_folds(sel)
    assert [f.year for f in folds] == [2020, 2021]
    f = folds[0]
    assert f.test.tolist() == [1]
    assert f.train.tolist() == [0, 3]  # scena A z 2020 nie jest ani w test, ani w train


def test_shore_pixels_4_neighbours():
    ev = np.array([[1, 1, 0], [1, 1, 255]], "uint8")
    assert holdout.shore_pixels(ev).tolist() == [[False, True, False], [False, False, False]]


def test_predict_water_rules():
    nan = np.nan
    m = _model([193.5, 194.5, nan, nan, nan], [193.0, 194.0, nan, 196.0, nan], [194.0, 195.0, 193.05, nan, nan])
    pred, unc = holdout.predict_water(m, 193.8)
    assert pred.tolist() == [1, 0, 1, 0, 255]
    assert unc.tolist() == [True, False, False, False, False]
    pred, _ = holdout.predict_water(_model([np.nan], [np.nan], [193.05]), 192.95)
    assert pred.tolist() == [1]
    pred, _ = holdout.predict_water(_model([np.nan], [196.0], [np.nan]), 195.0)
    assert pred.tolist() == [0]


def test_vertical_errors_counts_unpredicted():
    m = _model([194.0, 193.0, np.nan], [193.5, 192.5, np.nan], [194.5, 193.5, 195.0])
    shore = np.array([True, True, True])
    out = holdout.vertical_errors(m, shore, 193.8)
    assert out["n_shore"] == 3 and out["n_pred"] == 2
    assert out["err"].tolist() == pytest.approx([0.2, -0.8])
    assert out["in_bounds"].tolist() == [True, False]
    s = holdout.summarize(out["err"], out["in_bounds"], out["n_shore"])
    assert s["share_no_pred"] == pytest.approx(1 / 3)
    assert s["n"] == 2 and s["share_in_bounds"] == pytest.approx(0.5)
    assert s["bias"] == pytest.approx(-0.3)


def test_summarize_no_predictions_has_nan_not_error():
    s = holdout.summarize(np.array([]), np.array([], bool), 4)
    assert s["n"] == 0 and s["share_no_pred"] == 1.0 and np.isnan(s["bias"])


def test_iou_empty_zone_is_nan():
    a = np.array([[1, 0]], "uint8")
    assert np.isnan(holdout.iou(a, a, np.array([[False, False]])))
    assert np.isnan(holdout.iou(a, a, np.array([[False, True]])))  # tylko piksel 0 w strefie, brak wody w obu


def test_iou_ignores_255():
    pred = np.array([[1, 1, 255, 0]], "uint8")
    ref = np.array([[1, 0, 1, 255]], "uint8")
    zone = np.ones((1, 4), bool)
    assert holdout.iou(pred, ref, zone) == pytest.approx(0.5)


def _square(x0):
    m = np.zeros((40, 40), "uint8")
    m[10:20, x0:x0 + 10] = 1
    return m


def test_shoreline_distance_shifted_square():
    t = Affine(10, 0, 0, 0, -10, 400)
    d = holdout.shoreline_distance(_square(10), _square(11), t)
    assert d["median"] == pytest.approx(10, abs=1)
    assert d["mean_sym"] > 0 and d["p90"] >= d["median"]
    e = holdout.shoreline_distance(np.zeros((4, 4), "uint8"), _square(10)[:4, :4], t)
    assert all(np.isnan(v) for v in e.values())


def test_band_of_edges():
    assert budget.band_of(np.array([192.89, 192.9, 194.79, 194.8])).tolist() == ["<192.9", "192.9-194.8", "192.9-194.8", "194.8+"]
