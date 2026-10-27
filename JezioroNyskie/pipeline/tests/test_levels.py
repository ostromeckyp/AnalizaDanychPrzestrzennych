import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from mielizna.config import data_path
from mielizna.levels import (assign_levels, fit_area_level, load_area_level_curve, load_overrides,
                             save_area_level_curve, variant_b, variant_c, write_scenes_json)

KNOWN_CSV = data_path("reference", "known_levels.csv")


def bulletin(scene_date, v, v_npp=66.3):
    return {"scene_date": scene_date, "bulletin_date": scene_date, "source": "wayback", "v_current": v,
            "v_npp": v_npp, "v_maxpp": 122.1, "reading_utc": "06:00", "url": "x"}


def test_curve_is_monotonic_and_flags_extrapolation():
    c = fit_area_level(np.array([10, 12, 14, 16, 18.]), np.array([192, 193, 194, 195, 196.]))
    hs = [c(a)[0] for a in np.linspace(10, 18, 50)]
    assert np.all(np.diff(hs) >= 0)
    assert c(20.0)[1] is True and c(15.0)[1] is False


def test_curve_monotonic_on_noisy_input():
    c = fit_area_level(np.array([10, 11, 12, 13, 14, 15.]), np.array([192, 192.6, 192.4, 193.5, 193.3, 194.]))
    hs = [c(a)[0] for a in np.linspace(10, 15, 50)]
    assert np.all(np.diff(hs) >= -1e-9)


def test_curve_extrapolates_linearly_and_has_loo_rmse():
    rng = np.random.default_rng(0)
    a = np.linspace(10, 18, 40)
    c = fit_area_level(a, 192 + 0.5 * (a - 10) + rng.normal(0, 0.05, a.size))
    h20, extrap = c(20.0)
    assert extrap and abs(h20 - (192 + 0.5 * 10)) < 0.3
    assert 0 < c.rmse < 0.15


def test_curve_json_roundtrip(tmp_path):
    c = fit_area_level(np.array([10, 12, 14, 16, 18.]), np.array([192, 193, 194, 195, 196.]))
    save_area_level_curve(c, tmp_path / "c.json")
    d = json.loads((tmp_path / "c.json").read_text())
    assert d["method"] == "isotonic+pchip" and d["extrapolation"] == "linear_last3"
    assert {"area_km2", "h", "area_min", "area_max", "n_points", "rmse_loo"} <= set(d)
    c2 = load_area_level_curve(tmp_path / "c.json")
    assert c2(15.0) == c(15.0) and c2(20.0) == c(20.0)


def test_known_level_overrides_bulletin():
    df = assign_levels([date(2025, 4, 28)], pd.DataFrame([bulletin("2025-04-28", 90.0)]), load_overrides(KNOWN_CSV))
    assert df.iloc[0].h_t == 197.92 and df.iloc[0].h_method == "R"


def test_variant_b_uses_capacity_and_notes_regime():
    b = variant_b(pd.DataFrame([bulletin("2020-01-08", 34.84), bulletin("2023-01-02", 50.0, 65.7)]))
    assert (b.h_method == "B").all() and (b.h_sigma == 0.15).all()
    assert 193.5 < b.h_t.iloc[0] < 194.0
    assert "66.3" in b.capacity_curve_note.iloc[0] and "65.7" in b.capacity_curve_note.iloc[1]


def test_variant_c_sigma_extrapolation_and_bias_flag():
    c = fit_area_level(np.array([10, 12, 14, 16, 18.]), np.array([192, 193, 194, 195, 196.]))
    sc = pd.DataFrame({"date": [date(2018, 1, 1), date(2018, 1, 8), date(2018, 1, 15)],
                       "area_km2": [15.0, 25.0, 15.0], "lake_nodata_pct": [0.0, 0.0, 5.0]})
    r = variant_c(sc, c)
    assert (r.h_method == "C").all()
    assert r.h_sigma.iloc[0] == pytest.approx(c.rmse)
    assert r.h_sigma.iloc[1] == pytest.approx(c.rmse + 0.1)
    assert list(r.area_biased) == [False, False, True]


def test_assign_levels_order_and_qc_exclusion():
    dates = [date(2025, 4, 28), date(2020, 1, 8), date(2020, 2, 1), date(2020, 3, 1), date(2020, 3, 8),
             date(2020, 1, 15), date(2020, 1, 22)]
    bulls = pd.DataFrame([bulletin("2020-01-08", 34.84), bulletin("2020-03-08", 40.0),
                          bulletin("2020-01-15", 36.0), bulletin("2020-01-22", 38.0)])
    areas = {d: a for d, a in zip(dates, [17.0, 12.0, 13.0, 14.0, 15.0, 12.6, 13.4])}
    qc = {d: True for d in dates}
    qc[date(2020, 3, 1)] = False   # bez komunikatu -> excluded
    qc[date(2020, 3, 8)] = False   # komunikat -> B nadal
    df = assign_levels(dates, bulls, load_overrides(KNOWN_CSV), areas=areas, qc_ok=qc,
                       nodata_pct={d: 0.0 for d in dates}).set_index("date")
    assert df.loc[date(2025, 4, 28), "h_method"] == "R"
    assert df.loc[date(2020, 1, 8), "h_method"] == "B"
    assert df.loc[date(2020, 3, 8), "h_method"] == "B"
    assert df.loc[date(2020, 2, 1), "h_method"] == "C"
    assert df.loc[date(2020, 3, 1), "h_method"] == "qc_excluded" and np.isnan(df.loc[date(2020, 3, 1), "h_t"])


def sample_df():
    return pd.DataFrame([{"date": date(2020, 1, 8), "tiles": "33UXR;33UXS", "h_t": 193.123, "h_method": "B",
                          "h_source": "s", "h_sigma": 0.15, "h_datum": "d", "area_km2": 12.34567,
                          "lake_nodata_pct": 0.5, "otsu_threshold": 0.1, "local_cloud_pct": 1.0,
                          "qc_ok": True, "qc_reason": ""},
                         {"date": date(2019, 1, 1), "tiles": "33UXR", "h_t": np.nan, "h_method": "qc_excluded",
                          "h_source": "", "h_sigma": np.nan, "h_datum": None, "area_km2": 11.0,
                          "lake_nodata_pct": 0.5, "otsu_threshold": 0.1, "local_cloud_pct": 1.0,
                          "qc_ok": False, "qc_reason": "x"}])


def test_scenes_json_schema(tmp_path):
    write_scenes_json(sample_df(), tmp_path / "s.json")
    rows = json.loads((tmp_path / "s.json").read_text())
    s = rows[1]
    assert set(s) == {"date", "tiles", "h_t", "h_method", "h_source", "h_sigma", "h_datum", "area_km2",
                      "lake_nodata_pct", "otsu_threshold", "local_cloud_pct", "capacity_mln_m3",
                      "qc_ok", "qc_reason"}
    assert [r["date"] for r in rows] == ["2019-01-01", "2020-01-08"]  # posortowane
    assert s["h_t"] == 193.12 and s["area_km2"] == 12.346 and 18 < s["capacity_mln_m3"] < 40
    assert rows[0]["h_t"] is None and rows[0]["capacity_mln_m3"] is None and rows[0]["qc_ok"] is False
