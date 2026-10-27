import datetime as dt

import numpy as np

from mielizna.features import FEATURES, compute_features, indices, stack
from mielizna.s2 import BANDS


def _bands(shape=(5, 5), **over):
    vals = dict(blue=.05, green=.06, red=.04, nir=.02, swir16=.01, swir22=.005)
    vals.update(over)
    return {k: np.full(shape, v, dtype=np.float32) for k, v in vals.items()}


def test_indices_known_values():
    b = {k: np.array([v]) for k, v in dict(blue=.05, green=.06, red=.04, nir=.02, swir16=.01, swir22=.005).items()}
    i = indices(b)
    assert np.isclose(i["mndwi"][0], (0.06 - 0.01) / (0.06 + 0.01))
    assert np.isclose(i["awei_nsh"][0], 4 * (0.06 - 0.01) - (0.25 * 0.02 + 2.75 * 0.005))
    assert np.isclose(i["awei_sh"][0], 0.05 + 2.5 * 0.06 - 1.5 * (0.02 + 0.01) - 0.25 * 0.005)
    assert np.isclose(i["ndvi"][0], (0.02 - 0.04) / (0.02 + 0.04))


def test_zero_denominator_is_nan():
    b = {k: np.array([0.0]) for k in BANDS}
    assert np.isnan(indices(b)["ndwi"][0])


def test_feature_list_has_no_leaky_inputs():
    assert set(FEATURES).isdisjoint({"nmt", "dem", "water_freq", "h_t"})


def test_compute_features_has_all_and_season():
    f = compute_features(_bands(), 0.1, dt.date(2021, 7, 1))
    assert set(f) == set(FEATURES)
    assert np.allclose(f["mndwi_minus_otsu"], f["mndwi"] - 0.1)
    doy = dt.date(2021, 7, 1).timetuple().tm_yday
    assert np.isclose(f["doy_sin"][0, 0], np.sin(2 * np.pi * doy / 365.25))
    assert np.isclose(f["doy_cos"][0, 0], np.cos(2 * np.pi * doy / 365.25))


def test_window_mean_excludes_nan_neighbour():
    green = np.full((5, 5), .06, dtype=np.float32)
    swir = np.full((5, 5), .01, dtype=np.float32)
    swir[1, 1] = np.nan                       # sąsiad piksela (2, 2)
    f = compute_features(_bands() | {"swir16": swir}, 0.0, dt.date(2021, 7, 1))
    m = (0.06 - 0.01) / (0.06 + 0.01)
    assert np.isnan(f["mndwi"][1, 1]) and np.isnan(f["mndwi_mean3"][1, 1])
    assert np.isclose(f["mndwi_mean3"][2, 2], m)      # 8 ważnych sąsiadów, wszyscy = m
    assert np.isclose(f["mndwi_std3"][2, 2], 0.0, atol=1e-5)


def test_window_mean_value():
    sw = np.full((5, 5), .01, dtype=np.float32)
    sw[2, 3] = .03
    f = compute_features(_bands() | {"swir16": sw}, 0.0, dt.date(2021, 7, 1))
    m = f["mndwi"]
    assert np.isclose(f["mndwi_mean3"][2, 2], m[1:4, 1:4].mean(), atol=1e-5)
    assert np.isclose(f["mndwi_std3"][2, 2], m[1:4, 1:4].std(), atol=1e-4)


def test_stack_shape_and_order():
    f = compute_features(_bands((4, 6)), 0.0, dt.date(2021, 7, 1))
    s = stack(f)
    assert s.shape == (4, 6, len(FEATURES))
    for k, name in enumerate(FEATURES):
        assert np.allclose(s[..., k], f[name], equal_nan=True)
