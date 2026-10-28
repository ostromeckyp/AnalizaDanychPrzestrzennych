"""Testy wariantu D: powierzchnia z mapy KŻ, dopasowanie poziomu do linii brzegowej, wczytanie punktów po QC."""
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from affine import Affine
from shapely.geometry import LineString, Point, Polygon

from mielizna import kz, variant_d
from mielizna.grid import Grid

# siatka 6 x 6 km, 10 m; środek stożka w (X0, Y0)
GRID = Grid(crs="EPSG:2180", transform=Affine(10, 0, 0, 0, -10, 6000), width=600, height=600)
X0, Y0 = 3000.0, 3000.0
LEVELS = np.arange(192.5, 198.0 + 1e-9, 0.05)


def cone(z_center=190.0, slope=0.002):
    rr, cc = np.mgrid[0:GRID.height, 0:GRID.width]
    x = GRID.transform.c + (cc + 0.5) * 10
    y = GRID.transform.f - (rr + 0.5) * 10
    return z_center + slope * np.hypot(x - X0, y - Y0)


def circle(r):
    t = np.linspace(0, 2 * np.pi, 400)
    return LineString(np.c_[X0 + r * np.cos(t), Y0 + r * np.sin(t)])


def test_fit_level_on_cone_surface():
    surf = cone()
    h, d = variant_d.fit_level(circle(2500.0), surf, GRID, LEVELS)   # 190 + 0.002 * 2500 = 195,0
    assert h == pytest.approx(195.0, abs=0.05) and d < 10


def test_fit_level_too_few_points_returns_nan():
    surf = cone()
    h, d = variant_d.fit_level(circle(2500.0), surf, GRID, LEVELS, min_points=10_000)
    assert np.isnan(h) and np.isnan(d)


def test_fit_level_skips_points_where_surface_is_nan():
    surf = cone()
    surf[:, 300:] = np.nan                      # połowa jeziora bez powierzchni
    h, d = variant_d.fit_level(circle(2500.0), surf, GRID, LEVELS)
    assert h == pytest.approx(195.0, abs=0.05)


def _inputs():
    xs = np.array([1000, 5000, 5000, 1000, 3000, 2000, 4000, 3000.0])
    ys = np.array([1000, 1000, 5000, 5000, 3000, 4000, 2000, 1500.0])
    spots = gpd.GeoDataFrame({"z": 190 + 0.002 * np.hypot(xs - X0, ys - Y0)},
                             geometry=[Point(a, b) for a, b in zip(xs, ys)], crs="EPSG:2180")
    cont = gpd.GeoDataFrame({"level": [192.5]}, geometry=[circle(1250.0)], crs="EPSG:2180")
    return spots, cont


def test_surface_nan_in_gravel_and_outside_hull():
    spots, cont = _inputs()
    gravel = Polygon([(2000, 2000), (2400, 2000), (2400, 2400), (2000, 2400)])
    surf = variant_d.kz_surface(spots, cont, GRID, gravel=gravel)
    r, c = GRID.rowcol(2200, 2200)
    assert np.isnan(surf[r, c])
    r, c = GRID.rowcol(300, 300)                # poza otoczką punktów
    assert np.isnan(surf[r, c])
    r, c = GRID.rowcol(3000, 3500)
    assert surf[r, c] == pytest.approx(191.0, abs=0.1)
    no_gravel = variant_d.kz_surface(spots, cont, GRID)
    r, c = GRID.rowcol(2200, 2200)
    assert np.isfinite(no_gravel[r, c])


def _spots_qc():
    ocr = gpd.GeoDataFrame({"id": [0, 1, 2, 3, 4], "z": [190.0, 191.0, 192.0, 193.0, 194.0],
                            "px": [10.0, 20, 30, 40, 50], "py": [10.0, 20, 30, 40, 50],
                            "conf": [95.0, 95, 95, 60, 95], "color_ok": [True, True, True, True, False]},
                           geometry=[Point(i, i) for i in range(5)], crs="EPSG:2180")
    return ocr


def test_load_qc_spots_without_qc_keeps_confident_colour_ok():
    out = kz.load_qc_spots(_spots_qc(), None)
    assert sorted(out.id) == [0, 1, 2]
    out2 = kz.load_qc_spots(_spots_qc(), pd.DataFrame(columns=["id", "ocr_z", "qc", "z_qc", "px", "py"]))
    assert sorted(out2.id) == [0, 1, 2]


def test_load_qc_spots_with_qc_uses_ok_corrected_and_drops_rejected():
    qc = pd.DataFrame({"id": [9, 9, 9, 9], "ocr_z": [190.0, 191.0, 192.0, 193.0],
                       "qc": ["ok", "corrected", "rejected", "ok"], "z_qc": [np.nan, 191.5, np.nan, np.nan],
                       "px": [10.0, 20, 30, 41], "py": [10.0, 20, 30, 41]})
    out = kz.load_qc_spots(_spots_qc(), qc).set_index("id")
    # 0 ok, 1 poprawiony, 2 odrzucony, 3 ok (kotwica 1 px od 40), 4 nieoceniony: kolor zły -> odpada
    assert sorted(out.index) == [0, 1, 3]
    assert out.loc[1, "z"] == 191.5 and out.loc[0, "z"] == 190.0


def test_load_qc_spots_unjudged_fall_back_to_unchecked_rule():
    qc = pd.DataFrame({"id": [0], "ocr_z": [190.0], "qc": ["rejected"], "z_qc": [np.nan],
                       "px": [10.0], "py": [10.0]})
    out = kz.load_qc_spots(_spots_qc(), qc)
    assert sorted(out.id) == [1, 2]             # 0 odrzucony; 1, 2 nieocenione i pewne; 3 niepewny; 4 zły kolor


def test_summarize_shares_and_by_method():
    fit = pd.DataFrame({"date": ["a", "b", "c", "d"], "h_t_d": [194.0, 194.5, 195.0, np.nan]})
    sc = pd.DataFrame({"date": ["a", "b", "c", "d"], "h_t": [194.1, 194.1, 195.0, 194.0],
                       "h_method": ["B", "B", "A", "C"]})
    s = variant_d.summarize(fit, sc)
    assert s["n_scenes"] == 3 and s["share_within_0_2"] == pytest.approx(2 / 3)
    assert s["median_abs_diff"] == pytest.approx(0.1)
    assert s["by_method"]["B"]["n"] == 2 and s["by_method"]["C"]["n"] == 0 and s["by_method"]["R"]["n"] == 0
