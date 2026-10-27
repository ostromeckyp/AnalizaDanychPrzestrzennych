import numpy as np
import pytest


def test_load_products_semantics(products):
    p = products
    assert p.shape == (20, 30) and p.crs == "EPSG:2180"
    assert p.in_model[:, :25].all() and not p.in_model[:, 25:].any()
    assert np.isneginf(p.z_lo[0, 15]) and p.z_hi[0, 15] == pytest.approx(193.05)
    assert np.isposinf(p.z_hi[0, 22])
    assert p.version == "all-testver00001"
    assert [s["date"] for s in p.scenes] == sorted(s["date"] for s in p.scenes) and len(p.scenes) == 2
    assert set(p.shorelines.index) <= {s["date"] for s in p.scenes}
    assert p.z_max_floor == pytest.approx(193.05)
    assert p.npp == pytest.approx(195.91, abs=0.01) and p.max_pp == pytest.approx(198.89, abs=0.01)
