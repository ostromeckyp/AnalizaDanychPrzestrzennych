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


def test_spot_anchor_none_without_dot_or_dot_on_right():
    img = _canvas()
    for x in (32, 42, 52):
        img[20:34, x:x + 6] = (0, 0, 150)
    assert kz.spot_anchor(img, (30, 18, 40, 18)) is None
    img[30:34, 62:66] = (0, 0, 150)             # kropka z PRAWEJ strony
    assert kz.spot_anchor(img, (30, 18, 40, 18)) is None


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
