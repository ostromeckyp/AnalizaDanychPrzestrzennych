import geopandas as gpd
import numpy as np
from affine import Affine
from shapely.geometry import LineString, Point

from mielizna import kz_deep
from mielizna.grid import Grid

GRID = Grid(crs="EPSG:2180", transform=Affine(10, 0, 0, 0, -10, 6000), width=600, height=600)


def _plane(x):
    return 190.0 + 0.001 * x


def _case(extra=None):
    rng = np.random.default_rng(1)
    xs = np.r_[rng.integers(50, 550, 26), 50, 550, 50, 550] * 10 + 5.0     # środki pikseli
    ys = np.r_[rng.integers(50, 550, 26), 50, 50, 550, 550] * 10 + 5.0
    rows = [{"id": i, "z": _plane(x), "geometry": Point(x, y)} for i, (x, y) in enumerate(zip(xs, ys))]
    spots = gpd.GeoDataFrame(rows, crs="EPSG:2180")
    c = gpd.GeoDataFrame({"level": [192.5]}, geometry=[LineString([(2500, 0), (2500, 6000)])], crs="EPSG:2180")
    if extra is not None:
        c = gpd.GeoDataFrame({"level": [192.5, 195.0]}, geometry=[c.geometry[0], extra], crs="EPSG:2180")
    return spots, c


def test_loo_plane_near_zero_and_hull_skipped():
    spots, c = _case()
    r = kz_deep.loo(spots, c, GRID, None, np.ones((600, 600), bool))
    assert r["n_skipped"] >= 1
    assert r["n"] + r["n_skipped"] == len(spots)
    assert abs(r["mae"]) < 1e-6
    assert all(np.isfinite(e["err"]) for e in r["errors"])
    assert np.isfinite([r["bias"], r["p5"], r["p95"], r["p90_abs"]]).all()


def test_195_contour_ignored():
    spots, c = _case()
    _, c2 = _case(extra=LineString([(1000, 1000), (1000, 5000)]))
    a = kz_deep.deep_surface(spots, c, GRID, None)
    b = kz_deep.deep_surface(spots, c2, GRID, None)
    np.testing.assert_array_equal(a, b)


def test_sign_positive_when_surface_above_point():
    spots, c = _case()
    k = 3
    spots.loc[k, "z"] = spots.loc[k, "z"] - 0.5                  # punkt głębiej niż powierzchnia
    r = kz_deep.loo(spots, c, GRID, None, np.ones((600, 600), bool))
    e = [x for x in r["errors"] if x["id"] == k]
    assert e and e[0]["err"] > 0.3 and abs(e[0]["err"] - (e[0]["pred"] - e[0]["z"])) < 1e-12


def test_point_eval_matches_full_surface():
    spots, c = _case()
    r = kz_deep.loo(spots, c, GRID, None, np.ones((600, 600), bool))
    for e in r["errors"][:3]:
        i = int(e["id"])
        full = kz_deep.deep_surface(spots.drop(index=i), c, GRID, None)
        row, col = GRID.rowcol(spots.geometry[i].x, spots.geometry[i].y)
        assert abs(full[row, col] - e["pred"]) < 1e-9


def test_mask_and_below_block():
    spots, c = _case()
    m = np.zeros((600, 600), bool)
    r = kz_deep.loo(spots, c, GRID, None, m)
    assert r["n"] == 0 and r["mae"] is None
    r = kz_deep.loo(spots, c, GRID, None, np.ones((600, 600), bool))
    assert r["below_192_9"]["n"] == sum(e["z"] < 192.9 for e in r["errors"]) > 0
