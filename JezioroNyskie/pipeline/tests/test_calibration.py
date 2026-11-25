import json

import numpy as np

from mielizna import calibration

INF = np.inf


def test_deltas_p95_and_empty_band():
    r = np.arange(100.0)
    d = calibration.deltas({"192.9-194.8": r, "194.8+": np.array([])}, {"192.9-194.8": r * 2, "194.8+": np.array([])})
    assert d["192.9-194.8"]["delta_lo"] == np.percentile(r, 95)
    assert d["192.9-194.8"]["delta_hi"] == np.percentile(r * 2, 95)
    assert d["192.9-194.8"]["n"] == 100
    for b in ("194.8+", "<192.9"):
        assert d[b]["delta_lo"] == 0 and d[b]["delta_hi"] == 0 and d[b]["note"].startswith("brak pikseli")
    json.dumps(d, allow_nan=False)


D = {"<192.9": {"delta_lo": 0.0, "delta_hi": 0.0}, "192.9-194.8": {"delta_lo": 0.1, "delta_hi": 0.2},
     "194.8+": {"delta_lo": 0.3, "delta_hi": 0.4}}


def test_apply_bands_and_infinities():
    lo = np.array([193.0, 195.0, -INF, 192.0, -INF, np.nan, 193.0])
    hi = np.array([194.0, 196.0, 195.0, 192.5, INF, np.nan, INF])
    a, b = calibration.apply(lo, hi, D)
    assert np.allclose(a[0], 192.9) and np.allclose(b[0], 194.2)
    assert np.allclose(a[1], 194.7) and np.allclose(b[1], 196.4)
    assert a[2] == -INF and np.allclose(b[2], 195.4)  # pasmo wg z_hi (>= 194.8)
    assert np.allclose(a[3], 191.9) and np.allclose(b[3], 192.7)  # < 192.9 pożycza 192.9-194.8
    assert a[4] == -INF and b[4] == INF
    assert np.isnan(a[5]) and np.isnan(b[5])
    assert np.allclose(a[6], 192.9) and b[6] == INF  # pasmo wg z_lo


def test_coverage_before_after():
    lo = {"192.9-194.8": np.array([0, 0, 1.0, 0]), "194.8+": np.array([0, 0.0])}
    hi = {"192.9-194.8": np.array([0, 0.5, 0, 0]), "194.8+": np.array([0, 0.0])}
    d = calibration.deltas(lo, hi, q=100)
    c = calibration.coverage(lo, hi, d)
    assert c["bands"]["192.9-194.8"]["before"] == 0.5 and c["bands"]["192.9-194.8"]["after"] == 1.0
    assert c["overall"]["before"] == 4 / 6 and c["overall"]["after"] == 1.0
    assert c["bands"]["<192.9"]["after"] is None
