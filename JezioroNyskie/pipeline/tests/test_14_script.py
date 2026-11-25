import importlib.util
from pathlib import Path

import numpy as np

_SPEC = importlib.util.spec_from_file_location("kzdeep14", Path(__file__).parents[1] / "14_kz_deep.py")
s14 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(s14)

DELTAS = {"<192.9": {"delta_lo": 0.0, "delta_hi": 0.0},
          "192.9-194.8": {"delta_lo": 0.1, "delta_hi": 2.0},
          "194.8+": {"delta_lo": 1.0, "delta_hi": 0.5}}


def test_two_sided_only_calibrates_only_pixels_with_both_bounds():
    """Wariant raportowy: jednostronne granice (np. „zawsze woda”: −∞ / 193,05) zostają surowe."""
    z_lo = np.array([193.0, -np.inf, 195.0, np.nan])
    z_hi = np.array([194.0, 193.05, np.inf, np.nan])
    lo, hi = s14.calibrate_two_sided_only(z_lo, z_hi, DELTAS)
    np.testing.assert_allclose(lo[:3], [192.9, -np.inf, 195.0])
    np.testing.assert_allclose(hi[:3], [196.0, 193.05, np.inf])
    assert np.isnan(lo[3]) and np.isnan(hi[3])
    # serwowana kalibracja (wszędzie) zmienia granicę jednostronną — różnica wariantów jest właśnie tu
    lo_all, hi_all = s14.calibration.apply(z_lo, z_hi, DELTAS)
    assert hi_all[1] == 193.05 + 2.0 and lo_all[2] == 195.0 - 1.0


def test_kz_above_zmax_counts_only_covered_always_water():
    surf = np.array([193.5, 192.0, np.nan, 194.0])
    z_hi = np.array([193.05, 193.05, 193.05, 193.05])
    always = np.array([True, True, True, False])
    r = s14.kz_above_zmax(surf, z_hi, always)
    assert r["n_covered"] == 2
    assert r["coverage"] == 2 / 3
    assert r["kz_above_zmax_share"] == 0.5
