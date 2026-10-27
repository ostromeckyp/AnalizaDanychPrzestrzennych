import datetime as dt

import numpy as np
import pystac
import pytest

from mielizna.s2 import (cloud_mask, check_harmonized, dedupe_items, dn_to_reflectance,
                         drop_non_cog_items,
                         group_acquisitions, is_usable, mosaic_first_valid, reflectance_offset,
                         resample_like_load_day, scene_quality, usable_dates, valid_mask)

CFG = {"scene_filter": {"min_valid_pct": 95, "max_local_cloud_pct": 5, "max_ice_pct": 1,
                        "exclude_dates": []}}


def item(id="S2A_33UXR_20210601_0_L2A", date="2021-06-01", platform="sentinel-2a", tile="MGRS-33UXR",
         baseline="03.01", applied=False, raster_offset=None, scl_ext="tif"):
    d = dt.datetime.fromisoformat(date + "T10:00:00+00:00")
    it = pystac.Item(id, None, None, d, {"platform": platform, "grid:code": tile,
                                         "s2:processing_baseline": baseline,
                                         "earthsearch:boa_offset_applied": applied})
    it.add_asset("scl", pystac.Asset(f"https://example.test/{id}/SCL.{scl_ext}"))
    if raster_offset is not None:
        it.add_asset("swir16", pystac.Asset("x.tif", extra_fields={
            "raster:bands": [{"offset": raster_offset}]}))
    return it


def test_reflectance_masks_zero_and_applies_offset():
    r = dn_to_reflectance(np.array([0, 1000, 3000], dtype=np.uint16), -0.1)
    assert r.dtype == np.float32
    assert np.isnan(r[0]) and np.allclose(r[1:], [0.0, 0.2])


def test_offset_rule():  # Earth Search harmonizes all baselines; flag and raster offset ignored
    assert reflectance_offset(item(baseline="05.10", applied=True, raster_offset=-0.1)) == 0.0
    assert reflectance_offset(item(baseline="05.11", applied=False, raster_offset=-0.1)) == 0.0
    assert reflectance_offset(item(baseline="02.14", applied=False)) == 0.0
    it = item(baseline="00.01")
    del it.properties["earthsearch:boa_offset_applied"]
    assert reflectance_offset(it) == 0.0


def test_check_harmonized():
    scl = np.full((20, 20), 6, np.uint8)
    check_harmonized(np.full((20, 20), 40, np.uint16), scl, "ok")
    with pytest.raises(ValueError, match="SWIR16 floor ~1000 DN over water"):
        check_harmonized(np.full((20, 20), 1040, np.uint16), scl, "bad")


def test_check_harmonized_bright_water_median_passes():
    # hazy scene: median ~550 DN but a dark tail (p5 ~ 400) -> real water, not an offset floor
    scl = np.full((40, 40), 6, np.uint8)
    dn = np.linspace(400, 700, 1600).reshape(40, 40).astype(np.uint16)
    assert np.median(dn) > 500
    check_harmonized(dn, scl, "hazy")


def test_check_harmonized_few_water_pixels_is_noop():
    scl = np.full((5, 5), 6, np.uint8)
    check_harmonized(np.full((5, 5), 1040, np.uint16), scl, "few")


def test_bilinear_does_not_leak_nodata():
    out = resample_like_load_day(np.array([[0, 2000], [2000, 2000]], np.uint16))
    v = out[np.isfinite(out)]
    assert v.size and not ((v > 0) & (v < 0.2 - 1e-6)).any()


def test_bilinear_leaks_without_nodata_tag():  # negative control: the test above can fail
    out = resample_like_load_day(np.array([[0, 2000], [2000, 2000]], np.uint16), tag_nodata=False)
    v = out[np.isfinite(out)]
    assert ((v > 0) & (v < 0.2 - 1e-6)).any()


def test_quality_rejects_partial_tile():
    aoi = np.ones((10, 10), bool); valid = aoi.copy(); valid[:, 6:] = False
    q = scene_quality("2021-06-01", np.full((10, 10), 4), valid, aoi, aoi)
    assert q["valid_pct"] == 60 and not is_usable(q, CFG)


def test_quality_rejects_ice():
    scl = np.full((10, 10), 6); scl[0, :5] = 11
    ones = np.ones((10, 10), bool)
    q = scene_quality("2021-01-10", scl, ones, ones, ones)
    assert q["ice_pct"] == 5 and not is_usable(q, CFG)


def test_quality_accepts_clear():
    ones = np.ones((10, 10), bool)
    q = scene_quality("2021-06-01", np.full((10, 10), 6), ones, ones, ones)
    assert is_usable(q, CFG) and q["scl_pct"] == {6: 100.0}


def test_excluded_date_not_usable():
    ones = np.ones((10, 10), bool)
    q = scene_quality("2021-06-01", np.full((10, 10), 6), ones, ones, ones)
    cfg = {"scene_filter": {**CFG["scene_filter"],
                            "exclude_dates": [{"date": "2021-06-01", "reason": "lód"}]}}
    assert not is_usable(q, cfg)
    cfg["scene_filter"]["exclude_dates"] = ["2021-06-01"]
    assert not is_usable(q, cfg)


def test_cloud_mask_dilates_and_adds_shadow():
    scl = np.full((11, 11), 6, np.uint8); scl[5, 5] = 9; scl[0, 0] = 3
    m = cloud_mask(scl)
    assert m[5, 7] and m[3, 5] and not m[5, 8] and m[0, 0]


def test_valid_mask():
    scl = np.array([[0, 1, 6, 6]], np.uint8)
    b = {"blue": np.array([[1, 1, np.nan, 1]], np.float32)}
    assert valid_mask(b, scl).tolist() == [[False, False, False, True]]


def test_dedupe_keeps_higher_baseline_then_suffix_and_separates_platforms():
    a0 = item("S2A_33UXR_20200701_0_L2A", "2020-07-01", baseline="02.14")
    a1 = item("S2A_33UXR_20200701_1_L2A", "2020-07-01", baseline="05.00")
    b0 = item("S2B_33UXR_20200701_0_L2A", "2020-07-01", platform="sentinel-2b", baseline="02.14")
    c0 = item("S2A_33UXS_20210101_0_L2A", "2021-01-01", tile="MGRS-33UXS", baseline="00.01")
    c1 = item("S2A_33UXS_20210101_1_L2A", "2021-01-01", tile="MGRS-33UXS", baseline="00.01")
    ids = {i.id for i in dedupe_items([a0, a1, b0, c0, c1])}
    assert ids == {a1.id, b0.id, c1.id}


def test_group_acquisitions():
    x = item("S2A_33UXR_20200701_0_L2A", "2020-07-01")
    y = item("S2A_33UXS_20200701_0_L2A", "2020-07-01", tile="MGRS-33UXS")
    z = item("S2B_33UXR_20200701_0_L2A", "2020-07-01", platform="sentinel-2b")
    g = group_acquisitions([x, y, z])
    assert set(g) == {("2020-07-01", "sentinel-2a"), ("2020-07-01", "sentinel-2b")}
    assert len(g[("2020-07-01", "sentinel-2a")]) == 2


def test_mosaic_first_valid():
    n = np.nan
    b1 = {"nir": np.array([[1, 1, n]], np.float32)}
    b2 = {"nir": np.array([[2, 2, 2]], np.float32)}
    s1, s2 = np.array([[6, 6, 0]], np.uint8), np.array([[4, 4, 4]], np.uint8)
    v1, v2 = np.array([[True, True, False]]), np.array([[True, False, True]])
    bands, scl = mosaic_first_valid([b1, b2], [s1, s2], [v1, v2])
    assert np.allclose(bands["nir"], [[1, 1, 2]]) and scl.tolist() == [[6, 6, 4]]
    bands, scl = mosaic_first_valid([b1], [s1], [np.array([[True, False, False]])])
    assert np.isnan(bands["nir"][0, 1:]).all() and scl.tolist() == [[6, 0, 0]]


def test_drop_non_cog_items_keeps_cog_before_dedupe():
    legacy = item("S2A_33UXR_20200701_1_L2A", "2020-07-01", scl_ext="jp2")
    cog = item("S2A_33UXR_20200701_0_L2A", "2020-07-01")
    kept = drop_non_cog_items([legacy, cog])
    assert [i.id for i in kept] == [cog.id]
    assert [i.id for i in dedupe_items(kept)] == [cog.id]
    assert [i.id for i in dedupe_items([legacy, cog])] == [legacy.id]  # why the filter must come first


def _scene_tree(tmp_path, rows, rejected=None, cogs=()):
    import pandas as pd
    (tmp_path / "s2").mkdir()
    pd.DataFrame(rows).to_csv(tmp_path / "scenes_candidates.csv", index=False)
    if rejected is not None:
        pd.DataFrame(rejected).to_csv(tmp_path / "scenes_pass2_rejected.csv", index=False)
    for d in cogs:
        (tmp_path / "s2" / f"{d}.tif").touch()


def _row(date, acq=None, valid=100.0, cloud=0.0, ice=0.0):
    return dict(date=date, acq_id=acq or f"{date}_sentinel-2a", valid_pct=valid,
                local_cloud_pct=cloud, ice_pct=ice)


def test_usable_dates_filters_csv_config_and_rejected(tmp_path):
    rows = [_row("2021-06-01"), _row("2021-06-02", cloud=50), _row("2021-06-03"),
            _row("2021-06-04"), _row("2021-06-05")]
    rejected = [dict(date="2021-06-04", acq_id="2021-06-04_sentinel-2a", reason="guard")]
    _scene_tree(tmp_path, rows, rejected, cogs=["2021-06-01", "2021-06-05"])
    cfg = {"scene_filter": {**CFG["scene_filter"], "exclude_dates": [{"date": "2021-06-03", "reason": "ice"}]}}
    assert usable_dates(cfg, tmp_path) == ["2021-06-01", "2021-06-05"]


def test_usable_dates_without_rejected_file(tmp_path):
    _scene_tree(tmp_path, [_row("2021-06-01")], cogs=["2021-06-01"])
    assert usable_dates(CFG, tmp_path) == ["2021-06-01"]


def test_usable_dates_missing_cog_raises(tmp_path):
    _scene_tree(tmp_path, [_row("2021-06-01"), _row("2021-06-02")], cogs=["2021-06-01"])
    with pytest.raises(FileNotFoundError, match="2021-06-02"):
        usable_dates(CFG, tmp_path)
