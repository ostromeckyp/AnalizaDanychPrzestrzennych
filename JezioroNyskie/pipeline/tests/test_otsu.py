import numpy as np
import pytest

from mielizna.otsu import otsu_mask, otsu_threshold


def test_otsu_bimodal():
    rng = np.random.default_rng(0)
    m = np.concatenate([rng.normal(-0.3, .15, 6000), rng.normal(0.35, .12, 4000)])
    assert -0.1 < otsu_threshold(m, np.ones_like(m, bool)) < 0.12


def test_otsu_ignores_pixels_outside_aoi():
    rng = np.random.default_rng(1)
    m = np.concatenate([rng.normal(-0.3, .15, 600), rng.normal(0.35, .12, 400), np.full(5000, .9)])
    aoi = np.r_[np.ones(1000, bool), np.zeros(5000, bool)]
    assert -0.1 < otsu_threshold(m, aoi) < 0.12


def test_otsu_empty_aoi_raises():
    m = np.array([0.1, -0.2, 0.3])
    with pytest.raises(ValueError):
        otsu_threshold(m, np.zeros_like(m, bool))


def test_otsu_mask_nan_is_nodata():
    assert otsu_mask(np.array([np.nan, .5, -.5]), 0.0).tolist() == [255, 1, 0]
