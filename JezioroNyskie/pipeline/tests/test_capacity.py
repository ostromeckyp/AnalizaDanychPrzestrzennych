import numpy as np

from mielizna.capacity import capacity_to_level, level_to_capacity, load_table


def test_table_shape_and_ends():
    t = load_table()
    assert len(t) == 66
    assert t.iloc[0].tolist() == [18.0, 192.4]
    assert t.iloc[-1].tolist() == [122.0, 198.9]
    assert t.pojemnosc_mln_m3.is_monotonic_increasing
    assert np.allclose(np.diff(t.rzedna_m_npm), 0.1, atol=1e-6)


def test_known_points():
    assert abs(capacity_to_level(65.69) - 195.9) <= 0.05  # NPP wg KŻ
    assert abs(capacity_to_level(121.70) - 198.9) <= 0.05  # Max PP wg KŻ
    assert 194.5 <= capacity_to_level(45.62) <= 194.7  # interpelacja 12.09.2024
    assert np.isnan(capacity_to_level(10.0))
    assert abs(level_to_capacity(capacity_to_level(50.0)) - 50.0) < 1e-6


def test_explicit_table_matches_default():
    t = load_table()
    assert capacity_to_level(65.69, table=t) == capacity_to_level(65.69)
    assert level_to_capacity(195.0, table=t) == level_to_capacity(195.0)
    assert np.isnan(capacity_to_level(10.0, table=t))


def test_npp_and_max_pp_constants_live_in_capacity_and_are_shared():
    """Jedno źródło stałych brief §4 (backend i porównanie KŻ importują je stąd)."""
    from mielizna import capacity, kz_compare
    assert capacity.NPP_MLN_M3 == 65.69 and capacity.MAX_PP_MLN_M3 == 121.70
    assert kz_compare.NPP_MLN_M3 is capacity.NPP_MLN_M3
