from datetime import date

import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier

from mielizna import classify
from mielizna.classify import classify_scene, keep_lake_component, predict_scene
from mielizna.features import FEATURES, compute_features, stack
from mielizna.s2 import BANDS, cloud_mask

D = date(2021, 6, 1)


def _scene(shape=(40, 40)):
    """Lewa połowa woda (zielony wysoki, SWIR niski), prawa ląd; SCL 6 / 4."""
    b = {k: np.full(shape, 0.1, np.float32) for k in BANDS}
    b["green"][:, :20], b["swir16"][:, :20], b["nir"][:, :20] = 0.25, 0.02, 0.03
    b["green"][:, 20:], b["swir16"][:, 20:], b["nir"][:, 20:] = 0.08, 0.25, 0.30
    scl = np.full(shape, 4, np.uint8)
    scl[:, :20] = 6
    return b, scl


def _bundle(thr=0.5):
    """Model uczony na tej samej syntetycznej scenie (woda = lewa połowa)."""
    b, _ = _scene()
    f = stack(compute_features(b, 0.0, D)).reshape(-1, len(FEATURES))
    y = (np.arange(40 * 40) % 40 < 20).astype(int)
    m = RandomForestClassifier(n_estimators=10, random_state=0).fit(f, y)
    return {"model": m, "features": FEATURES, "water_threshold": thr}


def test_cloud_is_nodata_not_land():           # Review Focus 2
    b, scl = _scene()
    scl[5:8, 3:6] = 9                          # chmura nad wodą
    scl[30:32, 30:32] = 3                      # cień nad lądem
    m = predict_scene(b, scl, _bundle(), D, 0.0)
    assert (m[cloud_mask(scl)] == 255).all()
    assert (m[:3, :3] == 1).all() and (m[35:, 35:] == 0).all()


def test_nan_features_and_invalid_are_nodata():
    b, scl = _scene()
    b["red"][20, 30] = np.nan
    scl[0, 39] = 1                             # SCL saturated/defective
    m = predict_scene(b, scl, _bundle(), D, 0.0)
    assert m[20, 30] == 255 and m[0, 39] == 255
    assert m.dtype == np.uint8


def test_water_threshold_from_bundle_is_used():
    b, scl = _scene()
    assert (predict_scene(b, scl, _bundle(1.01), D, 0.0)[:3, :3] == 0).all()


def test_proba_map_scaled_and_nodata_matches_mask():
    b, scl = _scene()
    scl[5:8, 3:6] = 9
    mask, proba = classify.predict_scene_with_proba(b, scl, _bundle(), D, 0.0)
    assert proba.dtype == np.uint8 and proba[proba != 255].max() <= 254
    assert ((proba == 255) == (mask == 255)).all()
    assert proba[0, 0] == 254 and proba[39, 39] == 0


def test_keep_lake_component_drops_isolated_pond():
    m = np.zeros((20, 20), np.uint8); m[5:15, 5:15] = 1; m[0:2, 18:20] = 1
    core = np.zeros_like(m, bool); core[8:12, 8:12] = True
    out = keep_lake_component(m, core, np.ones_like(core), min_px=5)
    assert out[10, 10] == 1 and out[0, 19] == 0      # 4 px < 5 -> szum -> 0


def test_cut_off_bay_is_unknown_not_land():      # Review Focus 5
    m = np.zeros((20, 20), np.uint8); m[5:15, 5:10] = 1; m[5:15, 12:18] = 1   # zatoka 60 px odcięta
    core = np.zeros_like(m, bool); core[8:12, 6:9] = True
    out = keep_lake_component(m, core, np.ones_like(core), min_px=5)
    assert (out[5:15, 12:18] == 255).all() and (out[5:15, 5:10] == 1).all()


def test_keep_lake_component_nodata_and_outside_aoi():
    m = np.zeros((20, 20), np.uint8); m[5:15, 5:15] = 1; m[0, 0] = 255
    core = np.zeros_like(m, bool); core[8:12, 8:12] = True
    aoi = np.ones_like(core); aoi[:, 17:] = False
    out = keep_lake_component(m, core, aoi, min_px=5)
    assert out[0, 0] == 255 and (out[:, 17:] == 255).all() and out[10, 10] == 1


def test_diagonal_neighbours_are_connected():
    m = np.zeros((10, 10), np.uint8); m[2:6, 2:6] = 1; m[6:9, 6:9] = 1   # stykają się rogiem
    core = np.zeros_like(m, bool); core[3:5, 3:5] = True
    out = keep_lake_component(m, core, np.ones_like(core), min_px=5)
    assert (out[6:9, 6:9] == 1).all()


def test_lake_core_erodes_by_pixels():
    lake = np.zeros((30, 30), bool); lake[5:25, 5:25] = True
    core = classify.lake_core(lake, 3)
    assert core.sum() == 14 * 14 and not core[5, 5]


def test_classify_scene_returns_mask_otsu_area():
    b, scl = _scene()
    aoi = np.ones((40, 40), bool)
    core = np.zeros((40, 40), bool); core[10:30, 5:15] = True
    mask, t, area = classify_scene(b, scl, D, _bundle(), aoi, core)
    assert mask.shape == (40, 40) and np.isfinite(t)
    assert area == pytest.approx((mask == 1).sum() * 1e-4) and area == pytest.approx(0.08)


def test_classify_scene_full_matches_classify_scene():
    b, scl = _scene()
    aoi = np.ones((40, 40), bool)
    core = np.zeros((40, 40), bool); core[10:30, 5:15] = True
    m1, t1, _ = classify_scene(b, scl, D, _bundle(), aoi, core)
    m2, proba, t2 = classify.classify_scene_full(b, scl, D, _bundle(), aoi, core)
    assert (m1 == m2).all() and t1 == t2 and proba.shape == m1.shape


def test_otsu_scene_mask_cloud_is_nodata_and_filters_pond():
    b, scl = _scene()
    scl[5:8, 3:6] = 9
    aoi = np.ones((40, 40), bool)
    core = np.zeros((40, 40), bool); core[10:30, 5:15] = True
    m = classify.otsu_scene_mask(b, scl, aoi, core, 0.0)
    assert (m[cloud_mask(scl)] == 255).all() and m[20, 2] == 1 and m[20, 38] == 0
