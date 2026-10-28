"""Testy mielizna.datum: przesunięcie KRON86 -> EVRF2007 z siatek quasi-geoidy GUGiK (bez sieci)."""
import pytest

from mielizna import datum


def test_offset_from_geoid_heights():
    # H_evrf = h - N_evrf, H_kron = h - N_kron  =>  H_evrf - H_kron = N_kron - N_evrf
    assert datum.offset_from_geoid(41.768, 41.577) == pytest.approx(0.191)


def test_kron_to_evrf_offset_magnitude():
    try:
        off = datum.kron86_to_evrf2007(376000, 289000)
    except datum.GridsMissing as e:
        pytest.skip(f"brak siatek PROJ GUGiK (offline, bez cache): {e}")
    assert 0.05 <= abs(off) <= 0.30          # BRIEF: "rzędu kilkunastu cm"
