import numpy as np
import pytest

from mielizna import combine

NINF = -np.inf


def _one(z_lo, z_hi, kz, p5=-1.4, p95=5.5):
    lo, hi, src, conf = combine.merge_kz(np.array([z_lo]), np.array([z_hi]), np.array([kz]), p5, p95)
    return lo[0], hi[0], src[0], conf[0]


def test_finite_satellite_unchanged():
    assert _one(192.0, 193.0, 190.0) == (192.0, 193.0, 0, False)


def test_kz_fills_always_water():
    lo, hi, src, conf = _one(NINF, 193.05, 190.0)
    assert lo == pytest.approx(184.5) and hi == pytest.approx(191.4) and src == 1 and not conf


def test_kz_zhi_capped_by_satellite():
    lo, hi, src, conf = _one(NINF, 193.05, 193.0)
    assert lo == pytest.approx(187.5) and hi == pytest.approx(193.05) and src == 1 and not conf


def test_conflict_keeps_satellite():
    lo, hi, src, conf = _one(NINF, 193.05, 199.0)
    assert lo == NINF and hi == 193.05 and src == 0 and conf


def test_no_kz_unchanged_and_nan_outside():
    assert _one(NINF, 193.05, np.nan) == (NINF, 193.05, 0, False)
    lo, hi, src, conf = _one(np.nan, np.nan, 190.0)
    assert np.isnan(lo) and np.isnan(hi) and src == 0 and not conf


def test_inputs_not_mutated():
    lo, hi = np.array([NINF]), np.array([193.05])
    combine.merge_kz(lo, hi, np.array([190.0]), -1.4, 5.5)
    assert lo[0] == NINF and hi[0] == 193.05


def test_zone_shares():
    z = combine.zone_shares(np.array([194.0, 190.0, np.nan]), np.array([194.5, 191.0, np.nan]),
                            np.array([True, True, False]), 194.5, 0.5, 0.3)
    assert z["n"] == 2 and z["safe"] + z["risk"] + z["danger"] == pytest.approx(1.0)
    assert z["safe"] == 0.5 and z["risk"] == 0.5 and z["danger"] == 0.0
