import numpy as np

from mielizna import blocks
from mielizna.grid import reference_grid

GRID = reference_grid()


def test_checkerboard_blocks():
    r = blocks.block_role(np.array([372100, 372600]), np.array([285600, 285600]), GRID)
    assert list(r) == ["calib", "valid"]


def test_checkerboard_flips_across_block_in_y_and_is_aligned_to_grid_corner():
    x = np.array([372499.9, 372500.0, 372100, 372100])
    y = np.array([285500.0, 285500.0, 285999.9, 286000.0])
    assert list(blocks.block_role(x, y, GRID)) == ["calib", "valid", "calib", "valid"]
