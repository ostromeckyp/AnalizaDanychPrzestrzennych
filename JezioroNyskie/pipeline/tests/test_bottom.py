import json

import numpy as np
import pytest
import rasterio
from affine import Affine

from mielizna.bottom import (combine_evidence, compute_bounds, model_version, read_model, select_scenes,
                             write_model)
from mielizna.grid import Grid

H = np.array([193.8, 194.2, 194.6, 195.4])
S0 = np.zeros(4)


def px(*w):
    return np.array(w, np.uint8).reshape(-1, 1, 1)


def test_clean_pixel_interval():
    r = compute_bounds(px(0, 0, 1, 1), H, S0)
    assert r["z_min"][0, 0] == 194.2 and r["z_max"][0, 0] == 194.6 and r["n_conflict"][0, 0] == 0


def test_one_conflict_exact():
    r = compute_bounds(px(0, 1, 0, 1, 1), np.array([193.8, 194.0, 194.2, 194.6, 195.4]), np.zeros(5))
    assert (r["z_min"][0, 0], r["z_max"][0, 0], r["n_conflict"][0, 0]) == (193.8, 194.6, 1)


def test_unsorted_input_same_result():
    perm = [2, 0, 3, 1]
    r = compute_bounds(px(0, 0, 1, 1)[perm], H[perm], S0)
    assert (r["z_min"][0, 0], r["z_max"][0, 0]) == (194.2, 194.6)


def test_equal_levels_give_no_separator():
    r = compute_bounds(px(0, 1), np.array([195.0, 195.0]), np.zeros(2))
    assert r["n_conflict"][0, 0] == 1


def test_bounds_widened_by_sigma():
    r = compute_bounds(px(0, 0, 1, 1), H, np.array([0, 0.1, 0.2, 0]))
    assert np.isclose(r["z_min"][0, 0], 194.1) and np.isclose(r["z_max"][0, 0], 194.8)


def test_always_water_has_upper_bound_only():
    r = compute_bounds(px(1, 1, 1, 1), H, S0)
    assert np.isnan(r["z_min"][0, 0]) and r["z_max"][0, 0] == 193.8


def test_nodata_is_ignored_not_land():
    r = compute_bounds(px(255, 0, 1, 1), H, S0)
    assert r["obs_count"][0, 0] == 3 and r["z_min"][0, 0] == 194.2


def test_never_observed_is_nan():
    r = compute_bounds(px(255, 255, 255, 255), H, S0)
    assert np.isnan(r["z_min"][0, 0]) and np.isnan(r["z_max"][0, 0])


def test_combine_evidence():
    rf = np.array([1, 1, 0, 0, 255, 1, 0, 255, 255], np.uint8)
    ot = np.array([1, 0, 1, 0, 1, 255, 255, 0, 255], np.uint8)
    # R25: woda tylko gdy obie = 1; lad gdy KTORAKOLWIEK = 0 (nawet gdy druga to 255); inaczej 255
    assert combine_evidence(rf, ot).tolist() == [1, 0, 0, 0, 255, 255, 0, 0, 255]


def test_combine_evidence_otsu_255_does_not_erase_rf_land():
    """R25: Otsu 255 + RF 0 -> lad (wczesniej 255, co mogło obnizyc z_max wzgledem samego RF)."""
    assert combine_evidence(np.array([0], np.uint8), np.array([255], np.uint8)).tolist() == [0]
    assert combine_evidence(np.array([255], np.uint8), np.array([0], np.uint8)).tolist() == [0]


def test_r25_combined_never_lowers_zmax_vs_rf_only():
    """Dowod: RF∧Otsu-woda ⊆ RF-woda, RF-lad ⊆ polaczony-lad => wzgledem samego RF tylko usuwamy wode lub
    dokladamy lad => z_max (NaN = +inf) nie spada (przy sigma_C >= sigma_nonC)."""
    for seed in range(8):
        rng = np.random.default_rng(500 + seed)
        T = 25
        rf = rng.choice([0, 1, 255], size=(T, 20, 20), p=[.3, .45, .25]).astype(np.uint8)
        ot = rng.choice([0, 1, 255], size=(T, 20, 20), p=[.3, .45, .25]).astype(np.uint8)
        h = np.round(rng.uniform(193, 197, T), 1)
        isc = rng.random(T) < .3
        sig = np.where(isc, rng.uniform(.3, .6, T), rng.uniform(.05, .3, T))
        comb = compute_bounds(combine_evidence(rf, ot), h, sig, is_c=isc)
        base = compute_bounds(rf, h, sig, is_c=isc)
        zc = np.where(np.isnan(comb["z_max"]), np.inf, comb["z_max"])
        zb = np.where(np.isnan(base["z_max"]), np.inf, base["z_max"])
        assert np.isfinite(zb).any()
        assert np.all(zc >= zb - 1e-12)


def test_c_water_is_unknown_for_threshold_and_zmax():
    """R24: woda ze sceny C = 255. Tu C (194.2) widzi wodę, B (194.6, 195.4) też; z_max z B, flaga 8 ustawiona."""
    r = compute_bounds(px(0, 1, 1, 1), H, np.array([.15, .49, .15, .15]), is_c=np.array([0, 1, 0, 0], bool))
    assert np.isclose(r["z_max"][0, 0], 194.75) and r["z_max_raw"][0, 0] == 194.6
    assert r["z_min_raw"][0, 0] == 193.8 and r["flags"][0, 0] & 8


def test_c_water_ignored_equals_unknown():
    c = np.array([0, 1, 0, 0], bool)
    a = compute_bounds(px(0, 1, 1, 1), H, np.array([.15, .49, .15, .15]), is_c=c)
    b = compute_bounds(px(0, 255, 1, 1), H, np.array([.15, .49, .15, .15]), is_c=c)
    for k in ("z_min", "z_max", "z_min_raw", "z_max_raw", "n_conflict"):
        np.testing.assert_array_equal(a[k], b[k])


def test_only_c_water_gives_no_zmax_and_flag():
    r = compute_bounds(px(0, 1, 1, 1), H, np.array([.15, .49, .49, .49]), is_c=np.array([0, 1, 1, 1], bool))
    assert np.isnan(r["z_max"][0, 0]) and r["z_min_raw"][0, 0] == 193.8
    assert r["flags"][0, 0] & 8 and r["flags"][0, 0] & 2
    r = compute_bounds(px(1, 1), H[:2], np.array([.49, .49]), is_c=np.array([1, 1], bool))
    assert np.isnan(r["z_max"][0, 0]) and np.isnan(r["z_min"][0, 0]) and r["obs_count"][0, 0] == 2
    assert r["flags"][0, 0] == 8 | 16


def test_c_land_still_raises_zmin():
    r = compute_bounds(px(0, 0, 1, 1), H, np.array([.15, .49, .15, .15]), is_c=np.array([0, 1, 0, 0], bool))
    assert r["z_min_raw"][0, 0] == 194.2 and np.isclose(r["z_min"][0, 0], 194.2 - .49)
    assert not (r["flags"][0, 0] & 8)


def test_contradictory_distinct_levels_unresolved():
    r = compute_bounds(px(1, 0), np.array([193.0, 197.0]), np.zeros(2))
    assert r["n_conflict"][0, 0] == 1 and np.isnan(r["z_min"][0, 0]) and np.isnan(r["z_max"][0, 0])
    assert r["flags"][0, 0] & 4 and r["flags"][0, 0] & 16


def test_adding_c_water_never_lowers_zmax():
    for seed in range(8):
        rng = np.random.default_rng(100 + seed)
        T = 20
        m = rng.choice([0, 1, 255], size=(T, 15, 15), p=[.3, .3, .4]).astype(np.uint8)
        h = np.round(rng.uniform(193, 197, T), 1)
        isc = rng.random(T) < .4
        sig = np.where(isc, rng.uniform(.3, .6, T), rng.uniform(.05, .3, T))   # sigma_C >= sigma_nonC
        old = compute_bounds(m, h, sig, is_c=isc)
        m2 = m.copy()
        add = (m == 255) & isc[:, None, None] & (rng.random(m.shape) < .7)
        m2[add] = 1
        new = compute_bounds(m2, h, sig, is_c=isc)
        for key in ("z_max_raw", "z_max"):
            fin = np.isfinite(old[key])
            assert np.all(new[key][fin] >= old[key][fin] - 1e-12)
            np.testing.assert_array_equal(old[key], new[key])      # R24: dokładnie bez zmian


def test_equal_levels_unresolved_flag():
    r = compute_bounds(px(0, 1), np.array([195.0, 195.0]), np.zeros(2))
    assert r["obs_count"][0, 0] == 2 and np.isnan(r["z_min"][0, 0]) and np.isnan(r["z_max"][0, 0])
    assert r["flags"][0, 0] & 16


def test_special_flags_always_water_land():
    assert compute_bounds(px(1, 1, 1, 1), H, S0)["flags"][0, 0] == 1
    assert compute_bounds(px(0, 0, 0, 0), H, S0)["flags"][0, 0] == 2
    assert compute_bounds(px(255, 255, 255, 255), H, S0)["flags"][0, 0] == 0


def _reference(w, h):
    """Pętla po jednym pikselu: obwiednia minimalizatorów po progach między różnymi poziomami."""
    ok = w != 255
    w, hh = w[ok], h[ok]
    u = np.unique(hh)
    lev = np.searchsorted(u, hh)
    errs = [int(((w == 1) & (lev < k)).sum() + ((w == 0) & (lev >= k)).sum()) for k in range(len(u) + 1)]
    best = min(errs)
    ks = [k for k, e in enumerate(errs) if e == best]
    kmin, kmax = ks[0], ks[-1]
    land = hh[(w == 0) & (lev < kmin)]
    water = hh[(w == 1) & (lev >= kmax)]
    return (land.max() if land.size else np.nan, water.min() if water.size else np.nan, best)


def test_matches_bruteforce_reference():
    rng = np.random.default_rng(0)
    T = 25
    m = rng.choice([0, 1, 255], size=(T, 6, 7), p=[.4, .5, .1]).astype(np.uint8)
    h = np.round(rng.uniform(193, 197, T), 1)  # zaokrąglenie wymusza równe poziomy
    r = compute_bounds(m, h, np.zeros(T))
    for i in range(6):
        for j in range(7):
            zl, zw, n = _reference(m[:, i, j], h)
            np.testing.assert_array_equal(r["z_min_raw"][i, j], zl)
            np.testing.assert_array_equal(r["z_max_raw"][i, j], zw)
            assert r["n_conflict"][i, j] == n


def test_strips_do_not_change_result():
    rng = np.random.default_rng(3)
    m = rng.choice([0, 1, 255], size=(12, 9, 5), p=[.4, .5, .1]).astype(np.uint8)
    h = np.round(rng.uniform(193, 197, 12), 1)
    a = compute_bounds(m, h, np.full(12, .1), strip_rows=2)
    b = compute_bounds(m, h, np.full(12, .1), strip_rows=100)
    for k in a:
        np.testing.assert_array_equal(a[k], b[k])


def test_adding_land_never_lowers_zmax():
    """Własność z U1/R24 przy sigma_C >= sigma_nonC (przypadek realny: C 0.49, B 0.15; dowód z R24 z niej
    nie korzysta, bo woda C nie wchodzi do z_max)."""
    rng = np.random.default_rng(1)
    T = 20
    m = rng.choice([0, 1, 255], size=(T, 20, 20), p=[.3, .4, .3]).astype(np.uint8)
    h = np.round(rng.uniform(193, 197, T), 1)
    isc = rng.random(T) < .3
    sig = np.where(isc, rng.uniform(.3, .6, T), rng.uniform(.05, .3, T))
    old = compute_bounds(m, h, sig, is_c=isc)
    m2 = m.copy()
    flip = (m == 255) & (rng.random(m.shape) < .5)
    m2[flip] = 0
    new = compute_bounds(m2, h, sig, is_c=isc)
    for key in ("z_max_raw", "z_max"):
        fin = np.isfinite(old[key])
        assert np.all((new[key][fin] >= old[key][fin] - 1e-12) | np.isnan(new[key][fin]))


def test_bounds_ordering_invariant():
    rng = np.random.default_rng(2)
    T = 30
    m = rng.choice([0, 1, 255], size=(T, 25, 25), p=[.4, .5, .1]).astype(np.uint8)
    h = np.round(rng.uniform(193, 197, T), 1)
    r = compute_bounds(m, h, rng.uniform(0, .5, T), is_c=rng.random(T) < .3)
    a = np.isfinite(r["z_min"]) & np.isfinite(r["z_max"])
    assert a.any()
    assert np.all(r["z_min"][a] <= r["z_min_raw"][a])
    assert np.all(r["z_min_raw"][a] < r["z_max_raw"][a])
    assert np.all(r["z_max_raw"][a] <= r["z_max"][a])


def test_select_scenes_contract():
    sc = [{"date": "2020-05-02", "h_t": 195.0, "h_sigma": .15, "h_method": "B", "qc_ok": True, "h_source": ""},
          {"date": "2020-05-01", "h_t": 194.0, "h_sigma": .49, "h_method": "C", "qc_ok": True,
           "h_source": "krzywa, ekstrapolacja"},
          {"date": "2020-05-03", "h_t": 195.5, "h_sigma": .15, "h_method": "B", "qc_ok": False, "h_source": ""},
          {"date": "2020-05-04", "h_t": None, "h_sigma": None, "h_method": "qc_excluded", "qc_ok": True,
           "h_source": ""},
          {"date": "2020-05-05", "h_t": float("nan"), "h_sigma": .1, "h_method": "B", "qc_ok": True,
           "h_source": ""},
          {"date": "2020-06-01", "h_t": 196.0, "h_sigma": .15, "h_method": "B", "qc_ok": True, "h_source": ""},
          {"date": "2020-07-01", "h_t": 196.0, "h_sigma": .15, "h_method": "B", "qc_ok": True, "h_source": ""}]
    df = select_scenes(sc, "2020-05-01", "2020-06-01")
    assert df.date.tolist() == ["2020-05-01", "2020-05-02", "2020-06-01"]
    assert list(df.columns[:4]) == ["date", "h_t", "h_sigma", "h_method"]
    assert df.extrapolated.tolist() == [True, False, False]
    with pytest.raises(ValueError, match="h_sigma"):
        select_scenes([{"date": "2020-05-01", "h_t": 194.0, "h_sigma": None, "h_method": "B", "qc_ok": True}],
                      "2020-05-01", "2020-05-02")


def test_extrapolation_token_is_shared_with_levels():
    from mielizna.levels import EXTRAP_TOKEN
    sc = [{"date": "2020-05-01", "h_t": 194.0, "h_sigma": .49, "h_method": "C", "qc_ok": True,
           "h_source": f"krzywa{EXTRAP_TOKEN}"}]
    assert select_scenes(sc, "2020-05-01", "2020-05-02").extrapolated.tolist() == [True]


def _grid():
    return Grid("EPSG:2180", Affine(10, 0, 372000, 0, -10, 292500), 6, 4)


def test_write_model_roundtrip(tmp_path):
    g = _grid()
    m = np.full((3, 4, 6), 255, np.uint8)
    m[:, 0, 0] = [0, 1, 1]
    m[:, 1, 1] = [1, 1, 1]
    m[:, 2, 2] = [0, 0, 0]
    r = compute_bounds(m, np.array([194., 195., 196.]), np.full(3, .1))
    aoi = np.ones((4, 6), bool)
    aoi[3, :] = False
    meta = {"period": "all", "version": "abc"}
    write_model(r, g, tmp_path, meta, aoi)
    for f in ("bottom_zmin", "bottom_zmax", "bottom_z", "bottom_unc", "obs_count", "conflict_count",
              "bottom_flags"):
        assert (tmp_path / f"{f}.tif").exists()
    with rasterio.open(tmp_path / "bottom_zmax.tif") as ds:
        assert ds.dtypes[0] == "float32" and ds.crs.to_epsg() == 2180 and np.isnan(ds.nodata)
    with rasterio.open(tmp_path / "obs_count.tif") as ds:
        assert ds.dtypes[0] == "uint16" and ds.nodata == 65535
        assert ds.read(1)[3, 0] == 65535 and ds.read(1)[0, 0] == 3 and ds.read(1)[0, 3] == 0
    with rasterio.open(tmp_path / "bottom_flags.tif") as ds:
        f = ds.read(1)
        assert ds.dtypes[0] == "uint8" and ds.nodata == 255 and f[3, 0] == 255 and f[1, 1] == 1 and f[2, 2] == 2
    arrays, meta2 = read_model(tmp_path)
    assert meta2["period"] == "all" and meta2["version"] == "abc"
    assert np.isnan(arrays["z_min"][1, 1]) and np.isclose(arrays["z_max"][1, 1], 194.1, atol=1e-4)
    assert np.isclose(arrays["z_min"][0, 0], 193.9, atol=1e-4) and np.isclose(arrays["z_max"][0, 0], 195.1, atol=1e-4)
    assert np.isnan(arrays["z_max"][2, 2]) and arrays["flags"][2, 2] == 2


def test_model_version_depends_on_inputs():
    a = model_version(b"x", ["2020-01-01"], "sha1")
    assert len(a) == 12 and a == model_version(b"x", ["2020-01-01"], "sha1")
    assert a != model_version(b"y", ["2020-01-01"], "sha1") and a != model_version(b"x", ["2020-01-02"], "sha1")
    assert a != model_version(b"x", ["2020-01-01"], "sha2")
    json.dumps(a)


def test_r24_never_lowers_zmax_nor_zmin_vs_no_c_rule():
    """Własność R24 na losowych danych (σ_C ≥ σ_nonC): reguła C tylko podnosi z_max i z_min."""
    for seed in range(6):
        rng = np.random.default_rng(300 + seed)
        T = 25
        m = rng.choice([0, 1, 255], size=(T, 20, 20), p=[.35, .4, .25]).astype(np.uint8)
        h = np.round(rng.uniform(193, 197, T), 1)
        isc = rng.random(T) < .4
        sig = np.where(isc, rng.uniform(.3, .6, T), rng.uniform(.05, .3, T))
        with_c = compute_bounds(m, h, sig, is_c=isc)
        without = compute_bounds(m, h, sig, is_c=None)
        # NaN = ±inf (brak granicy): z_max NaN → +inf, z_min NaN → -inf
        zmax_c = np.where(np.isnan(with_c["z_max"]), np.inf, with_c["z_max"])
        zmax_0 = np.where(np.isnan(without["z_max"]), np.inf, without["z_max"])
        zmin_c = np.where(np.isnan(with_c["z_min"]), -np.inf, with_c["z_min"])
        zmin_0 = np.where(np.isnan(without["z_min"]), -np.inf, without["z_min"])
        fin = np.isfinite(zmax_0)
        assert fin.any()
        assert np.all(zmax_c[fin] >= zmax_0[fin] - 1e-12)
        fin = np.isfinite(zmin_0)
        assert np.all(zmin_c[fin] >= zmin_0[fin] - 1e-12)
