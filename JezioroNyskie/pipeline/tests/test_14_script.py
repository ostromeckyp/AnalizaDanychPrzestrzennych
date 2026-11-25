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


def test_write_spots_csv_in_grid_crs(tmp_path):
    """Punkty KŻ użyte do powierzchni/LOO trafiają do `kz_spots.csv` (id, x, y, z) w układzie siatki."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Point
    spots = gpd.GeoDataFrame({"id": [7, 3], "z": [190.5, 188.25], "px": [1, 2]},
                             geometry=[Point(17.25, 50.46), Point(375100.0, 289900.0)], crs="EPSG:4326")
    spots.loc[1, "geometry"] = gpd.GeoSeries([Point(375100.0, 289900.0)], crs="EPSG:2180").to_crs(4326).iloc[0]
    s14.write_spots(tmp_path / "kz_spots.csv", spots, "EPSG:2180")
    df = pd.read_csv(tmp_path / "kz_spots.csv")
    assert list(df.columns) == ["id", "x", "y", "z"]
    assert df["id"].tolist() == [7, 3] and df["z"].tolist() == [190.5, 188.25]
    assert abs(df["x"][1] - 375100.0) < 0.01 and abs(df["y"][1] - 289900.0) < 0.01
