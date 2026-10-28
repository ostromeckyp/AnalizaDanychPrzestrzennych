from datetime import date

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, MultiLineString

from mielizna import variant_a

CX, CY = variant_a.DEFAULT_CENTER


def ring_points(n=400, z=195.40, noise=0.05, sectors=8, seed=1):
    rng = np.random.default_rng(seed)
    width = 2 * np.pi * sectors / 8
    ang = rng.uniform(0, width, n) - np.pi
    r = 2000 + rng.normal(0, 10, n)
    xy = np.column_stack([CX + r * np.cos(ang), CY + r * np.sin(ang)])
    return xy, z + rng.normal(0, noise, n)


def with_outliers():
    xy, z = ring_points()
    z = z.copy()
    z[::10] = 199.0  # 10% korona zapory
    return xy, z


def one_sector():
    return ring_points(n=400, sectors=1)


EPOCHS = pd.DataFrame({
    "epoch": [2011, 2017, 2022, 2024],
    "date": ["2011-03-20", "2017-02-27", "2022-03-23", "2024-09-06"],
    "date_span_days": [1, 26, 0, 0],
    "h_water_evrf": [194.639, 193.589, 195.69, 194.89]})


def test_level_from_dem_median_and_sigma():
    xy, z = ring_points()
    h, s, n = variant_a.level_from_dem(xy, z, h_lidar=194.0)
    assert h == pytest.approx(195.40, abs=0.02) and s < 0.1 and n == 400


def test_level_from_dem_ignores_dam_crest_outliers():
    h, _, _ = variant_a.level_from_dem(*with_outliers(), h_lidar=194.0)
    assert h == pytest.approx(195.40, abs=0.05)


def test_level_from_dem_rejects_one_sided_coverage():
    assert variant_a.level_from_dem(*one_sector(), h_lidar=194.0) is None


def test_level_from_dem_rejects_too_few_points_and_drops_water_level_points():
    xy, z = ring_points(n=40)
    assert variant_a.level_from_dem(xy, z, h_lidar=194.0) is None
    xy, z = ring_points(n=400, z=194.0, noise=0.02)   # wszystko <= h_lidar + 0,10 -> woda/mokra plaża
    assert variant_a.level_from_dem(xy, z, h_lidar=194.0) is None
    assert variant_a.diagnose(xy, z, 194.0)["n"] == 0


def test_choose_epoch_needs_lower_lidar_level():
    high = EPOCHS[EPOCHS.h_water_evrf >= 193.9]            # wszystkie epoki >= 193,9 >= h_guess - 0,2
    assert variant_a.choose_epoch(high, date(2023, 6, 1), h_guess=194.1) is None
    assert variant_a.choose_epoch(EPOCHS, date(2023, 6, 1), h_guess=194.1).epoch == 2017


def test_choose_epoch_nearest_in_time_among_lower():
    e = variant_a.choose_epoch(EPOCHS, date(2023, 6, 1), h_guess=195.5)
    assert e.epoch == 2024   # 2022 (195.69) odpada, 2024 jest najbliżej w czasie
    e = variant_a.choose_epoch(EPOCHS, date(2018, 6, 1), h_guess=195.5)
    assert e.epoch == 2017


def test_choose_epoch_tie_prefers_smaller_span():
    ep = pd.DataFrame({"epoch": [1, 2], "date": ["2020-01-01", "2020-01-11"], "date_span_days": [26, 0],
                       "h_water_evrf": [193.0, 193.0]})
    assert variant_a.choose_epoch(ep, date(2020, 1, 6), 195.0).epoch == 2


def test_choose_epoch_skips_epoch_without_date():
    ep = pd.DataFrame({"epoch": [1, 2], "date": ["", "2020-01-11"], "date_span_days": [None, 0],
                       "h_water_evrf": [193.0, 193.0]})
    assert variant_a.choose_epoch(ep, date(2020, 1, 6), 195.0).epoch == 2


def test_sample_shoreline_spacing_and_multiline():
    pts = variant_a.sample_shoreline(LineString([(0, 0), (100, 0)]), 5)
    assert len(pts) == 21 and pts[1, 0] == pytest.approx(5)
    m = MultiLineString([[(0, 0), (10, 0)], [(0, 10), (10, 10)]])
    assert len(variant_a.sample_shoreline(m, 5)) == 6


def test_nmt_sample_nodata_and_outside(tmp_path):
    arr = np.full((10, 10), 195.0, dtype="float32")
    arr[0, 0] = -9999
    p = tmp_path / "t.tif"
    with rasterio.open(p, "w", driver="GTiff", height=10, width=10, count=1, dtype="float32", crs="EPSG:2180",
                       transform=from_origin(1000, 2010, 1, 1), nodata=-9999) as d:
        d.write(arr, 1)
    z = variant_a.Nmt([p]).sample(np.array([[1000.5, 2009.5], [1005.5, 2005.5], [5000.0, 5000.0]]))
    assert np.isnan(z[0]) and z[1] == 195.0 and np.isnan(z[2])


def test_level_from_dem_max_sigma_gate():
    xy, z = ring_points(noise=0.5)
    assert variant_a.level_from_dem(xy, z, h_lidar=194.0) is not None
    assert variant_a.level_from_dem(xy, z, h_lidar=194.0, max_sigma=0.3) is None
