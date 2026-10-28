"""Testy porównania z mapą KŻ (K5): punkty w pasmach, poziomice, werdykt go/no-go, flaga `checked`."""
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from affine import Affine
from shapely.geometry import LineString, Point, Polygon

from mielizna import kz, kz_compare
from mielizna.grid import Grid

GRID = Grid(crs="EPSG:2180", transform=Affine(10, 0, 0, 0, -10, 1000), width=100, height=100)
NPP = 195.9


def model(z=194.0, half=0.2):
    full = np.full((GRID.height, GRID.width), z, float)
    return {"z": full, "z_min": full - half, "z_max": full + half}


def spots(rows):
    """rows: (x, y, z)."""
    return gpd.GeoDataFrame({"z": [r[2] for r in rows]}, geometry=[Point(r[0], r[1]) for r in rows], crs="EPSG:2180")


GRAVEL = Polygon([(800, 800), (1000, 800), (1000, 1000), (800, 1000)])
SPOTS = spots([(105, 105, 193.0), (305, 105, 194.0), (505, 105, 194.5),      # pasmo 192,5-195,0
               (105, 305, 195.5),                                              # 195,0-NPP
               (305, 305, 196.5),                                              # NPP+
               (505, 305, 191.0),                                              # poniżej 192,5
               (850, 850, 193.5)])                                             # żwirownia - pomijana


def test_rejected_spots_never_scored():
    ocr = gpd.GeoDataFrame({"id": [0, 1], "z": [193.0, 194.0], "px": [10.0, 50.0], "py": [10.0, 50.0], "conf": [95.0, 95.0],
                            "color_ok": [True, True]}, geometry=[Point(0, 0), Point(10, 10)], crs="EPSG:2180")
    qc = pd.DataFrame({"id": [0, 1], "ocr_z": [193.0, 194.0], "qc": ["ok", "rejected"], "z_qc": [np.nan, np.nan],
                       "px": [10.0, 50.0], "py": [10.0, 50.0]})
    out = kz.load_qc_spots(ocr, qc)
    assert 1 not in set(out.id) and out.checked.tolist() == [True]


def test_checked_flag_false_for_unjudged_true_for_judged():
    ocr = gpd.GeoDataFrame({"id": [0, 1], "z": [193.0, 194.0], "px": [10.0, 50.0], "py": [10.0, 50.0], "conf": [95.0, 95.0],
                            "color_ok": [True, True]}, geometry=[Point(0, 0), Point(10, 10)], crs="EPSG:2180")
    qc = pd.DataFrame({"id": [0], "ocr_z": [193.0], "qc": ["ok"], "z_qc": [np.nan], "px": [10.0], "py": [10.0]})
    out = kz.load_qc_spots(ocr, qc).set_index("id")
    assert bool(out.loc[0, "checked"]) and not bool(out.loc[1, "checked"])
    assert kz.load_qc_spots(ocr, None).checked.tolist() == [False, False]


def test_points_banded_and_gravel_excluded():
    r = kz_compare.compare_points(SPOTS, model(), GRAVEL, npp=NPP, grid=GRID, verdict="good")
    assert set(r) >= {"192.5-195.0", "195.0-npp", "npp+", "below_192.5", "pooled"}
    assert r["192.5-195.0"]["n"] == 3 and r["195.0-npp"]["n"] == 1 and r["below_192.5"]["n"] == 1
    assert r["pooled"]["n"] == 5                                   # bez pasma < 192,5 i bez żwirowni
    # bias = model - KŻ; (194-193 + 0 + (-0.5)) / 3
    assert r["192.5-195.0"]["bias"] == pytest.approx((1.0 + 0.0 - 0.5) / 3)
    assert r["192.5-195.0"]["share_in_bounds"] == pytest.approx(1 / 3)       # w [193,8; 194,2] tylko 194,0
    assert r["pooled"]["bands"] == "192.5+"


def test_points_without_model_are_dropped_and_counted():
    m = model()
    m["z"][0:20, 0:20] = np.nan                                    # lewy górny róg (x<200, y>800) bez modelu
    s = spots([(105, 905, 194.0), (305, 105, 194.0)])
    r = kz_compare.compare_points(s, m, None, npp=NPP, grid=GRID, verdict="good")
    assert r["192.5-195.0"]["n"] == 1 and r["192.5-195.0"]["n_spots"] == 2


def test_aggregated_only_compares_50m_cell_medians():
    # dwa punkty KŻ w jednej komórce 50 m: mediana 193,0 i 195,0 = 194,0; model stały 194,0 -> błąd 0
    s = spots([(105, 105, 193.0), (120, 110, 195.0), (135, 120, 194.0)])
    r = kz_compare.compare_points(s, model(), None, npp=NPP, grid=GRID, verdict="aggregated_only")
    b = r["192.5-195.0"]
    assert b["n"] == 1 and b["bias"] == pytest.approx(0.0) and b["unit"] == "cell50"


def test_symmetric_mean_distance_of_parallel_lines():
    a = LineString([(0, 0), (1000, 0)])
    b = LineString([(0, 10), (1000, 10)])
    assert kz_compare.mean_distance(a, b) == pytest.approx(10.0)
    assert kz_compare.mean_distance(a, b) == pytest.approx(kz_compare.mean_distance(b, a))


def test_symmetric_mean_distance_is_symmetric_for_unequal_lines():
    a = LineString([(0, 0), (1000, 0)])
    b = LineString([(0, 10), (200, 10)])
    assert kz_compare.mean_distance(a, b) == pytest.approx(kz_compare.mean_distance(b, a))


def test_model_contour_recovers_known_level():
    rr, cc = np.mgrid[0:GRID.height, 0:GRID.width]
    z = 190.0 + 0.01 * (cc * 10.0)                                 # rośnie na wschód 1 cm / m; 195,0 przy x = 500 m
    line = kz_compare.model_contour(z, GRID, 195.0)
    xs = np.array(line.coords if line.geom_type == "LineString" else [c for g in line.geoms for c in g.coords])[:, 0]
    assert xs.mean() == pytest.approx(500.0, abs=6.0)
    assert kz_compare.model_contour(z, GRID, 250.0).is_empty


def test_compare_contours_reports_distance_hausdorff_and_coverage():
    kz_line = LineString([(0, 0), (500, 0)])
    model_line = LineString([(0, 20), (2000, 20)])                 # model dłuższy niż próbka KŻ
    r = kz_compare.compare_contours(kz_line, model_line, clip_m=150.0)
    assert 20.0 <= r["mean_distance_m"] < 40.0                     # nadmiar modelu w buforze (do 150 m) podnosi średnią symetryczną
    assert r["hausdorff_m"] >= 20.0
    assert r["kz_length_km"] == pytest.approx(0.5) and r["model_length_km_total"] == pytest.approx(2.0)
    assert 0.5 < r["model_length_km_compared"] < 1.0               # 500 m + 2 x ~149 m
    assert r["kz_to_model_mean_m"] == pytest.approx(20.0, abs=0.5)


def test_go_no_go_investigate_when_bias_large():
    r = kz_compare.go_no_go(bias=0.7, datum_offset=0.199, other_biases={"lidar_all": 1.16, "lidar_pre_flood": 0.20})
    assert r["decision"] == "investigate" and r["notes"]
    ok = kz_compare.go_no_go(bias=-0.3, datum_offset=0.199, other_biases={})
    assert ok["decision"] == "go"


def test_npp_matches_backend_value():
    assert kz_compare.npp_level() == pytest.approx(195.91, abs=0.01)
