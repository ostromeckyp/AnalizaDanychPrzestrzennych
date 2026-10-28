"""Testy poziomic KŻ (K3) i obrysu żwirowni: maska koloru, szkielet -> linie, wielokąt z wierzchołków (bez sieci)."""
import numpy as np
import pytest
from shapely.geometry import Point, box

from mielizna import kz

# afiniczna fikstura piksel -> EPSG:2180: 1 px = 1 m, oś y obrazu w dół
T_AFFINE = kz.KzTransform("affine", lambda px, py: (np.asarray(px) + 375000.0, 290000.0 - np.asarray(py)),
                          lambda x, y: (np.asarray(x) - 375000.0, 290000.0 - np.asarray(y)), 0.0, 0.0, 0, 0)
LAKE_FIXTURE = box(375100, 289000, 375600, 289700)
VERTS = [(300.0, 400.0), (500.0, 380.0), (520.0, 600.0), (310.0, 620.0)]


def draw_solid_and_dashed():
    m = np.zeros((200, 600), bool)
    m[50:53, 50:450] = True                 # linia ciągła 400 px, grubość 3
    for k in range(10):                      # przerywana: 10 kresek po 30 px, przerwa 10 px
        m[120:123, 50 + 40 * k:80 + 40 * k] = True
    return m


def test_mask_to_lines_drops_dashed_segments():
    lines = kz.mask_to_lines(draw_solid_and_dashed(), min_len_px=80)
    assert len(lines) == 1 and lines[0].length > 350


def test_mask_to_lines_prunes_short_spur_and_keeps_one_line():
    m = np.zeros((100, 400), bool)
    m[50:53, 20:380] = True
    m[40:50, 200:203] = True                # krótki ogonek (litera przy linii)
    lines = kz.mask_to_lines(m, min_len_px=80)
    assert len(lines) == 1 and lines[0].length > 340


def test_color_mask_tolerance():
    img = np.zeros((4, 4, 3), np.uint8)
    img[0, 0] = (15, 30, 140)
    img[1, 1] = (15, 30, 200)
    m = kz.color_mask(img, (15, 30, 140), 20)
    assert m[0, 0] and not m[1, 1] and m.sum() == 1


def test_lines_to_2180_uses_transform():
    from shapely.geometry import LineString
    out = kz.lines_to_2180([LineString([(0, 0), (10, 5)])], T_AFFINE)
    assert list(out[0].coords) == [(375000.0, 290000.0), (375010.0, 289995.0)]


def test_gravel_polygon_valid_and_inside_lake():
    g = kz.vertices_to_polygon(VERTS, T_AFFINE)
    assert g.is_valid and g.geom_type == "Polygon" and g.within(LAKE_FIXTURE.buffer(50))


def test_gravel_polygon_fixes_bowtie_and_rejects_degenerate():
    g = kz.vertices_to_polygon([(0, 0), (100, 100), (100, 0), (0, 100)], T_AFFINE)
    assert g.is_valid and g.area > 0
    with pytest.raises(ValueError):
        kz.vertices_to_polygon([(0, 0), (1, 1)], T_AFFINE)


def test_contour_levels_split_by_neighbour_fills():
    # 195,0: linia między lądem a białym pasem; 192,5: między białym pasem a wodą; inna poziomica w bieli: odrzucona
    img = np.zeros((120, 200, 3), np.uint8)
    img[:] = (240, 248, 252)                          # biały pas
    img[:40] = (150, 190, 120)                        # ląd
    img[80:] = (195, 235, 250)                        # woda głębsza
    line = (15, 30, 140)
    img[39:42, :] = line                              # 195,0
    img[79:82, :] = line                              # 192,5
    img[60:62, :] = line                              # wewnątrz pasa (np. 193,0) – lądu brak, wody brak
    colors = {"line": [15, 30, 140], "line_tol": 40, "shallow": [240, 248, 252], "shallow_tol": 12,
              "deep": [195, 235, 250], "deep_tol": 25, "ring_px": 6}
    m = kz.contour_level_masks(img, colors)
    assert m[195.0][40, 100] and not m[195.0][80, 100]
    assert m[192.5][80, 100] and not m[192.5][40, 100]
    assert not m[195.0][61, 100] and not m[192.5][61, 100]


COLORS = {"line": [40, 60, 170], "line_tol": 90, "shallow": [248, 251, 253], "shallow_tol": 14,
          "deep": [195, 235, 250], "deep_tol": 35, "ring_px": 8, "grow_px": 4}
LAND, WATER, NAVY, GREY = (160, 189, 131), (195, 235, 250), (15, 30, 140), (125, 130, 135)


def _land_water(line_rgb, thickness=3):
    img = np.zeros((120, 300, 3), np.uint8)
    img[:60] = LAND
    img[60:] = WATER
    img[60 - 1:60 - 1 + thickness, :] = line_rgb
    return img


def test_grey_grid_line_on_shore_is_not_a_contour():
    img = _land_water(GREY)
    m = kz.contour_level_masks(img, COLORS)
    assert not m[195.0].any() and not m[192.5].any()


def test_navy_shore_line_still_195():
    m = kz.contour_level_masks(_land_water(NAVY), COLORS)
    assert m[195.0][59, 150]


def _sides(img, y, x0=20, x1=280):
    xy = np.column_stack([np.arange(x0, x1, 1.0), np.full(x1 - x0, float(y))])
    return kz.line_side_votes(img, xy, offset_px=8)


def test_side_votes_shore_line_is_land_vs_water():
    frac, n = _sides(_land_water(NAVY), 60)
    assert frac > 0.9 and n >= 10


def test_side_votes_line_inside_land_or_inside_water_is_not_shore():
    img = _land_water(NAVY)
    assert _sides(img, 25)[0] < 0.1       # poziomica nad brzegiem (ląd po obu stronach)
    assert _sides(img, 95)[0] < 0.1       # poziomica w wodzie


def test_side_votes_ignores_beige_track_symbol_on_land():
    img = _land_water(NAVY)
    img[20:24, :] = (190, 180, 150)       # beżowy symbol drogi gruntowej, ląd po obu stronach linii y=22
    assert _sides(img, 22)[0] < 0.1


def test_drop_outer_parallels_keeps_line_nearer_reference():
    from shapely.geometry import LineString
    ref = LineString([(0, 0), (1000, 0)])
    inner = LineString([(0, 20), (500, 20)])
    outer = LineString([(0, 30), (500, 30)])
    far = LineString([(0, 200), (500, 200)])
    keep = kz.drop_outer_parallels([outer, inner, far], ref, tol_m=12)
    assert keep == [False, True, True]


def test_match_drops_by_centroid_not_rank():
    from shapely.geometry import LineString
    lines = [LineString([(0, 0), (100, 0)]), LineString([(0, 500), (100, 500)])]
    drops = [{"x": 52.0, "y": 505.0, "length_m": 100.0}]
    assert kz.match_drops(lines, drops, tol_m=20) == [False, True]
    assert kz.match_drops(lines, [{"x": 52.0, "y": 560.0, "length_m": 100.0}], tol_m=20) == [False, False]


def test_vertices_to_polygon_warns_on_repair(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        kz.vertices_to_polygon([(0, 0), (100, 100), (100, 0), (0, 100)], T_AFFINE)
    assert "naprawiono" in caplog.text


def test_side_votes_land_vs_land_with_slightly_different_greens_is_not_shore():
    img = np.zeros((120, 300, 3), np.uint8)
    img[:60] = (152, 200, 120)
    img[60:] = (208, 232, 184)            # jasna zieleń niska (dno z roślinnością) to dla nas ląd: nie rozstrzygamy
    img[59:62, :] = NAVY
    assert _sides(img, 60)[0] < 0.1


def test_axis_aligned_lines_are_grid_not_contours():
    assert kz.is_axis_aligned(np.array([[100, 5], [100, 400]])) and kz.is_axis_aligned(np.array([[5, 77], [300, 78.5]]))
    assert not kz.is_axis_aligned(np.array([[0, 0], [200, 30], [400, 0]]))


def test_long_straight_line_is_not_a_contour_but_a_wiggly_one_is():
    x = np.arange(0, 400.0)
    assert kz.is_straight(np.column_stack([x, 0.2 * x]))
    assert not kz.is_straight(np.column_stack([x, 40 * np.sin(x / 40)]))
    assert not kz.is_straight(np.column_stack([x[:100], 0.2 * x[:100]]))     # krótka: nie rozstrzygamy
