import numpy as np
import pytest
from affine import Affine

from mielizna import evaluate
from mielizna.grid import Grid

NAN = np.nan


def _model():
    z = np.array([[193.0, 194.0], [195.0, NAN]])
    return {"z": z, "z_min": np.array([[NAN, 193.5], [194.5, NAN]]),
            "z_max": np.array([[193.5, 194.5], [195.5, NAN]]), "unc": np.full((2, 2), 0.5)}


DEM = np.array([[193.2, 194.1], [195.9, 195.0]])


def test_metrics_basic():
    assert evaluate.metrics(np.array([1., 2.]), np.array([1.5, 1.5])) == {"n": 2, "mae": 0.5, "rmse": 0.5, "bias": 0.0}


def test_metrics_empty_is_nan_not_error():
    m = evaluate.metrics(np.array([]), np.array([]))
    assert m["n"] == 0 and np.isnan(m["rmse"])


def test_share_in_bounds_open_lower():
    assert evaluate.share_in_bounds(np.array([1., 5.]), np.array([np.nan, 0.]), np.array([2., 2.])) == 0.5


def test_only_valid_blocks_are_scored():
    roles = np.full((2, 2), "calib")
    r = evaluate.bottom_vs_dem(_model(), DEM, h_water=194.0, roles=roles)
    assert r["n"] == 0


def test_bottom_vs_dem_filters_water_and_missing_model():
    roles = np.full((2, 2), "valid")
    # h_water 194.0 + 0.1: piksel (0,0) 193.2 i (0,1) 194.1 odpadają (<= 194.1), (1,1) bez z
    r = evaluate.bottom_vs_dem(_model(), DEM, h_water=194.0, roles=roles)
    assert r["n"] == 1 and r["bias"] == pytest.approx(-0.9) and r["share_in_bounds"] == 0.0
    r2 = evaluate.bottom_vs_dem(_model(), DEM, h_water=190.0, roles=roles)
    assert r2["n"] == 3 and r2["share_in_bounds"] == pytest.approx(2 / 3)   # 193.2 w (-inf,193.5], 194.1 w [193.5,194.5]


def test_model_choice_threshold():
    assert evaluate.choose_model(0.049)["period"] == "all" and evaluate.choose_model(0.05)["period"] == "post_flood"
    assert "5" in evaluate.choose_model(0.2)["reason"]


def test_bottom_change_significance():
    pre = {"z": np.array([[1., 1., NAN]]), "unc": np.array([[.1, .1, .1]])}
    post = {"z": np.array([[1.1, 2., 1.]]), "unc": np.array([[.1, .1, .1]])}
    r = evaluate.bottom_change(pre, post)
    assert r["n"] == 2 and r["share_significant"] == 0.5     # 0,1 < 0,2; 1,0 > 0,2; trzeci bez pre


def test_dem_to_grid_mean_and_coverage():
    grid = Grid("EPSG:2180", Affine(10, 0, 0, 0, -10, 20), 2, 2)
    # arkusz 1 m: 20x20, lewy górny róg (0, 20); piksel modelu (0,0) = 10x10 m
    z = np.full((20, 20), 5.0, np.float32)
    z[:10, :10] = 2.0
    z[:10, :10][:, :6] = -9999                      # 60 % nodata w pikselu (0,0) -> pokrycie 40 % < 50 %
    z[10:, 10:] = 8.0
    z[10:, 10:][:5, :] = -9999                      # 50 % pokrycia w pikselu (1,1) -> zostaje
    out = evaluate.dem_to_grid([(z, Affine(1, 0, 0, 0, -1, 20), -9999.)], grid, offset=0.5, min_cover=0.5)
    assert np.isnan(out[0, 0])
    assert out[0, 1] == pytest.approx(5.5) and out[1, 0] == pytest.approx(5.5)   # +offset dokładnie raz
    assert out[1, 1] == pytest.approx(8.5)
