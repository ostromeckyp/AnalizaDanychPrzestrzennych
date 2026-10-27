"""Aplikacja FastAPI: fabryka `create_app`, `/api/meta`, `/api/zones` i `/api/point`.

Co robi: buduje aplikację z produktami w `app.state`, wystawia metadane (zakresy suwaka, domyślne
  parametry, dokładność) i strefy głębokości dla zadanych h / draft / margin, z ETag i cache.
Dlaczego tak: produkty ładują się leniwie (w `lifespan`), gdy nie podano ich wprost - import
  modułu (testy, `export_openapi`) nie wymaga prawdziwych danych. ETag jest funkcją wersji modelu i
  zaokrąglonych parametrów, więc przeglądarka i CDN mogą odpowiadać 304 bez ciała. Zakres `h` zależy od
  danych, więc walidujemy go w handlerze (422), a nie w `Query`.
Wejście → wyjście: `create_app(settings, products, *, search_fn, load_fn)` → `FastAPI`;
  `GET /api/meta` → `MetaResponse`; `GET /api/zones?h=&draft=&margin=` → `ZonesResponse`;
  `GET /api/point?lon=&lat=&h=&draft=&margin=` → `PointResponse`.
  `search_fn` i `load_fn` (wstrzykiwane wyszukiwanie STAC / wczytanie sceny) zostaną użyte w kolejnych zadaniach.
Jak to obronić: wynik stref jest czystą funkcją (wersja modelu, h, draft, margin) po zaokrągleniu do
  0,05 m, więc klucz cache, ETag i treść zawsze się zgadzają.
"""
import math
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response
from pyproj import Transformer

from app.cache import TTLStore
from app.data import Products, load_products
from app.point import point_info
from app.schemas import MetaResponse, PointResponse, ZonesResponse
from app.settings import Settings, get_settings
from app.zones import (round_param, zone_classes, zone_stats, zone_warnings, zones_geojson)

CACHE_CONTROL = "public, max-age=300"
SLIDER_STEP = 0.05
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


def cached_json_response(request: Request, etag: str, build) -> Response:
    """Odpowiedź JSON z ETag i Cache-Control; `If-None-Match` równy ETagowi daje 304 bez ciała.

    `build()` zwraca bajty JSON i jest wywoływane tylko, gdy ciało jest potrzebne. Wspólne dla
    wszystkich endpointów z ETagiem.
    """
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=build(), media_type="application/json", headers=headers)


def slider_range(products: Products) -> tuple[float, float]:
    """Zakres suwaka poziomu: od h_min_obs − 0,5 do max(h_max_obs + 0,5, Max PP), zaokrąglone do 0,05."""
    m = products.meta
    return (round_param(m["h_min_obs"] - 0.5),
            round_param(max(m["h_max_obs"] + 0.5, products.max_pp)))


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
                       for s in products.scenes]})


def create_app(settings: Settings | None = None, products: Products | None = None, *,
               search_fn=None, load_fn=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.products is None:           # leniwe ładowanie: tylko gdy nie podano produktów
            app.state.products = load_products(settings.data_dir, settings.period)
        yield

    app = FastAPI(title="Mielizna API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.products = products
    app.state.cache = TTLStore()
    app.state.search_fn, app.state.load_fn = search_fn, load_fn

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

    return app


app = create_app()
