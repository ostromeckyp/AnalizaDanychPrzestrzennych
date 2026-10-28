"""Testy mielizna.datum: przesunięcie KRON86 -> EVRF2007 z siatek quasi-geoidy GUGiK (bez sieci)."""
import pytest

from mielizna import datum


def test_offset_from_geoid_heights():
    # H_evrf = h - N_evrf, H_kron = h - N_kron  =>  H_evrf - H_kron = N_kron - N_evrf
    assert datum.offset_from_geoid(41.768, 41.577) == pytest.approx(0.191)


@pytest.fixture
def proj_offline():
    """Sieć PROJ wyłączona na czas testu (test ma działać tylko z lokalnych siatek), potem przywrócona."""
    from pyproj import network
    was = network.is_network_enabled()
    network.set_network_enabled(False)
    datum._geoid_transformer.cache_clear()          # transformator z poprzedniego ustawienia sieci nie może przeżyć
    try:
        yield
    finally:
        network.set_network_enabled(was)
        datum._geoid_transformer.cache_clear()


def test_proj_offline_fixture_disables_network(proj_offline):
    from pyproj import network
    assert network.is_network_enabled() is False


def test_kron_to_evrf_offset_magnitude(proj_offline):
    try:
        off = datum.kron86_to_evrf2007(376000, 289000)
    except datum.GridsMissing as e:
        pytest.skip(f"brak siatek PROJ GUGiK (offline, bez cache): {e}")
    assert 0.05 <= abs(off) <= 0.30          # BRIEF: "rzędu kilkunastu cm"
