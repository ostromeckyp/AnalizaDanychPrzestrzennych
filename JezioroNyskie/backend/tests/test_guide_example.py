"""Przykład A z `docs/jak-czytac-kod.md` policzony prawdziwym kodem (pipeline `compute_bounds` + `depth.py`).

Co robi: odtwarza piksel z czterema scenami, sprawdza przedział dna, głębokość, strefę i rodzaj punktu,
  oraz że te same liczby (jako tekst) stoją w przewodniku.
Dlaczego tak: liczby w dokumentacji nie mogą się rozjechać z kodem.
Wejście → wyjście: stałe sceny → liczby z przewodnika; zmiana reguły w kodzie albo tekstu przewodnika psuje test.
Jak to obronić: asercje są literałami z przewodnika, a nie przeliczeniem tą samą formułą.
"""
from pathlib import Path

import numpy as np
import pytest

from app import depth

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "jak-czytac-kod.md"


@pytest.fixture(scope="module")
def example():
    bottom = pytest.importorskip("mielizna.bottom")
    h = np.array([194.9, 194.2, 195.6, 193.8])
    sigma = np.array([0.15, 0.15, 0.40, 0.15])
    is_c = np.array([False, False, True, False])
    masks = np.array([1, 0, 1, 0], dtype=np.uint8).reshape(4, 1, 1)     # 1 woda, 0 ląd
    r = bottom.compute_bounds(masks, h, sigma, is_c, k_sigma=1.0)
    b = depth.satellite_bounds(r["z_min"], r["z_max"], r["obs_count"], r["flags"])
    return r, b


def test_bounds_from_compute_bounds(example):
    bottom = pytest.importorskip("mielizna.bottom")
    r, _ = example
    assert r["z_min_raw"][0, 0] == pytest.approx(194.2)
    assert r["z_max_raw"][0, 0] == pytest.approx(194.9)
    assert r["z_min"][0, 0] == pytest.approx(194.05)
    assert r["z_max"][0, 0] == pytest.approx(195.05)
    assert r["n_conflict"][0, 0] == 0
    assert r["flags"][0, 0] == bottom.FLAG_C_WATER_IGNORED == 8


def test_depth_zone_and_kind(example):
    _, b = example
    assert b.in_model[0, 0] and b.z_lo[0, 0] == pytest.approx(194.05) and b.z_hi[0, 0] == pytest.approx(195.05)
    d_lo, d_hi = depth.depth_range(195.5, b.z_lo, b.z_hi)
    assert d_lo[0, 0] == pytest.approx(0.45) and d_hi[0, 0] == pytest.approx(1.45)
    assert depth.classify(195.5, 0.5, 0.3, b)[0, 0] == depth.RISK
    assert depth.point_kind(195.5, b.z_lo[0, 0]) == "model"


def test_guide_contains_the_numbers():
    text = GUIDE.read_text(encoding="utf-8")
    for s in ["194,05", "195,05", "0,45", "1,45", "**RISK**", "`z_min_raw = 194,2`", "`z_max_raw = 194,9`", "flaga 8"]:
        assert s in text
