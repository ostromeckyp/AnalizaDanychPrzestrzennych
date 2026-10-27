import numpy as np

from mielizna.otsu import otsu_mask, otsu_threshold


def test_otsu_bimodal():
    rng = np.random.default_rng(0)
    m = np.concatenate([rng.normal(-0.4, .05, 5000), rng.normal(0.4, .05, 5000)])
    t = otsu_threshold(m, np.ones_like(m, bool))
    assert -0.15 < t < 0.15


def test_otsu_ignores_pixels_outside_aoi():
    rng = np.random.default_rng(1)
    m = np.concatenate([rng.normal(-.5, .05, 500), rng.normal(.5, .05, 500), np.full(5000, .9)])
    aoi = np.r_[np.ones(1000, bool), np.zeros(5000, bool)]
    assert -0.2 < otsu_threshold(m, aoi) < 0.2


def test_otsu_mask_nan_is_nodata():
    assert otsu_mask(np.array([np.nan, .5, -.5]), 0.0).tolist() == [255, 1, 0]
