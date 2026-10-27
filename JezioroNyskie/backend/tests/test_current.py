"""Testy bieżącego poziomu z najnowszej sceny (bez sieci: search/load/ctx są wstrzykiwane)."""
import json
import math
from datetime import date

import numpy as np
import pytest

from mielizna import s2
from mielizna.classify import lake_core
from mielizna.config import load_config
from mielizna.grid import Grid

from app.current import CurrentLevelService, SceneContext

H, W = 20, 30


class _Model:
    """Atrapa RF: P(woda) rośnie z MNDWI (kolumna 7 w FEATURES)."""
    def predict_proba(self, X):
        p = 1 / (1 + np.exp(-12 * X[:, 7]))
        return np.column_stack([1 - p, p])


def _fake_ctx(products):
    aoi = np.ones((H, W), bool)
    lake = np.zeros((H, W), bool)
    lake[:, :20] = True
    core = np.zeros((H, W), bool)
    core[4:16, 4:16] = True                      # lake_core(20 px) zniknąłby w siatce 20×30
    assert lake_core(lake).sum() == 0
    grid = Grid(products.crs, products.transform, W, H)
    return SceneContext(cfg=load_config(), grid=grid, aoi=aoi, lake=lake, core=core,
                        bundle={"model": _Model(), "water_threshold": 0.5}, curve=products.curve)


def _scene(scl_class=4, level=0.0):
    f = lambda w, l: np.where(np.arange(W)[None, :] < 20, w, l) * np.ones((H, 1)) + level  # noqa: E731
    bands = {"blue": f(0.05, 0.08), "green": f(0.10, 0.06), "red": f(0.05, 0.10), "nir": f(0.03, 0.30),
             "swir16": f(0.02, 0.30), "swir22": f(0.02, 0.20)}
    return {k: v.astype(np.float32) for k, v in bands.items()}, np.full((H, W), scl_class, np.uint8)


def good_scene(items, grid, cfg):
    return _scene()


def cloudy_scene(calls):
    def load(items, grid, cfg):
        calls.append(items)
        return _scene(scl_class=9)               # chmury wszędzie
    return load


def corrupt_scene(items, grid, cfg):
    bands, scl = _scene()
    return {k: np.full_like(v, 1e-4) for k, v in bands.items()}, scl


def one_acq(d, platform="Sentinel-2A"):
    return lambda a, b: {(d, platform): ["tile-33UXR"]}


@pytest.fixture
def service_factory(products, tmp_path):
    def build(search, load=good_scene, today=date(2026, 10, 27)):
        return CurrentLevelService(products, tmp_path / "current", search, load,
                                   ctx_factory=lambda: _fake_ctx(products), clock=lambda: today)
    return build


def test_fallback_when_nothing_found(service_factory):
    s = service_factory(search=lambda a, b: {})
    s.refresh(); r = s.get()
    assert r["source"] == "pipeline" and r["scene_date"] == "2026-10-20"
    assert r["stale"] is False and r["last_error"] is None


def test_live_scene_newer_than_pipeline(service_factory):
    s = service_factory(search=one_acq("2026-10-26")); s.refresh(); r = s.get()
    assert r["source"] == "satellite" and r["h_method"] == "C_live"
    assert r["shoreline"]["type"] in ("LineString", "MultiLineString")
    assert r["h_sigma"] >= s.products.curve.sigma
    assert r["acq_id"] == "2026-10-26_Sentinel-2A" and r["age_days"] == 1 and r["last_checked"]
    json.dumps(r, allow_nan=False)               # JSON-safe


def test_rejections_are_cached_and_not_retried(service_factory, tmp_path):
    calls = []
    s = service_factory(search=one_acq("2026-10-26"), load=cloudy_scene(calls))
    s.refresh(); s.refresh()
    assert len(calls) == 1 and s.get()["source"] == "pipeline"
    assert json.loads(next(tmp_path.glob("current/2026-10-26_*.json")).read_text())["rejected"] == "not_usable"


def test_search_error_never_raises(service_factory):
    def boom(a, b): raise ConnectionError("offline")
    s = service_factory(search=boom); s.refresh(); r = s.get()
    assert r["source"] == "pipeline" and "offline" in r["last_error"]


def test_corrupt_scene_rejected(service_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(s2, "RADIOMETRY_MIN_PIXELS", 100)   # fixture ma 600 pikseli
    s = service_factory(search=one_acq("2026-10-26"), load=corrupt_scene); s.refresh()
    assert s.get()["source"] == "pipeline"
    assert json.loads(next(tmp_path.glob("current/2026-10-26_*.json")).read_text())["rejected"] == "radiometry"


def test_stale_after_fresh_days(service_factory):
    s = service_factory(search=lambda a, b: {}, today=date(2026, 11, 15)); s.refresh()
    assert s.get()["stale"] is True and s.get()["age_days"] == 26


def test_winter_scene_flags_ice(service_factory):
    s = service_factory(search=one_acq("2026-12-10"), today=date(2026, 12, 12)); s.refresh()
    assert s.get()["ice_unverified"] is True


def test_transient_load_error_is_retried(service_factory, tmp_path):
    n = []
    def flaky(items, grid, cfg):
        n.append(1)
        if len(n) == 1:
            raise OSError("s3 down")
        return _scene()
    s = service_factory(search=one_acq("2026-10-26"), load=flaky); s.refresh()
    assert s.get()["source"] == "pipeline" and "s3 down" in s.get()["last_error"]
    assert not list(tmp_path.glob("current/*.json"))
    s.refresh()
    assert s.get()["source"] == "satellite" and s.get()["last_error"] is None


def test_ctx_failure_writes_nothing(products, tmp_path):
    def bad_ctx(): raise FileNotFoundError("rf_model.joblib")
    s = CurrentLevelService(products, tmp_path / "current", one_acq("2026-10-26"), good_scene,
                            ctx_factory=bad_ctx, clock=lambda: date(2026, 10, 27))
    s.refresh()
    r = s.get()
    assert r["source"] == "pipeline" and "rf_model.joblib" in r["last_error"]
    assert not list((tmp_path / "current").glob("*.json"))


def test_qc_failure_is_persisted_and_publishes_nothing(service_factory, tmp_path):
    def land_core(items, grid, cfg):
        bands, scl = _scene()
        land = _scene()[0]
        hole = np.zeros((H, W), bool)
        hole[6:13, 6:15] = True                            # ląd w rdzeniu jeziora
        return {k: np.where(hole, land[k][0, 25], bands[k]).astype(np.float32) for k in bands}, scl
    s = service_factory(search=one_acq("2026-10-26"), load=land_core); s.refresh()
    assert s.get()["source"] == "pipeline"
    rej = json.loads(next(tmp_path.glob("current/2026-10-26_*.json")).read_text())["rejected"]
    assert rej.startswith("qc:"), rej


def test_checks_at_most_three_newest_first(service_factory):
    calls = []
    acqs = {(f"2026-10-{d}", "Sentinel-2A"): [d] for d in (20, 22, 24, 25, 26)}
    s = service_factory(search=lambda a, b: acqs,
                        load=lambda items, g, c: (calls.append(items[0]), _scene(scl_class=9))[1])
    s.refresh()
    assert calls == [26, 25, 24]


def test_tie_with_pipeline_prefers_pipeline(service_factory):
    s = service_factory(search=one_acq("2026-10-20")); s.refresh()
    assert s.get()["source"] == "pipeline"


def test_accepted_survives_restart(service_factory, products, tmp_path):
    service_factory(search=one_acq("2026-10-26")).refresh()
    s2_ = service_factory(search=lambda a, b: {})
    assert s2_.get()["source"] == "satellite"


def test_get_without_refresh_is_fallback(service_factory):
    r = service_factory(search=lambda a, b: {}).get()
    assert r["last_checked"] is None and r["refreshing"] is False
    assert r["shoreline"]["type"] in ("LineString", "MultiLineString")
    assert r["h"] == 193.5 and r["h_method"] == "B" and not math.isnan(r["h_sigma"])


def test_partial_ingest_rejection_is_reevaluated_when_second_tile_appears(service_factory, tmp_path):
    calls = []
    tiles = [["33UXR"]]
    s = service_factory(search=lambda a, b: {("2026-10-26", "Sentinel-2A"): list(tiles[0])},
                        load=cloudy_scene(calls))
    s.refresh(); s.refresh()
    path = next(tmp_path.glob("current/2026-10-26_*.json"))
    stored = json.loads(path.read_text())
    assert len(calls) == 1 and stored["rejected"] == "not_usable" and stored["items"] == ["33UXR"]
    tiles[0] = ["33UXS", "33UXR"]                       # drugi kafel dotarł po pierwszym sprawdzeniu
    s.refresh()
    assert len(calls) == 2 and json.loads(path.read_text())["items"] == ["33UXR", "33UXS"]
    s.refresh()
    assert len(calls) == 2                              # ten sam zbiór kafli: bez ponownej oceny


def test_item_ids_prefer_id_attribute(service_factory, tmp_path):
    class Item:
        def __init__(self, id): self.id = id
    s = service_factory(search=lambda a, b: {("2026-10-26", "Sentinel-2A"): [Item("b"), Item("a")]})
    s.refresh()
    assert json.loads(next(tmp_path.glob("current/2026-10-26_*.json")).read_text())["items"] == ["a", "b"]


def test_reevaluation_replaces_earlier_acceptance(service_factory, tmp_path):
    tiles = [["33UXR"]]
    loads = [good_scene]
    s = service_factory(search=lambda a, b: {("2026-10-26", "Sentinel-2A"): list(tiles[0])},
                        load=lambda i, g, c: loads[0](i, g, c))
    s.refresh()
    assert s.get()["source"] == "satellite"
    tiles[0], loads[0] = ["33UXR", "33UXS"], (lambda i, g, c: _scene(scl_class=9))
    s.refresh()
    assert s.get()["source"] == "pipeline"
