import numpy as np
import pytest

from mielizna import volume


def _model(z, zmin, zmax, flags=None):
    z, zmin, zmax = (np.array(a, dtype="float32") for a in (z, zmin, zmax))
    return {"z": z, "z_min": zmin, "z_max": zmax,
            "flags": np.zeros(z.shape, "uint8") if flags is None else np.array(flags, "uint8")}


def test_bounds_map_nan_to_infinities_and_core():
    # piksele: rdzeń (zawsze woda), przedział, zawsze ląd, poza modelem
    b = volume.bottom_bounds(_model([np.nan, 194.0, np.nan, np.nan],
                                    [np.nan, 193.5, 197.0, np.nan],
                                    [193.0, 194.5, np.nan, np.nan], flags=[1, 0, 2, 255]))
    assert b["core"].tolist() == [True, False, False, False]
    assert b["mid"][0] == -np.inf and b["mid"][1] == 194.0 and b["mid"][2] == np.inf and np.isnan(b["mid"][3])
    assert b["low"][0] == -np.inf and b["high"][2] == np.inf


def test_layer_volume_full_partial_and_empty_pixels():
    zb = np.array([-np.inf, 194.0, np.inf, np.nan])
    # warstwa 193.5–194.5: rdzeń 1.0 m, piksel z dnem 194.0 0.5 m, ląd 0, NaN pominięty
    assert volume.layer_volume(zb, 193.5, 194.5) == pytest.approx(1.5 * 100 / 1e6)


def test_layer_table_bounds_order():
    b = volume.bottom_bounds(_model([np.nan, 194.0], [np.nan, 193.6], [193.0, 194.4]))
    row = volume.layer_table(b, lambda h: 2.0 * h, [193.5, 194.5])[0]
    assert row["dv_model_min"] <= row["dv_model"] <= row["dv_model_max"]
    assert row["dv_table"] == pytest.approx(2.0)


def test_core_bottom_recovers_known_depth():
    # 10 pikseli rdzenia o dnie 190 m i 10 pikseli z dnem 194 m; tabela „prawdziwa” przy h = 195
    n = 10
    b = volume.bottom_bounds(_model([np.nan] * n + [194.0] * n, [np.nan] * n + [193.8] * n, [193.0] * n + [194.2] * n))
    v_true = (n * 5.0 + n * 1.0) * 100 / 1e6
    res = volume.core_bottom(b, 195.0, v_true)
    assert res["z_core_mean"] == pytest.approx(190.0)
    assert res["area_core_km2"] == pytest.approx(n * 100 / 1e6)
