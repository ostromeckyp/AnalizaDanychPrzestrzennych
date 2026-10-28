"""Testy georeferencji mapy KŻ: dopasowanie afiniczne/wielomianowe, werdykt, ekstrakcja obrazu (bez sieci)."""
import numpy as np
import pandas as pd
import pyproj
import pytest

from mielizna import kz

TO_WGS = pyproj.Transformer.from_crs(2180, 4326, always_xy=True)
RNG_SEED = 7


def synthetic_gcp(affine=None, poly2=None, noise_px=0.0, n_fit=12, n_check=4, w=9867, h=4791):
    """GCP z znanej transformacji piksel -> EPSG:2180 (+ szum w pikselach); lon/lat liczone odwrotnie."""
    rng = np.random.default_rng(RNG_SEED)
    n = n_fit + n_check
    px = rng.uniform(0, w, n)
    py = rng.uniform(0, h, n)
    if affine is not None:
        a, b, c, d, e, f = affine
        x = a * px + b * py + c
        y = d * px + e * py + f
    else:
        x, y = poly2(px, py)
    px_obs = px + rng.normal(0, noise_px, n)
    py_obs = py + rng.normal(0, noise_px, n)
    lon, lat = TO_WGS.transform(x, y)
    role = ["fit"] * n_fit + ["check"] * n_check
    return pd.DataFrame({"id": range(n), "px": px_obs, "py": py_obs, "lon": lon, "lat": lat, "role": role})


A_TRUE = (0.95, 0.02, 372500.0, 0.015, -0.95, 292000.0)


def P_TRUE(px, py):
    # afiniczna + wyraźna krzywizna (zniekształcenie rzutu / skan)
    x = 0.95 * px + 0.02 * py + 372500 + 2.0e-5 * px * py + 3.0e-5 * px ** 2
    y = 0.015 * px - 0.95 * py + 292000 + 2.5e-5 * py ** 2 - 1.5e-5 * px * py
    return x, y


def test_affine_recovers_known_transform():
    gcp = synthetic_gcp(affine=A_TRUE, noise_px=0.5, n_fit=12, n_check=4)
    t = kz.fit_transform(gcp, "affine")
    assert t.rmse_check < 2.0
    x, y = t.px_to_2180(np.array([100.0]), np.array([200.0]))
    assert abs(x[0] - (0.95 * 100 + 0.02 * 200 + 372500)) < 3
    assert abs(y[0] - (0.015 * 100 - 0.95 * 200 + 292000)) < 3


def test_poly2_beats_affine_on_curved_distortion():
    gcp = synthetic_gcp(poly2=P_TRUE, n_fit=16, n_check=6)
    assert kz.fit_transform(gcp, "poly2").rmse_check < kz.fit_transform(gcp, "affine").rmse_check


def test_inverse_roundtrip():
    gcp = synthetic_gcp(poly2=P_TRUE, n_fit=16, n_check=6)
    t = kz.fit_transform(gcp, "poly2")
    px, py = np.array([500.0, 5000.0, 9000.0]), np.array([300.0, 2400.0, 4500.0])
    x, y = t.px_to_2180(px, py)
    qx, qy = t.inverse_2180(x, y)
    assert np.allclose(qx, px, atol=0.5) and np.allclose(qy, py, atol=0.5)


def test_verdict_thresholds():
    assert kz.verdict(4.9) == "good" and kz.verdict(9.9) == "acceptable" and kz.verdict(10.1) == "aggregated_only"


def test_fit_needs_enough_points():
    gcp = synthetic_gcp(affine=A_TRUE, n_fit=4, n_check=2)
    with pytest.raises(ValueError):
        kz.fit_transform(gcp, "poly2")


def test_extract_image_roundtrip(tmp_path):
    from PIL import Image
    from pypdf import PdfWriter
    im = Image.new("RGB", (120, 60), (10, 200, 30))
    pdf = tmp_path / "k.pdf"
    im.save(pdf, "PDF")
    out = tmp_path / "k.png"
    assert kz.extract_image(pdf, out) == (120, 60)
    assert Image.open(out).size == (120, 60)


def test_band_centre_finds_band_despite_neighbouring_dark_feature():
    d = np.arange(-60, 61, 2.0)
    prof = np.full(d.shape, 210.0)
    prof[(d >= -3) & (d <= 21)] = 140.0          # pas zapory o środku +9 m, szerokość 24 m
    prof[(d >= -52) & (d <= -44)] = 120.0        # ciemniejsza droga obok (nie zapora)
    c = kz.band_centre(prof, d, width_m=24.0, max_shift_m=30.0)
    assert abs(c - 9.0) <= 2.0


def test_band_centre_none_on_flat_profile():
    d = np.arange(-60, 61, 2.0)
    assert kz.band_centre(np.full(d.shape, 200.0), d, width_m=24.0, max_shift_m=30.0) is None
