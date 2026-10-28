"""Testy OCR rzędnych z mapy KŻ: parsowanie, kolor, kropka-kotwica, kafle, błąd ważony warstwami."""
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from mielizna import kz

FIX = Path(__file__).parent / "fixtures"
needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="brak tesseract w PATH")


def load(name):
    return np.asarray(Image.open(FIX / name).convert("RGB"))


@pytest.mark.parametrize("s,z", [("194,3", 194.3), (".193,5", 193.5), ("1943", None), ("201,0", None),
                                 ("abc", None), ("184,9", None), ("200,0", 200.0), ("185,0", 185.0),
                                 ("196,0.", 196.0), ("194.3", None)])
def test_parse_spot(s, z):
    assert kz.parse_spot(s) == z


def test_color_rule():
    assert kz.color_consistent(194.9, "blue") and not kz.color_consistent(195.2, "blue")
    assert kz.color_consistent(195.0, "black") and not kz.color_consistent(194.0, "black")
    assert not kz.color_consistent(194.0, "other")


def _canvas(bg=(200, 240, 250)):
    return np.full((60, 120, 3), bg, np.uint8)


def test_spot_anchor_finds_dot_left_of_number():
    img = _canvas()
    img[30:34, 20:24] = (0, 0, 150)             # kropka 4x4, środek (21.5, 31.5)
    for x in (32, 42, 52):                       # trzy "cyfry" 6 x 14 px
        img[20:34, x:x + 6] = (0, 0, 150)
    ax, ay = kz.spot_anchor(img, (20, 18, 40, 18))
    assert (ax, ay) == pytest.approx((21.5, 31.5), abs=0.6)


def _number(img, x=32, y=20):
    """Trzy „cyfry” 6 x 14 px; zwraca ramkę (left, top, width, height) jak z OCR."""
    for k in range(3):
        img[y:y + 14, x + 10 * k:x + 10 * k + 6] = (0, 0, 150)
    return (x, y - 2, 26, 16)


def _dot(img, x, y):
    img[y:y + 4, x:x + 4] = (0, 0, 150)
    return x + 1.5, y + 1.5


def _canvas2(h=100):
    return np.full((h, 120, 3), (200, 240, 250), np.uint8)


def test_spot_anchor_none_without_any_dot():
    img = _canvas()
    assert kz.spot_anchors(img, [_number(img)]) == [None]


@pytest.mark.parametrize("dx,dy,side", [(42, 8, "above"), (66, 28, "right"), (42, 38, "below"), (22, 31, "left")])
def test_spot_anchor_any_side(dx, dy, side):
    img = _canvas2()
    box = _number(img)
    cx, cy = _dot(img, dx, dy)
    (x, y, sd), = kz.spot_anchors(img, [box])
    assert sd == side and (x, y) == pytest.approx((cx, cy), abs=0.6)


def test_spot_anchor_dot_too_far_is_none():
    img = _canvas2()
    box = _number(img)
    _dot(img, 20, 80)                       # 40+ px pod liczbą, promień = 1,5 x 16 = 24 px
    assert kz.spot_anchors(img, [box]) == [None]


def test_spot_anchor_ambiguous_two_dots_rejected():
    img = _canvas2()
    box = _number(img)
    _dot(img, 22, 31)                       # po lewej (odległość ~8)
    _dot(img, 66, 31)                       # po prawej (odległość ~8): stosunek < 1,3
    assert kz.spot_anchors(img, [box]) == [None]


def test_spot_anchor_clearly_nearer_dot_wins():
    img = _canvas2()
    box = _number(img)
    _dot(img, 25, 31)                       # blisko po lewej
    _dot(img, 80, 31)                       # daleko po prawej
    (x, y, sd), = kz.spot_anchors(img, [box])
    assert sd == "left" and x < 30


def test_shared_dot_goes_to_nearer_number_only():
    img = _canvas2(110)
    a = _number(img, 32, 20)
    b = _number(img, 32, 70)
    _dot(img, 20, 42)                       # kropka bliżej pierwszej liczby (a)
    ra, rb = kz.spot_anchors(img, [a, b])
    assert ra is not None and rb is None


def test_shared_dot_equidistant_rejects_both():
    img = _canvas2(110)
    a = _number(img, 32, 20)
    b = _number(img, 32, 62)
    _dot(img, 20, 44)                       # w połowie drogi między liczbami
    assert kz.spot_anchors(img, [a, b]) == [None, None]


def test_dot_inside_other_word_box_is_ignored():
    img = _canvas2()
    box = _number(img)
    _dot(img, 66, 31)                       # to przecinek cudzego słowa
    assert kz.spot_anchors(img, [box], others=[(60, 25, 20, 12)]) == [None]


def test_text_color():
    for rgb, want in [((0, 0, 150), "blue"), ((0, 0, 0), "black"), ((220, 40, 200), "other"), ((0, 110, 20), "other")]:
        img = _canvas()
        img[20:34, 30:36] = rgb
        img[20:34, 40:46] = rgb
        assert kz.text_color(img, (28, 18, 20, 18)) == want


@needs_tesseract
def test_ocr_on_crop_finds_known_spots():
    # wartości odczytane okiem z wycinka (niebieskie < 195,0: 189,5 187,6 188,3 188,2 187,9 188,0 188,4 188,6)
    df = kz.ocr_tiles(load("kz_crop.png"))
    assert list(df.columns) == ["text", "conf", "left", "top", "width", "height"]
    zs = {kz.parse_spot(t) for t in df.text} - {None}
    known = {189.5, 187.6, 188.3, 188.2, 187.9, 188.0, 188.4, 188.6}
    assert len(zs & known) >= 3, zs


@needs_tesseract
def test_ocr_tiles_overlap_has_no_duplicates():
    df = kz.ocr_tiles(load("kz_crop.png"), tile=300, overlap=60)
    spots = df[df.text.map(kz.parse_spot).notna()]
    c = np.column_stack([spots.left + spots.width / 2, spots.top + spots.height / 2])
    d = np.hypot(c[:, None, 0] - c[None, :, 0], c[:, None, 1] - c[None, :, 1]) + np.eye(len(c)) * 1e9
    assert (d > 8).all()


def _qc(n_sus, err_sus, n_reg, err_reg, n_skip=5):
    rows = []
    for stratum, n, err in (("sus", n_sus, err_sus), ("reg", n_reg, err_reg)):
        for i in range(n):
            q = ("corrected" if i % 2 else "rejected") if i < err else "ok"
            rows.append((f"{stratum}{i}", 194.0, q, 194.5 if q == "corrected" else np.nan))
    rows += [(f"skip{i}", 194.0, "skip", np.nan) for i in range(n_skip)]
    return pd.DataFrame(rows, columns=["id", "ocr_z", "qc", "z_qc"])


def test_error_rate_is_stratum_weighted():
    """Populacja 1000 punktów: 100 podejrzanych (10 %) i 900 zwykłych. Próba 100 + 100 (po 50 %): podejrzane
    mylą się w 40 %, zwykłe w 2 %. Surowy udział błędów = 42/200 = 0,21, a ważony warstwami
    = 0,10 * 0,40 + 0,90 * 0,02 = 0,058 (waga = udział warstwy w populacji / udział w próbie)."""
    qc = _qc(100, 40, 100, 2)
    ocr = pd.DataFrame({"id": [f"sus{i}" for i in range(100)] + [f"reg{i}" for i in range(100)] + [f"skip{i}" for i in range(5)],
                        "color_ok": [False] * 100 + [True] * 105, "conf": 90.0})
    population = pd.DataFrame({"color_ok": [False] * 100 + [True] * 900, "conf": 90.0})
    rate, n = kz.ocr_error_rate(qc.merge(ocr[["id", "color_ok", "conf"]], on="id"), population)
    assert n == 200                                            # skip nie liczy się do ocenionych
    assert rate == pytest.approx(0.058, abs=1e-9)
    unweighted = (qc.qc.isin(["corrected", "rejected"]).sum()) / 200
    assert unweighted == pytest.approx(0.21) and abs(rate - unweighted) > 0.1
    assert abs(rate - 0.06) <= 0.01


def test_stratum_rule():
    d = pd.DataFrame({"color_ok": [True, False, True, True], "conf": [95, 95, 70, 80]})
    assert list(kz.is_suspect(d)) == [False, True, True, False]


def test_comma_tail_below_box_is_not_an_anchor():
    img = _canvas2()
    box = _number(img)                       # ramka (32, 18, 26, 16): dół ramki y = 34
    _dot(img, 46, 36)                        # ogonek przecinka wystaje 0-4 px pod ramkę, nad drugą cyfrą
    assert kz.spot_anchors(img, [box]) == [None]


def test_dot_below_beyond_comma_tail_is_still_an_anchor():
    img = _canvas2()
    box = _number(img)
    cx, cy = _dot(img, 46, 44)               # 10 px pod ramką > 0,3 x wysokość
    (x, y, sd), = kz.spot_anchors(img, [box])
    assert sd == "below" and (x, y) == pytest.approx((cx, cy), abs=0.6)


def test_shared_blob_clipped_by_different_windows_is_still_one_dot():
    """Kropka przecięta oknem poszukiwań jednej liczby ma dla drugiej inny środek; kluczem jest cała kropka."""
    img = _canvas2(120)
    a = _number(img, 32, 20)                 # ramka (32,18,26,16), okno kończy się na y = 58
    b = _number(img, 32, 76)                 # ramka (32,74,26,16), bliżej kropki
    img[55:61, 20:26] = (0, 0, 150)          # kropka 6x6 przecięta oknem A
    ra, rb = kz.spot_anchors(img, [a, b])
    assert ra is None and rb is not None


def test_lake_zone_filter_fills_island_holes_and_buffers():
    from shapely.geometry import Polygon

    lake = Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)], holes=[[(400, 400), (600, 400), (600, 600), (400, 600)]])
    x = np.array([500.0, 1050.0, 1200.0, -50.0])
    y = np.array([500.0, 500.0, 500.0, 500.0])
    assert list(kz.in_lake_zone(x, y, lake, buffer_m=100)) == [True, True, False, True]   # wyspa w środku zostaje


def test_match_qc_survives_renumbering():
    spots = pd.DataFrame({"id": [0, 1, 2], "z": [188.0, 189.0, 190.0], "px": [10.0, 50.0, 90.0], "py": [5.0, 5.0, 5.0]})
    qc = pd.DataFrame({"id": [7, 8, 9], "ocr_z": [189.0, 190.0, 188.0], "qc": ["ok", "rejected", "ok"], "z_qc": [np.nan] * 3,
                       "px": [51.0, 90.5, 300.0], "py": [5.5, 4.0, 5.0]})        # trzeci: brak punktu w pobliżu
    out, dropped = kz.match_qc(qc, spots)
    assert dict(zip(out.id, out.qc)) == {1: "ok", 2: "rejected"} and dropped == 1
    qc2 = qc.assign(ocr_z=[189.0, 191.0, 188.0])                                  # ten sam punkt, inna rzędna -> odrzucony
    assert kz.match_qc(qc2, spots)[1] == 2


def test_red_marker_is_not_a_dot():
    img = _canvas2()
    box = _number(img)
    img[31:35, 22:26] = (220, 30, 30)       # czerwony krzyżyk komunikatu w miejscu kropki
    assert kz.spot_anchors(img, [box]) == [None]
