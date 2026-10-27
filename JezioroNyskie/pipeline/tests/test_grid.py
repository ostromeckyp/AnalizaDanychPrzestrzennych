from affine import Affine

from mielizna.grid import reference_grid


def test_reference_grid_shape_and_origin():
    g = reference_grid()
    assert (g.height, g.width) == (700, 900)
    assert g.transform == Affine(10, 0, 372000, 0, -10, 292500)
    assert g.crs == "EPSG:2180"
    assert g.bounds() == (372000, 285500, 381000, 292500)


def test_xy_rowcol_roundtrip():
    g = reference_grid()
    assert g.xy(0, 0) == (372005.0, 292495.0)
    assert g.rowcol(*g.xy(350, 420)) == (350, 420)
