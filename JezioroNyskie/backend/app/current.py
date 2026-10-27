"""Bieżący poziom wody z najnowszej sceny Sentinel-2, z awaryjnym powrotem do scen pipeline'u.

Co robi: szuka w STAC najnowszych akwizycji (ostatnie 30 dni), klasyfikuje je wspólnym kodem pipeline'u
  (`mielizna.classify.analyze_scene`), zamienia powierzchnię Otsu na rzędną krzywą powierzchnia↔poziom
  i zapisuje wynik (przyjęty albo odrzucony z powodem) w `cache_dir`. `get()` zwraca nowszą z:
  najnowszej przyjętej sceny na żywo i ostatniej opublikowanej sceny pipeline'u.
Dlaczego tak: scena na żywo nie ma komunikatu RZGW, więc poziom (wariant „C_live") pochodzi wyłącznie z
  powierzchni wody, z niepewnością krzywej (+ dodatek przy ekstrapolacji). Odrzucenia też są zapisywane,
  żeby nie pobierać drugi raz tej samej złej sceny. Zapisujemy tylko werdykty o danych (przyjęta, not_usable,
  radiometry, no_water, qc:*); błędy przejściowe (S3/GDAL, zapis pliku) i systemowe (ctx: brak modelu, zła
  siatka) trafiają do `last_error` bez pliku, więc akwizycja jest ponawiana. Błąd sieci nigdy nie wywraca API: zostaje fallback.
  Powierzchnia dla krzywej to Otsu, nigdy RF (RF przy niskiej wodzie nasyca się na mule → za wysoki poziom).
Wejście → wyjście: `search_fn`, `load_fn`, `ctx_factory` (wstrzykiwane, testy bez sieci) →
  `CurrentLevelService.get()` = słownik `CurrentLevelResponse` bez NaN/Infinity.
Jak to obronić: klasyfikacja i QC to ta sama funkcja co w skrypcie 04; scena z `qc_ok` False nie daje
  poziomu ani linii brzegowej; `ice_unverified` w miesiącach XI–III, bo SCL nie widzi lodu; wątek odświeżający
  i wątki żądań dzielą stan przez `threading.Lock`, a pliki cache powstają atomowo (tmp + replace).
"""
import dataclasses
import json
import logging
import math
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import shapely
from pyproj import CRS

from mielizna import osm, rf, s2
from mielizna.classify import analyze_scene, lake_core
from mielizna.config import load_config
from mielizna.grid import Grid, reference_grid
from mielizna.levels import C_EXTRAP_EXTRA, EXTRAP_TOKEN, AreaLevelCurve
from mielizna.shoreline import mask_to_shoreline

from app.data import Products

log = logging.getLogger(__name__)

SEARCH_DAYS = 30            # okno wyszukiwania wstecz
MAX_CHECKS = 3              # maks. nowych akwizycji ocenianych w jednym odświeżeniu
ICE_MONTHS = {11, 12, 1, 2, 3}
S3_ENV = {"AWS_NO_SIGN_REQUEST": "YES", "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
          "GDAL_HTTP_MAX_RETRY": "5", "GDAL_HTTP_RETRY_DELAY": "2", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif"}
# te same wartości co pipeline/01_fetch_s2.py


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _num(x) -> float | None:
    """float skończony albo None (JSON nie przyjmuje NaN/Infinity)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


@dataclass
class CurrentLevel:
    source: str                      # "satellite" | "pipeline"
    scene_date: str
    acq_id: str | None
    h: float
    h_sigma: float
    h_method: str                    # "C_live" dla satellite, metoda sceny dla pipeline
    extrapolated: bool
    area_biased: bool                # lake_nodata_pct > 1
    ice_unverified: bool             # SCL nie widzi lodu (XI–III)
    local_cloud_pct: float | None
    area_otsu_km2: float | None
    shoreline: dict | None           # GeoJSON geometry, EPSG:4326
    computed_at: str


def _shoreline_geojson(geom, crs: str) -> dict | None:
    """Geometria (EPSG:2180) → GeoJSON geometry w EPSG:4326; pusta → None."""
    if geom is None or geom.is_empty:
        return None
    g = gpd.GeoSeries([geom], crs=crs).to_crs(4326).iloc[0]
    return json.loads(shapely.to_geojson(g))


def pipeline_fallback(products: Products) -> CurrentLevel:
    """Ostatnia opublikowana scena pipeline'u (z `h_t`, qc_ok) wraz z jej linią brzegową."""
    sc = products.scenes[-1]
    geom = products.shorelines.loc[sc["date"]].geometry if sc["date"] in products.shorelines.index else None
    if isinstance(geom, gpd.GeoSeries):
        geom = geom.iloc[0]
    return CurrentLevel(
        source="pipeline", scene_date=sc["date"], acq_id=None, h=float(sc["h_t"]),
        h_sigma=_num(sc.get("h_sigma")) or 0.0, h_method=str(sc["h_method"]),
        extrapolated=EXTRAP_TOKEN in str(sc.get("h_source") or ""),
        area_biased=(_num(sc.get("lake_nodata_pct")) or 0.0) > 1,
        ice_unverified=False,        # plan 1: przegląd wizualny odrzucał sceny z lodem
        local_cloud_pct=_num(sc.get("local_cloud_pct")), area_otsu_km2=_num(sc.get("area_otsu_km2")),
        shoreline=_shoreline_geojson(geom, products.shorelines.crs.to_string()), computed_at=_now())


@dataclass
class SceneContext:
    cfg: dict
    grid: Grid
    aoi: np.ndarray
    lake: np.ndarray
    core: np.ndarray
    bundle: dict
    curve: AreaLevelCurve

    @classmethod
    def build(cls, products: Products, data_dir: Path) -> "SceneContext":
        """Wszystko z `data_dir` (bez zmiany `os.environ`); siatka musi równać się `reference_grid()`."""
        cfg = load_config()
        grid = reference_grid(cfg)
        assert grid.transform == products.transform and (grid.height, grid.width) == tuple(products.shape) \
            and CRS.from_user_input(grid.crs) == CRS.from_user_input(products.crs), \
            "siatka produktów różni się od mielizna.grid.reference_grid()"
        proc = Path(data_dir) / "processed"
        gpkg = proc / "lake.gpkg"
        lake = osm.lake_mask(grid, path=gpkg)
        return cls(cfg=cfg, grid=grid, aoi=osm.aoi_mask(grid, path=gpkg), lake=lake, core=lake_core(lake),
                   bundle=rf.load_model(proc / "model" / "rf_model.joblib"), curve=products.curve)


def load_scene(items, grid, cfg):
    """`s2.load_day` z odczytem COG z publicznego S3 (opcje GDAL jak w skrypcie 01)."""
    with rasterio.Env(**S3_ENV):
        return s2.load_day(items, grid, cfg)


def stac_search(cfg: dict, start: date, end: date) -> dict:
    """Akwizycje {(data, platforma): [kafle]} z okna [start, end]; kopia `cfg` z podmienionym okresem."""
    cfg2 = {**cfg, "period": {"start": start.isoformat(), "end": end.isoformat()}}
    return s2.group_acquisitions(s2.search_items(cfg2, cache=None))


def evaluate(items: list, date: str, ctx: SceneContext, load_fn=load_scene) -> "CurrentLevel | str":
    """Ocenia jedną akwizycję: `CurrentLevel` albo powód odrzucenia (str)."""
    bands, scl = load_fn(items, ctx.grid, ctx.cfg)
    q = s2.scene_quality(date, scl, s2.valid_mask(bands, scl), ctx.aoi, ctx.lake)
    if not s2.is_usable(q, ctx.cfg):
        return "not_usable"
    try:
        r = analyze_scene(bands, scl, date, ctx.bundle, ctx.aoi, ctx.lake, ctx.core)
    except ValueError as e:
        if "radiometrically corrupt" in str(e):
            return "radiometry"
        raise
    area = float(r["area_otsu_km2"])
    if area == 0:
        return "no_water"
    if not r["qc_ok"]:
        return f"qc:{r['qc_reason']}"
    h, extrap = ctx.curve(area)
    geom, _ = mask_to_shoreline(r["mask"], ctx.grid.transform)
    month = int(date[5:7])
    return CurrentLevel(
        source="satellite", scene_date=date, acq_id=None, h=float(h),
        h_sigma=float(ctx.curve.sigma + (C_EXTRAP_EXTRA if extrap else 0.0)), h_method="C_live",
        extrapolated=bool(extrap), area_biased=bool(r["lake_nodata_pct"] > 1), ice_unverified=month in ICE_MONTHS,
        local_cloud_pct=_num(r["local_cloud_pct"]), area_otsu_km2=_num(area),
        shoreline=_shoreline_geojson(geom, ctx.grid.crs), computed_at=_now())


class CurrentLevelService:
    """Odświeżanie (wątek roboczy) i odczyt (wątki żądań) bieżącego poziomu."""

    def __init__(self, products: Products, cache_dir: Path, search_fn, load_fn, ctx_factory,
                 fresh_days: int = 10, clock=date.today):
        self.products, self.cache_dir = products, Path(cache_dir)
        self.search_fn, self.load_fn, self.ctx_factory = search_fn, load_fn, ctx_factory
        self.fresh_days, self.clock = fresh_days, clock
        self._lock = threading.Lock()
        self._ctx: SceneContext | None = None
        self._refreshing = False
        self._last_checked: str | None = None
        self._last_error: str | None = None
        self._accepted: dict[str, dict] = {}
        for f in self.cache_dir.glob("*.json") if self.cache_dir.exists() else []:
            try:
                acc = json.loads(f.read_text(encoding="utf-8")).get("accepted")
            except (OSError, ValueError):
                continue
            if acc:
                self._accepted[f.stem] = acc

    def _write(self, name: str, payload: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{name}.json"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
        os.replace(tmp, path)

    def refresh(self) -> None:
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True
        try:
            self._refresh()
        except Exception as e:  # noqa: BLE001 - refresh() nigdy nie rzuca
            with self._lock:
                self._last_error = f"{type(e).__name__}: {e}"
        finally:
            with self._lock:
                self._refreshing = False
                self._last_checked = _now()

    def _refresh(self) -> None:
        today = self.clock()
        try:
            found = self.search_fn(today - timedelta(days=SEARCH_DAYS), today)
        except Exception as e:  # noqa: BLE001 - sieć nie może wywrócić API
            log.warning("STAC search failed: %s", e)
            with self._lock:
                self._last_error = f"{type(e).__name__}: {e}"
            return
        with self._lock:
            self._last_error = None
        todo = [k for k in sorted(found, key=lambda k: k[0], reverse=True)
                if not (self.cache_dir / f"{k[0]}_{k[1]}.json").exists()][:MAX_CHECKS]
        if not todo:
            return
        if self._ctx is None:
            try:
                self._ctx = self.ctx_factory()
            except Exception as e:  # noqa: BLE001 - błąd systemowy (brak modelu, zła siatka), nie werdykt o scenie
                log.warning("ctx_factory failed: %s", e)
                with self._lock:
                    self._last_error = f"ctx: {type(e).__name__}: {e}"
                return
        for (day, platform) in todo:
            name = f"{day}_{platform}"
            try:
                res = evaluate(found[(day, platform)], day, self._ctx, self.load_fn)
                if isinstance(res, str):
                    self._write(name, {"rejected": res, "checked_at": _now()})
                else:
                    res = dataclasses.replace(res, acq_id=name)
                    acc = dataclasses.asdict(res)
                    self._write(name, {"accepted": acc})
                    with self._lock:
                        self._accepted[name] = acc
            except Exception as e:  # noqa: BLE001 - błąd przejściowy: nie zapisujemy, ponowimy przy następnym odświeżeniu
                log.warning("acquisition %s failed: %s", name, e)
                with self._lock:
                    self._last_error = f"{name}: {type(e).__name__}: {e}"

    def get(self) -> dict:
        """Nowsza z (najnowsza przyjęta scena na żywo, fallback pipeline); remis → pipeline."""
        best = dataclasses.asdict(pipeline_fallback(self.products))
        with self._lock:
            live = max(self._accepted.values(), key=lambda a: a["scene_date"], default=None)
            refreshing, checked, err = self._refreshing, self._last_checked, self._last_error
        if live is not None and live["scene_date"] > best["scene_date"]:
            best = dict(live)
        age = (self.clock() - date.fromisoformat(best["scene_date"])).days
        return {**best, "age_days": age, "stale": age > self.fresh_days, "refreshing": refreshing,
                "last_checked": checked, "last_error": err}
