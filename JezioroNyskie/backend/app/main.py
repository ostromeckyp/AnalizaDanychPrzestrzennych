"""Aplikacja FastAPI: fabryka `create_app`, `/api/meta`, `/api/zones`, `/api/point` oraz listy i pojemność.

Co robi: buduje aplikację z produktami w `app.state`, wystawia metadane (zakresy suwaka, domyślne
  parametry, dokładność) i strefy głębokości dla zadanych h / draft / margin, z ETag i cache.
Dlaczego tak: produkty ładują się leniwie (w `lifespan`), gdy nie podano ich wprost - import
  modułu (testy, `export_openapi`) nie wymaga prawdziwych danych. ETag jest funkcją wersji modelu i
  zaokrąglonych parametrów, więc przeglądarka i CDN mogą odpowiadać 304 bez ciała. Zakres `h` zależy od
  danych, więc walidujemy go w handlerze (422), a nie w `Query`.
Wejście → wyjście: `create_app(settings, products, *, search_fn, load_fn)` → `FastAPI`;
  `GET /api/meta` → `MetaResponse`; `GET /api/zones?h=&draft=&margin=` → `ZonesResponse`;
  `GET /api/point?lon=&lat=&h=&draft=&margin=` → `PointResponse`;
  `GET /api/layers/{bottom,uncertainty}.png?theme=light|dark` → PNG (ETag, 304);
  `GET /api/scenes` → `list[SceneOut]`; `GET /api/shorelines?date=` → GeoJSON `Feature` (EPSG:4326, 404 gdy brak);
  `GET /api/marinas` → `FeatureCollection`; `GET /api/capacity-to-level?v=` / `/api/level-to-capacity?h=` → `{v, h, in_table}`.
  `GET /api/current-level` → `CurrentLevelResponse` (zawsze 200, `no-cache`; z `settings.live` odświeżane w tle).
  `search_fn` i `load_fn` (wstrzykiwane wyszukiwanie STAC / wczytanie sceny) trafiają do `CurrentLevelService`;
  pętla `refresh_loop` działa w `lifespan` i jest anulowana przy zamknięciu.
Jak to obronić: wynik stref jest czystą funkcją (wersja modelu, h, draft, margin) po zaokrągleniu do
  0,05 m, więc klucz cache, ETag i treść zawsze się zgadzają.
"""
import asyncio
import functools
import json
import logging
import math
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from mielizna.config import load_config
from pyproj import Transformer

from app import current
from app.cache import TTLStore
from app.data import Products, capacity_to_level, level_to_capacity, load_products
from app.layers import UNC_MIN, layer_coordinates, bottom_breaks, render_bottom_png, render_uncertainty_png
from app.point import point_info
from app.schemas import (CapacityToLevel, CurrentLevelResponse, Layers, LevelToCapacity, MetaResponse, PointResponse, SceneOut,
                         ZonesResponse)
from app.settings import Settings, get_settings
from app.zones import (round_param, zone_classes, zone_stats, zone_warnings, zones_geojson)

CACHE_CONTROL = "public, max-age=300"
LAYER_CACHE_CONTROL = "public, max-age=86400"   # obrazy warstw: zmieniają się tylko z modelem
STATIC_CACHE_CONTROL = "public, max-age=3600"   # sceny, linie, przystanie, pojemność: zmieniają się tylko z modelem
CAPACITY_MAX_MLN_M3 = 200.0
LEVEL_LIMITS = (180.0, 210.0)                   # rozsądny zakres rzędnej [m n.p.m.] dla /api/level-to-capacity
SLIDER_STEP = 0.05
log = logging.getLogger(__name__)
DEFAULT_DRAFT, DEFAULT_MARGIN = 1.20, 0.30
DRAFT_LIMITS, MARGIN_LIMITS = (0.10, 3.00), (0.00, 1.00)
# brief §16.4: wartości zanurzenia „do potwierdzenia" - front pokazuje je jako wstępne
DRAFT_PRESETS = [
    {"label": "Omega", "draft": 0.90},
    {"label": "Sasanka 660 miecz w górze", "draft": 0.40},
    {"label": "Sasanka 660 miecz w dole", "draft": 1.25},
]


def finite_or_none(x) -> float | None:
    """Liczba skończona albo None (JSON nie zna NaN ani Infinity)."""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def cached_response(request: Request, etag: str, build, cache_control: str = CACHE_CONTROL,
                    media_type: str = "application/json") -> Response:
    """Odpowiedź z ETag i Cache-Control; `If-None-Match` równy ETagowi daje 304 bez ciała.

    `build()` zwraca bajty ciała i jest wywoływane tylko, gdy ciało jest potrzebne. Wspólne dla
    wszystkich endpointów z ETagiem (JSON i PNG).
    """
    headers = {"ETag": etag, "Cache-Control": cache_control}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=build(), media_type=media_type, headers=headers)


def cached_json_response(request: Request, etag: str, build, cache_control: str = CACHE_CONTROL) -> Response:
    """`cached_response` dla JSON."""
    return cached_response(request, etag, build, cache_control)


def slider_range(products: Products) -> tuple[float, float]:
    """Zakres suwaka poziomu: od h_min_obs − 0,5 do max(h_max_obs + 0,5, Max PP), zaokrąglone do 0,05."""
    m = products.meta
    return (round_param(m["h_min_obs"] - 0.5),
            round_param(max(m["h_max_obs"] + 0.5, products.max_pp)))


def scene_out(s: dict) -> SceneOut:
    """Pola sceny dla frontu; liczby nieskończone i NaN → None."""
    f = lambda k: finite_or_none(s.get(k))   # noqa: E731
    return SceneOut(date=s["date"], h_t=f("h_t"), h_sigma=f("h_sigma"), h_method=s.get("h_method"),
                    area_km2=f("area_km2"), area_otsu_km2=f("area_otsu_km2"), otsu_threshold=f("otsu_threshold"),
                    local_cloud_pct=f("local_cloud_pct"), lake_nodata_pct=f("lake_nodata_pct"))


def build_layers(products: Products) -> Layers:
    coords = layer_coordinates(products)
    return Layers(
        bottom={"url": "/api/layers/bottom.png", "coordinates": coords, "breaks": bottom_breaks(products)},
        uncertainty={"url": "/api/layers/uncertainty.png", "coordinates": coords, "min_unc": UNC_MIN})


def build_meta(products: Products) -> MetaResponse:
    m, curve = products.meta, products.curve
    lo, hi = slider_range(products)
    dates = [s["date"] for s in products.scenes]
    last_h = products.scenes[-1]["h_t"] if products.scenes else (lo + hi) / 2
    x0, y0 = products.transform @ (0, products.shape[0])
    x1, y1 = products.transform @ (products.shape[1], 0)
    tr = Transformer.from_crs(products.crs, 4326, always_xy=True)
    lons, lats = tr.transform([x0, x1, x0, x1], [y0, y0, y1, y1])
    shore = products.rf_metrics["by_block"]["per_stratum"]["shore"]
    return MetaResponse(
        model_version=products.version, period=m["period"], period_dates=m["period_dates"],
        n_scenes=len(products.scenes), n_scenes_by_method=m["n_scenes_by_method"],
        first_scene_date=dates[0] if dates else None, last_scene_date=dates[-1] if dates else None,
        h_min_obs=m["h_min_obs"], h_max_obs=m["h_max_obs"], npp=products.npp, max_pp=products.max_pp,
        slider={"min": lo, "max": hi, "step": SLIDER_STEP},
        defaults={"h": round_param(last_h), "draft": DEFAULT_DRAFT, "margin": DEFAULT_MARGIN},
        limits={"draft": DRAFT_LIMITS, "margin": MARGIN_LIMITS},
        draft_presets=DRAFT_PRESETS, presets_provisional=True,
        bbox_wgs84=(min(lons), min(lats), max(lons), max(lats)), crs=products.crs,
        z_max_floor=products.z_max_floor,
        accuracy={"rf_oa": shore["rf_t"]["oa"], "rf_ba": shore["rf_t"]["bacc"],
                  "rf_kappa": shore["rf_t"]["kappa"], "otsu_ba": shore["otsu"]["bacc"],
                  "n_labels": shore["rf_t"]["n"]},
        area_level={
            "nodes_area_km2": [finite_or_none(a) for a in curve.area_km2],
            "nodes_h": [finite_or_none(h) for h in curve.h],
            "rmse_loo": finite_or_none(curve.rmse), "rmse_loyo": finite_or_none(curve.rmse_loyo),
            "points": [{"date": s["date"], "area_otsu_km2": finite_or_none(s.get("area_otsu_km2")),
                        "h_t": finite_or_none(s["h_t"]), "h_method": s.get("h_method")}
                       for s in products.scenes]},
        layers=build_layers(products))


async def refresh_loop(service: current.CurrentLevelService, interval_s: float) -> None:
    """Odświeża bieżący poziom w wątku roboczym co `interval_s`; żaden wyjątek nie przerywa pętli."""
    while True:
        try:
            await asyncio.to_thread(service.refresh)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - pętla ma trwać mimo błędu
            log.exception("current-level refresh failed")
        await asyncio.sleep(interval_s)


def create_app(settings: Settings | None = None, products: Products | None = None, *,
               search_fn=None, load_fn=None) -> FastAPI:
    settings = settings or get_settings()

    def build_service() -> current.CurrentLevelService:
        p = app.state.products
        return current.CurrentLevelService(
            p, settings.data_dir / "processed" / "current",
            search_fn or functools.partial(current.stac_search, load_config()),
            load_fn or current.load_scene,
            lambda: current.SceneContext.build(p, settings.data_dir),
            fresh_days=settings.fresh_days)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.products is None:           # leniwe ładowanie: tylko gdy nie podano produktów
            app.state.products = load_products(settings.data_dir, settings.period)
        if app.state.current is None:
            app.state.current = build_service()
        task = (asyncio.create_task(refresh_loop(app.state.current, settings.refresh_hours * 3600))
                if settings.live else None)
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title="Mielizna API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.products = products
    app.state.cache = TTLStore()
    app.state.search_fn, app.state.load_fn = search_fn, load_fn
    app.state.current = build_service() if products is not None else None   # inaczej w lifespan, po załadowaniu produktów

    @app.get("/api/meta", response_model=MetaResponse)
    def meta(request: Request):
        p: Products = request.app.state.products
        return cached_json_response(request, f'W/"{p.version}"',
                                    lambda: build_meta(p).model_dump_json().encode())

    @app.get("/api/zones", response_model=ZonesResponse)
    def zones(request: Request, h: float = Query(..., allow_inf_nan=False),
              draft: float = Query(DEFAULT_DRAFT, ge=DRAFT_LIMITS[0], le=DRAFT_LIMITS[1]),
              margin: float = Query(DEFAULT_MARGIN, ge=MARGIN_LIMITS[0], le=MARGIN_LIMITS[1])):
        p: Products = request.app.state.products
        lo, hi = slider_range(p)
        h, draft, margin = round_param(h), round_param(draft), round_param(margin)
        if not (lo <= h <= hi):
            raise HTTPException(422, f"h poza zakresem suwaka [{lo}, {hi}]")
        etag = f'W/"{p.version}-{h:.2f}-{draft:.2f}-{margin:.2f}"'
        key = ("zones", h, draft, margin, p.version)
        cache: TTLStore = request.app.state.cache

        def build() -> bytes:
            body = cache.get(key)
            if body is None:
                classes = zone_classes(h, draft, margin, p.z_lo, p.z_hi, p.in_model)
                fc = zones_geojson(classes, p.transform, p.crs)
                body = ZonesResponse(
                    type=fc["type"], features=fc["features"],
                    stats=zone_stats(classes, h, p.z_lo, p.in_model),
                    params={"h": h, "draft": draft, "margin": margin},
                    warnings=zone_warnings(h, draft, margin, p), model_version=p.version,
                ).model_dump_json().encode()
                cache.set(key, body)
            return body

        return cached_json_response(request, etag, build)

    @app.get("/api/point", response_model=PointResponse)
    def point(request: Request, lon: float = Query(..., ge=-180, le=180, allow_inf_nan=False),
              lat: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
              h: float = Query(..., allow_inf_nan=False),
              draft: float = Query(DEFAULT_DRAFT, ge=DRAFT_LIMITS[0], le=DRAFT_LIMITS[1]),
              margin: float = Query(DEFAULT_MARGIN, ge=MARGIN_LIMITS[0], le=MARGIN_LIMITS[1])):
        p: Products = request.app.state.products
        lo, hi = slider_range(p)
        h, draft, margin = round_param(h), round_param(draft), round_param(margin)
        if not (lo <= h <= hi):
            raise HTTPException(422, f"h poza zakresem suwaka [{lo}, {hi}]")
        body = PointResponse(**point_info(p, lon, lat, h, draft, margin))
        return Response(content=body.model_dump_json(), media_type="application/json")

    def static_json(request: Request, suffix: str, build) -> Response:
        p: Products = request.app.state.products
        return cached_json_response(request, f'W/"{p.version}{suffix}"', build, STATIC_CACHE_CONTROL)

    @app.get("/api/scenes", response_model=list[SceneOut])
    def scenes(request: Request):
        p: Products = request.app.state.products
        return static_json(request, "", lambda: json.dumps(
            [scene_out(s).model_dump() for s in p.scenes], ensure_ascii=False).encode())

    @app.get("/api/shorelines")
    def shorelines(request: Request, date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")):
        p: Products = request.app.state.products
        scene = next((s for s in p.scenes if s["date"] == date), None)   # tylko sceny opublikowane
        if scene is None or date not in p.shorelines.index:
            raise HTTPException(404, f"brak linii brzegowej dla {date}")

        def build() -> bytes:
            geom = p.shorelines.loc[[date]].to_crs(4326).geometry.iloc[0]
            return json.dumps({"type": "Feature", "geometry": geom.__geo_interface__,
                               "properties": scene_out(scene).model_dump()}, ensure_ascii=False).encode()
        return static_json(request, f"-shore-{date}", build)

    @app.get("/api/marinas")
    def marinas(request: Request):
        p: Products = request.app.state.products

        def build() -> bytes:
            gdf = p.marinas.to_crs(4326)[["osm_id", "kind", "name", "geometry"]]
            return gdf.to_json(drop_id=True, ensure_ascii=False).encode()   # NaN → null (geopandas)
        return static_json(request, "-marinas", build)

    @app.get("/api/capacity-to-level", response_model=CapacityToLevel)
    def capacity_to_level_ep(request: Request, v: float = Query(..., gt=0, le=CAPACITY_MAX_MLN_M3,
                                                                allow_inf_nan=False)):
        """Pojemność v [mln m³] (0 < v ≤ 200, inaczej 422) → rzędna; poza tabelą KŻ h=None."""
        p: Products = request.app.state.products
        h = finite_or_none(capacity_to_level(p, v))
        return static_json(request, f"-c2l-{v:g}", lambda: CapacityToLevel(
            v=v, h=h, in_table=h is not None).model_dump_json().encode())

    @app.get("/api/level-to-capacity", response_model=LevelToCapacity)
    def level_to_capacity_ep(request: Request, h: float = Query(..., ge=LEVEL_LIMITS[0], le=LEVEL_LIMITS[1],
                                                                allow_inf_nan=False)):
        """Rzędna h [m n.p.m.] (180–210, inaczej 422) → pojemność [mln m³]; poza tabelą KŻ v=None."""
        p: Products = request.app.state.products
        v = finite_or_none(level_to_capacity(p, h))
        return static_json(request, f"-l2c-{h:g}", lambda: LevelToCapacity(
            h=h, v=v, in_table=v is not None).model_dump_json().encode())

    @app.get("/api/current-level", response_model=CurrentLevelResponse)
    def current_level(request: Request):
        """Bieżący poziom (najnowsza scena S2 albo pipeline); odpowiedź natychmiastowa, zawsze 200."""
        body = CurrentLevelResponse(**request.app.state.current.get())
        return Response(content=body.model_dump_json(), media_type="application/json",
                        headers={"Cache-Control": "no-cache"})

    layer_renderers = {"bottom": render_bottom_png, "uncertainty": render_uncertainty_png}

    def layer_png(request: Request, name: str, theme: str) -> Response:
        p: Products = request.app.state.products
        cache: TTLStore = request.app.state.cache
        key = ("layer", name, theme, p.version)

        def build() -> bytes:
            body = cache.get(key)
            if body is None:
                body = layer_renderers[name](p, theme)
                cache.set(key, body)
            return body

        return cached_response(request, f'W/"{p.version}-{name}-{theme}"', build, LAYER_CACHE_CONTROL, "image/png")

    @app.get("/api/layers/bottom.png", response_class=Response, responses={200: {"content": {"image/png": {}}}})
    def bottom_png(request: Request, theme: Literal["light", "dark"] = Query(...)):
        """Dno w 5 klasach (RGBA, EPSG:3857); narożniki i progi w `/api/meta`."""
        return layer_png(request, "bottom", theme)

    @app.get("/api/layers/uncertainty.png", response_class=Response,
             responses={200: {"content": {"image/png": {}}}})
    def uncertainty_png(request: Request, theme: Literal["light", "dark"] = Query(...)):
        """Kropki niepewności (RGBA, 4× rozdzielczość, EPSG:3857)."""
        return layer_png(request, "uncertainty", theme)

    return app


app = create_app()
