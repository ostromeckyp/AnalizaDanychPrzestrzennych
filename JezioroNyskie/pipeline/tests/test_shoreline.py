import numpy as np
import pytest
from affine import Affine

from mielizna.shoreline import mask_to_shoreline


def test_shoreline_area_of_square():
    m = np.zeros((30, 30), np.uint8); m[10:20, 10:20] = 1
    geom, area = mask_to_shoreline(m, Affine(10, 0, 0, 0, -10, 300))
    assert area == pytest.approx(0.01) and geom.length == pytest.approx(400, rel=0.05)


def test_shoreline_uses_largest_polygon_and_skips_nodata():
    m = np.zeros((30, 30), np.uint8); m[10:20, 10:20] = 1; m[0:2, 0:2] = 1; m[25:, :] = 255
    geom, area = mask_to_shoreline(m, Affine(10, 0, 0, 0, -10, 300))
    assert area == pytest.approx(0.0104)               # wszystkie piksele == 1, nie tylko największy
    assert geom.length == pytest.approx(400, rel=0.05)  # linia tylko największego poligonu


def test_shoreline_empty_mask():
    geom, area = mask_to_shoreline(np.zeros((5, 5), np.uint8), Affine(10, 0, 0, 0, -10, 50))
    assert geom.is_empty and area == 0.0
