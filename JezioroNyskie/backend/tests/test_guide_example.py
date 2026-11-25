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


# ---------------- Przykład B: piksel „zawsze woda” z dnem z mapy KŻ ----------------

DATA = Path(__file__).resolve().parents[2] / "data" / "processed"
# wartości z calibration.json i model/all_kz/meta.json zaokrąglone do 0,01 m, jak w przewodniku
DELTAS_B = {"<192.9": {"delta_lo": 0.0, "delta_hi": 0.0},
            "192.9-194.8": {"delta_lo": 0.11, "delta_hi": 2.23},
            "194.8+": {"delta_lo": 1.83, "delta_hi": 0.71}}
P5_B, P95_B, KZ_B, H_B = -2.00, 3.02, 190.0, 194.5


@pytest.fixture(scope="module")
def example_b():
    calibration = pytest.importorskip("mielizna.calibration")
    combine = pytest.importorskip("mielizna.combine")
    sat = depth.satellite_bounds(np.array([[np.nan]]), np.array([[193.05]]),
                                 np.array([[150]], dtype=np.uint16), np.array([[1]], dtype=np.uint8))
    lo_c, hi_c = calibration.apply(sat.z_lo, sat.z_hi, DELTAS_B)
    out = {}
    for name, kz in (("kz", KZ_B), ("no_kz", np.nan)):
        lo, hi, src, conf = combine.merge_kz(lo_c, hi_c, np.array([[kz]]), P5_B, P95_B)
        out[name] = (lo, hi, src, conf)
    return sat, (lo_c, hi_c), out


def test_example_b_calibration(example_b):
    sat, (lo_c, hi_c), _ = example_b
    assert sat.z_lo[0, 0] == -np.inf and sat.z_hi[0, 0] == pytest.approx(193.05)
    assert lo_c[0, 0] == -np.inf and hi_c[0, 0] == pytest.approx(195.28)


def test_example_b_kz_merge_depth_zone_kind(example_b):
    _, _, out = example_b
    lo, hi, src, conf = out["kz"]
    assert lo[0, 0] == pytest.approx(186.98) and hi[0, 0] == pytest.approx(192.00)
    assert src[0, 0] == depth.SOURCE_KZ and not conf[0, 0]
    b = depth.Bounds.from_arrays(lo, hi, [[True]])
    d_lo, d_hi = depth.depth_range(H_B, b.z_lo, b.z_hi)
    assert d_lo[0, 0] == pytest.approx(2.50) and d_hi[0, 0] == pytest.approx(7.52)
    assert depth.classify(H_B, 0.5, 0.3, b)[0, 0] == depth.SAFE
    assert depth.point_kind(H_B, lo[0, 0]) == "model"


def test_example_b_without_kz_and_without_calibration(example_b):
    sat, _, out = example_b
    lo, hi, src, _ = out["no_kz"]
    assert lo[0, 0] == -np.inf and hi[0, 0] == pytest.approx(195.28) and src[0, 0] == depth.SOURCE_SATELLITE
    b = depth.Bounds.from_arrays(lo, hi, [[True]])
    d_lo, d_hi = depth.depth_range(H_B, b.z_lo, b.z_hi)
    assert d_lo[0, 0] == pytest.approx(-0.78) and d_hi[0, 0] == np.inf
    assert depth.classify(H_B, 0.5, 0.3, b)[0, 0] == depth.RISK
    assert depth.point_kind(H_B, lo[0, 0]) == "always_water"
    raw = depth.depth_range(H_B, sat.z_lo, sat.z_hi)[0][0, 0]
    assert raw == pytest.approx(1.45) and depth.classify(H_B, 0.5, 0.3, sat)[0, 0] == depth.SAFE


def test_example_b_inputs_match_data_files():
    """Zaokrąglone wejścia przykładu B odpowiadają prawdziwym plikom (pomijane bez danych)."""
    import json
    cal, meta = DATA / "eval" / "calibration.json", DATA / "model" / "all_kz" / "meta.json"
    if not (cal.exists() and meta.exists()):
        pytest.skip("brak danych (poza gitem)")
    bands = json.loads(cal.read_text(encoding="utf-8"))["bands"]
    for b in ("192.9-194.8", "194.8+"):
        for k in ("delta_lo", "delta_hi"):
            assert round(bands[b][k], 2) == DELTAS_B[b][k]
    m = json.loads(meta.read_text(encoding="utf-8"))
    assert round(m["p5"], 2) == P5_B and round(m["p95"], 2) == P95_B


def test_guide_contains_example_b_numbers():
    text = GUIDE.read_text(encoding="utf-8")
    for s in ["`δ_hi = 2,23`", "`P5 = −2,00`", "`P95 = +3,02`", "`kz = 190,0`", "193,05 + 2,23 = 195,28",
              "190,0 − 3,02 = 186,98", "min(195,28; 190,0 + 2,00) = 192,00", "2,50", "7,52", "**SAFE**",
              "194,5 − 195,28 = −0,78", "**RISK**", "`D_lo = 1,45` m", "combine.merge_kz", "calibration.apply"]:
        assert s in text, s
