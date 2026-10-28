"""Testy mielizna.lidar: data nalotu z czasu GPS, klasa i poziom wody (fikstury LAZ tworzone w teście, bez sieci)."""
from datetime import date

import laspy
import numpy as np
import pytest
from shapely.geometry import box

from mielizna import lidar

CORE = box(1000, 1000, 1100, 1100)


def make_laz(tmp_path, gps=None, adjusted=True, classes=None, name="tiny.laz"):
    """Mały LAZ (format 3, GPS time). `classes` = {klasa: z}; punkty w CORE (klasa 2 poza rdzeniem nie jest wymagana)."""
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = np.array([0.01, 0.01, 0.01])
    header.offsets = np.array([1000.0, 1000.0, 190.0])
    if adjusted:
        header.global_encoding.gps_time_type = laspy.header.GpsTimeType.STANDARD
    else:
        header.global_encoding.gps_time_type = laspy.header.GpsTimeType.WEEK_TIME
    rng = np.random.default_rng(0)
    xs, ys, zs, cs = [], [], [], []
    for cls, z in (classes or {}).items():
        n = 400
        xs.append(rng.uniform(1010, 1090, n)); ys.append(rng.uniform(1010, 1090, n))
        zs.append(z + rng.normal(0, 0.02, n)); cs.append(np.full(n, cls))
    if gps is not None and not xs:
        xs, ys, zs, cs = [np.full(len(gps), 1050.0)], [np.full(len(gps), 1050.0)], [np.full(len(gps), 194.0)], [np.zeros(len(gps), int)]
    x, y, z, c = map(np.concatenate, (xs, ys, zs, cs))
    las = laspy.LasData(header)
    las.x, las.y, las.z = x, y, z
    las.classification = c.astype(np.uint8)
    las.gps_time = np.resize(np.asarray(gps if gps is not None else [0.0], float), len(x))
    p = tmp_path / name
    las.write(str(p))
    return p


def test_flight_date_from_adjusted_gps(tmp_path):     # 1980-01-06 + (2.0e8 + 1e9 - 18) s
    assert lidar.flight_dates(make_laz(tmp_path, gps=[2.0e8], adjusted=True)) == [date(2018, 1, 14)]


def test_flight_dates_unique_sorted(tmp_path):
    p = make_laz(tmp_path, gps=[2.0e8 + 86400 * 2, 2.0e8, 2.0e8 + 5], adjusted=True)
    assert lidar.flight_dates(p) == [date(2018, 1, 14), date(2018, 1, 16)]


def test_week_time_gives_no_date(tmp_path, caplog):
    assert lidar.flight_dates(make_laz(tmp_path, gps=[3600.0], adjusted=False)) == []
    assert "GPS week time" in caplog.text


def test_water_class_and_level(tmp_path):
    p = make_laz(tmp_path, classes={9: 194.31, 2: 200.0})
    assert lidar.water_class(p, CORE) == 9
    h, iqr, n = lidar.water_level(p, CORE, 9)
    assert h == pytest.approx(194.31, abs=0.01) and n > 100 and 0 < iqr < 0.1


def test_water_level_ignores_points_outside_core(tmp_path):
    p = make_laz(tmp_path, classes={9: 194.31})
    assert lidar.water_level(p, box(0, 0, 10, 10), 9)[2] == 0


def test_multiple_files_pooled(tmp_path):
    a = make_laz(tmp_path, classes={9: 194.0}, name="a.laz")
    b = make_laz(tmp_path, classes={9: 194.2}, name="b.laz")
    h, _, n = lidar.water_level([a, b], CORE, 9)
    assert n == 800 and h == pytest.approx(194.1, abs=0.15)
