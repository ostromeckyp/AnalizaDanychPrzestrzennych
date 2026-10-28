import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from mielizna.config import data_path
from mielizna.levels import (assign_levels, curve_areas, fit_area_level, load_area_level_curve, load_overrides,
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
    assert r.h_sigma.iloc[0] == pytest.approx(c.sigma)
    assert r.h_sigma.iloc[1] == pytest.approx(c.sigma + 0.1)
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
                          "h_source": "s", "h_sigma": 0.15, "h_datum": "d", "area_km2": 12.34567, "area_otsu_km2": 11.23456,
                          "lake_nodata_pct": 0.5, "otsu_threshold": 0.1, "local_cloud_pct": 1.0,
                          "qc_ok": True, "qc_reason": ""},
                         {"date": date(2019, 1, 1), "tiles": "33UXR", "h_t": np.nan, "h_method": "qc_excluded",
                          "h_source": "", "h_sigma": np.nan, "h_datum": None, "area_km2": 11.0, "area_otsu_km2": 10.0,
                          "lake_nodata_pct": 0.5, "otsu_threshold": 0.1, "local_cloud_pct": 1.0,
                          "qc_ok": False, "qc_reason": "x"}])


def test_scenes_json_schema(tmp_path):
    write_scenes_json(sample_df(), tmp_path / "s.json")
    rows = json.loads((tmp_path / "s.json").read_text())
    s = rows[1]
    assert set(s) == {"date", "tiles", "h_t", "h_method", "h_source", "h_sigma", "h_datum", "h_t_b", "h_t_a", "h_diff_ab", "area_km2",
                      "area_otsu_km2", "lake_nodata_pct", "otsu_threshold", "local_cloud_pct", "capacity_mln_m3",
                      "qc_ok", "qc_reason"}
    assert [r["date"] for r in rows] == ["2019-01-01", "2020-01-08"]  # posortowane
    assert s["h_t"] == 193.12 and s["area_km2"] == 12.346 and s["area_otsu_km2"] == 11.235 and 18 < s["capacity_mln_m3"] < 40
    assert rows[0]["h_t"] is None and rows[0]["capacity_mln_m3"] is None and rows[0]["qc_ok"] is False


def _offset_data():
    rng = np.random.default_rng(1)
    a = np.linspace(10, 18, 60)
    groups = np.repeat([2017, 2018, 2019, 2020], 15)
    off = {2017: 0.4, 2018: -0.4, 2019: 0.3, 2020: -0.3}
    h = 192 + 0.5 * (a - 10) + np.array([off[g] for g in groups]) + rng.normal(0, 0.03, a.size)
    perm = rng.permutation(a.size)
    return a[perm], h[perm], groups[perm]


def test_loyo_exceeds_loo_with_per_group_offsets_and_nan_without_groups():
    a, h, g = _offset_data()
    c = fit_area_level(a, h, groups=g)
    assert np.isfinite(c.rmse_loyo) and c.rmse_loyo > c.rmse
    assert c.sigma == c.rmse_loyo
    c0 = fit_area_level(a, h)
    assert np.isnan(c0.rmse_loyo) and c0.sigma == c0.rmse


def test_variant_c_uses_loyo_sigma_and_reports_otsu_area():
    c = fit_area_level(np.array([10, 12, 14, 16, 18.]), np.array([192, 193, 194, 195, 196.]))
    c.rmse_loyo = 0.49
    sc = pd.DataFrame({"date": [date(2018, 1, 1), date(2018, 1, 8)], "area_km2": [15.0, 25.0],
                       "lake_nodata_pct": [0.0, 0.0]})
    r = variant_c(sc, c)
    assert r.h_sigma.iloc[0] == pytest.approx(0.49) and r.h_sigma.iloc[1] == pytest.approx(0.59)
    assert "A_otsu=15.00 km2" in r.h_source.iloc[0]


def test_curve_json_roundtrip_keeps_loyo_and_area_source(tmp_path):
    a, h, g = _offset_data()
    c = fit_area_level(a, h, groups=g)
    save_area_level_curve(c, tmp_path / "c.json")
    d = json.loads((tmp_path / "c.json").read_text())
    assert d["rmse_loyo"] == pytest.approx(c.rmse_loyo) and d["rmse_loo"] == pytest.approx(c.rmse)
    assert d["area_source"] == "area_otsu_km2 (Otsu, classify_stats.csv)"
    assert load_area_level_curve(tmp_path / "c.json").rmse_loyo == pytest.approx(c.rmse_loyo)


def test_curve_areas_picks_otsu_and_raises_on_missing_date():
    cs = pd.DataFrame({"date": ["2020-01-08", "2020-01-15"], "area_km2": [1.0, 2.0], "area_otsu_km2": [11.0, 12.0]})
    assert curve_areas(cs, [date(2020, 1, 15)]) == {date(2020, 1, 15): 12.0}
    with pytest.raises(ValueError):
        curve_areas(cs, [date(2020, 1, 8), date(2020, 2, 1)])


def test_assign_levels_without_areas_does_not_label_qc_ok_scene_excluded():
    df = assign_levels([date(2020, 2, 1), date(2020, 1, 8)], pd.DataFrame([bulletin("2020-01-08", 34.84)]),
                       load_overrides(KNOWN_CSV)).set_index("date")
    assert df.loc[date(2020, 1, 8), "h_method"] == "B"
    assert df.loc[date(2020, 2, 1), "h_method"] != "qc_excluded"


def _a_override(d, h, method="A"):
    return pd.DataFrame([{"start": d, "end": d, "h": h, "sigma": 0.1, "method": method, "source": "LiDAR 2024 NMT, n=500"}])


def test_b_wins_over_a_and_a_is_kept_in_h_t_a():
    d = date(2020, 1, 8)
    b = bulletin("2020-01-08", 34.84)
    b_only = assign_levels([d], pd.DataFrame([b]), _a_override(date(2001, 1, 1), 1.0)).iloc[0]
    assert b_only.h_method == "B" and np.isnan(b_only.h_t_a) and np.isnan(b_only.h_diff_ab)
    hb = float(b_only.h_t)
    row = assign_levels([d], pd.DataFrame([b]), _a_override(d, hb + 0.35)).iloc[0]
    assert row.h_method == "B" and row.h_t == pytest.approx(hb) and row.h_datum != "PL-EVRF2007-NH"
    assert row.h_t_b == pytest.approx(hb) and row.h_t_a == pytest.approx(hb + 0.35)
    assert row.h_diff_ab == pytest.approx(0.35)


def test_r_beats_b_and_a_and_a_beats_c():
    from mielizna.levels import PRECEDENCE
    assert PRECEDENCE == {"R": 0, "B": 1, "A": 2, "C": 3}
    d = date(2025, 4, 28)
    ov = pd.concat([load_overrides(KNOWN_CSV), _a_override(d, 195.0)], ignore_index=True)
    assert assign_levels([d], pd.DataFrame([bulletin("2025-04-28", 90.0)]), ov).iloc[0].h_method == "R"


def test_assign_levels_a_without_bulletin_has_no_b_fields():
    d = date(2020, 2, 1)
    row = assign_levels([d], pd.DataFrame([bulletin("2020-01-08", 34.84)]), _a_override(d, 195.0)).iloc[0]
    assert row.h_method == "A" and row.h_t == 195.0 and row.h_t_a == 195.0
    assert np.isnan(row.h_t_b) and np.isnan(row.h_diff_ab) and row.h_datum == "PL-EVRF2007-NH"


def test_scenes_json_writes_b_fields(tmp_path):
    df = sample_df()
    df["h_t_b"] = [193.0, np.nan]
    df["h_t_a"] = [193.123, np.nan]
    df["h_diff_ab"] = [0.123, np.nan]
    write_scenes_json(df, tmp_path / "s.json")
    rows = json.loads((tmp_path / "s.json").read_text())
    assert rows[1]["h_t_b"] == 193.0 and rows[1]["h_t_a"] == 193.12 and rows[1]["h_diff_ab"] == 0.12 and rows[0]["h_t_b"] is None


def test_curve_is_fitted_on_r_and_b_only_not_a():
    dates = [date(2020, 1, 8), date(2020, 1, 15), date(2020, 1, 22), date(2020, 1, 29), date(2020, 2, 5),
             date(2020, 2, 12), date(2020, 2, 19)]
    bulls = pd.DataFrame([bulletin("2020-01-08", 34.84), bulletin("2020-01-15", 36.0), bulletin("2020-01-22", 38.0),
                          bulletin("2020-01-29", 40.0)])
    areas = dict(zip(dates, [12.0, 12.6, 13.4, 14.0, 13.0, 15.0, 15.5]))
    kw = dict(areas=areas, qc_ok={d: True for d in dates}, nodata_pct={d: 0.0 for d in dates})
    none = _a_override(date(2001, 1, 1), 1.0)
    base = assign_levels(dates, bulls, none, **kw)
    ov = pd.concat([_a_override(date(2020, 2, 5), 190.0), _a_override(date(2020, 2, 12), 199.0)], ignore_index=True)
    with_a = assign_levels(dates, bulls, ov, **kw)
    assert with_a.set_index("date").loc[date(2020, 2, 5), "h_method"] == "A"
    assert with_a.attrs["curve"].n_obs == base.attrs["curve"].n_obs == 4
    assert with_a.attrs["curve"].rmse == pytest.approx(base.attrs["curve"].rmse)
    assert with_a.set_index("date").loc[date(2020, 2, 19), "h_t"] == pytest.approx(
        base.set_index("date").loc[date(2020, 2, 19), "h_t"])


def test_curve_fit_still_excludes_high_nodata_scenes():
    dates = [date(2020, 1, 8), date(2020, 1, 15), date(2020, 1, 22), date(2020, 1, 29), date(2020, 2, 5)]
    bulls = pd.DataFrame([bulletin("2020-01-08", 34.84), bulletin("2020-01-15", 36.0), bulletin("2020-01-22", 38.0),
                          bulletin("2020-01-29", 40.0)])
    nd = {d: 0.0 for d in dates}
    nd[date(2020, 1, 29)] = 5.0
    df = assign_levels(dates, bulls, _a_override(date(2001, 1, 1), 1.0), areas=dict(zip(dates, [12.0, 12.6, 13.4, 14.0, 13.0])),
                       qc_ok={d: True for d in dates}, nodata_pct=nd)
    assert df.attrs["curve"].n_obs == 3
