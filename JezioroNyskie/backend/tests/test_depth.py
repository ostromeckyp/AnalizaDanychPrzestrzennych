import numpy as np

from app import depth
from app.depth import Bounds, classify, depth_range, point_kind, satellite_bounds
from app.zones import DANGER, NONE, RISK, SAFE


def test_satellite_bounds_infinities_and_outside_model():
    z_min = np.array([[193.0, np.nan, 192.0], [191.0, 190.0, 189.0]], dtype=np.float32)
    z_max = np.array([[194.0, 195.0, np.nan], [192.0, 191.0, 190.0]], dtype=np.float32)
    obs = np.array([[3, 3, 3], [0, 65535, 3]], dtype=np.uint16)
    flags = np.array([[0, 0, 0], [0, 0, 255]], dtype=np.uint8)
    b = satellite_bounds(z_min, z_max, obs, flags)
    assert isinstance(b, Bounds)
    assert b.z_lo.dtype == np.float64 and b.z_hi.dtype == np.float64 and b.in_model.dtype == bool
    assert b.in_model.tolist() == [[True, True, True], [False, False, False]]
    assert b.z_lo[0, 0] == 193.0 and b.z_hi[0, 0] == 194.0
    assert b.z_lo[0, 1] == -np.inf and b.z_hi[0, 1] == 195.0     # NaN w z_min = zawsze woda
    assert b.z_lo[0, 2] == 192.0 and b.z_hi[0, 2] == np.inf      # NaN w z_max = zawsze ląd
    assert np.isnan(b.z_lo[1]).all() and np.isnan(b.z_hi[1]).all()
    assert b.source.dtype == np.uint8 and not b.source.any()
    assert b.kz_conflict.dtype == bool and not b.kz_conflict.any()


def test_depth_range():
    d_lo, d_hi = depth_range(195.0, np.array([[193.0]]), np.array([[194.0]]))
    assert d_lo.tolist() == [[1.0]] and d_hi.tolist() == [[2.0]]


def test_classify_three_pixels():
    z_lo = np.array([[190.0, 193.0, 196.0]])
    z_hi = np.array([[191.0, 194.0, 197.0]])
    b = Bounds(z_lo, z_hi, np.ones((1, 3), bool), np.zeros((1, 3), np.uint8), np.zeros((1, 3), bool))
    c = classify(195.0, 1.0, 0.3, b)
    assert c.tolist() == [[SAFE, RISK, DANGER]]
    b.in_model[0, 0] = False
    assert classify(195.0, 1.0, 0.3, b)[0, 0] == NONE


def test_point_kind():
    assert point_kind(195.0, 196.0) == "land"
    assert point_kind(195.0, 195.0) == "land"
    assert point_kind(195.0, -np.inf) == "always_water"
    assert point_kind(195.0, 193.0) == "model"
    assert depth.point_kind(195.0, 193.0) == "model"
