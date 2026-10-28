"""Kontrakt API (modele pydantic v2) - źródło `openapi.json` dla frontu.

Co robi: opisuje kształt odpowiedzi `/api/meta`, `/api/zones`, `/api/point`, `/api/scenes` i `/api/capacity-to-level` / `/api/level-to-capacity`, w `/api/meta` także adresy warstw obrazów
  (kolejne zadania dopisują swoje modele).
Dlaczego tak: front (React) generuje typy TypeScript z `openapi.json`, więc kontrakt ma być jawny i
  ścisły. Pola, które mogą być nieskończone lub NaN, mają typ `float | None` i serializują się jako
  `null` - JSON nigdy nie zawiera `NaN`/`Infinity`. Cechy GeoJSON niosą dodatkowe klucze (`id`, `bbox`),
  dlatego `GeoFeature` ma opcjonalne `id` i `bbox`, a geometria to luźne `dict[str, Any]`
  (typy GeoJSON dla stref, linii brzegowej i przystani dzielą jedną bazę).
Wejście → wyjście: słowniki z `app.main` → walidowane modele → JSON.
Jak to obronić: zmiana modelu zmienia `openapi.json`, a test migawki wymusza jej świadome odświeżenie
  (`uv run python scripts/export_openapi.py`).
"""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel


class Params(BaseModel):
    h: float
    draft: float
    margin: float


class ZoneStats(BaseModel):
    water_km2: float
    safe_km2: float
    risk_km2: float
    danger_km2: float
    safe_pct: float
    risk_pct: float
    danger_pct: float


class GeoFeature(BaseModel):
    """Cecha GeoJSON (RFC 7946): wspólna baza dla stref, linii brzegowej i przystani."""
    type: Literal["Feature"]
    geometry: dict[str, Any]
    id: str | int | None = None
    bbox: list[float] | None = None


class ZoneProperties(BaseModel):
    zone: Literal["safe", "risk", "danger"]


class ZoneFeature(GeoFeature):
    properties: ZoneProperties


class MarinaProperties(BaseModel):
    osm_id: int | None
    kind: str | None
    name: str | None


class MarinaFeature(GeoFeature):
    properties: MarinaProperties


class MarinasResponse(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[MarinaFeature]


class ZonesResponse(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[ZoneFeature]
    stats: ZoneStats
    params: Params
    warnings: list[str]
    model_version: str


class Slider(BaseModel):
    min: float
    max: float
    step: float


class Limits(BaseModel):
    draft: tuple[float, float]
    margin: tuple[float, float]


class DraftPreset(BaseModel):
    label: str
    draft: float


class Accuracy(BaseModel):
    rf_oa: float | None
    rf_ba: float | None
    rf_kappa: float | None
    otsu_ba: float | None
    n_labels: int | None
    # Ocena dna vs NMT LiDAR: zbiorczo po epokach NMT, dla okresu modelu faktycznie serwowanego
    # (`model_period`); null, gdy brak pliku oceny albo bloku zbiorczego dla tego okresu.
    bottom_rmse_nmt: float | None = None
    bottom_bias_nmt: float | None = None
    bottom_in_bounds_nmt: float | None = None
    kz_rmse: float | None = None             # zgodność z punktami mapy KŻ (null do czasu `eval/kz_compare.json`)
    kz_bias: float | None = None
    levels_mae_ab: float | None = None       # średni błąd bezwzględny |A − B| poziomu wody
    # Udział scen z |D − (A/B/R/C)| ≤ 0,2 m - TYLKO w dziedzinie wariantu D (sceny z h_t < h_max_valid),
    # a nie dokładność całej populacji.
    variant_d_within_0_2: float | None = None


class AreaLevelPoint(BaseModel):
    date: str
    area_otsu_km2: float | None
    h_t: float | None
    h_method: str | None


class AreaLevel(BaseModel):
    nodes_area_km2: list[float | None]
    nodes_h: list[float | None]
    rmse_loo: float | None
    rmse_loyo: float | None
    points: list[AreaLevelPoint]


class BottomLayer(BaseModel):
    url: str
    coordinates: list[tuple[float, float]]   # 4 narożniki [lon, lat]: LG, PG, PD, LD
    breaks: list[float]                      # 6 progów klas dna [m n.p.m.]


class UncertaintyLayer(BaseModel):
    url: str
    coordinates: list[tuple[float, float]]
    min_unc: float                           # od tej niepewności [m] rysowana jest kropka


class Layers(BaseModel):
    bottom: BottomLayer
    uncertainty: UncertaintyLayer


class MetaResponse(BaseModel):
    model_version: str
    period: str
    period_dates: list[str]
    model_period: Literal["all", "pre_flood", "post_flood"]
    model_period_reason: str
    n_scenes: int
    n_scenes_by_method: dict[str, int]
    first_scene_date: str | None
    last_scene_date: str | None
    h_min_obs: float
    h_max_obs: float
    npp: float
    max_pp: float
    slider: Slider
    defaults: Params
    limits: Limits
    draft_presets: list[DraftPreset]
    presets_provisional: bool
    bbox_wgs84: tuple[float, float, float, float]
    crs: str
    z_max_floor: float
    accuracy: Accuracy
    area_level: AreaLevel
    layers: Layers


class PointResponse(BaseModel):
    kind: Literal["model", "always_water", "land", "outside"]
    lon: float
    lat: float
    h: float
    draft: float
    margin: float
    zone: Literal["safe", "risk", "danger"] | None
    depth_min: float | None
    depth_max: float | None
    clearance_min: float | None
    clearance_max: float | None
    z_min: float | None
    z_max: float | None
    z: float | None
    unc: float | None
    bottom_above_water_min: float | None
    bottom_above_water_max: float | None
    obs_count: int | None
    gravel: bool                    # punkt w obrysie żwirowni: dno zmienne, model może być nieaktualny


class GravelProperties(BaseModel):
    source: str
    attribution: str


class GravelFeature(GeoFeature):
    properties: GravelProperties


class GravelResponse(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[GravelFeature]


class SceneOut(BaseModel):
    date: str
    h_t: float | None
    h_sigma: float | None
    h_method: str | None
    area_km2: float | None          # powierzchnia z RF - ta sama co linia brzegowa
    area_otsu_km2: float | None     # powierzchnia Otsu (używana przez krzywą powierzchnia↔poziom)
    otsu_threshold: float | None
    local_cloud_pct: float | None
    lake_nodata_pct: float | None


class ShorelineFeature(GeoFeature):
    properties: SceneOut


class CapacityToLevel(BaseModel):
    v: float
    h: float | None
    in_table: bool


class LevelToCapacity(BaseModel):
    h: float
    v: float | None
    in_table: bool


class BulletinLatest(BaseModel):
    bulletin_date: date
    reading_utc: str | None
    v_current: float
    h: float | None              # rzędna z tabeli KŻ (jak /api/capacity-to-level); None poza tabelą
    in_table: bool
    v_npp: float | None
    url: str
    fetched_at: datetime
    stale: bool
    source: Literal["govpl", "pipeline"]
    refreshing: bool             # trwa pobieranie w tle: kolejne zapytanie za kilka sekund da nowszy wynik


class CurrentLevelResponse(BaseModel):
    source: Literal["satellite", "pipeline"]
    scene_date: str
    acq_id: str | None
    h: float
    h_sigma: float
    h_method: str
    extrapolated: bool
    area_biased: bool
    ice_unverified: bool
    local_cloud_pct: float | None
    area_otsu_km2: float | None
    shoreline: dict | None
    computed_at: str
    age_days: int
    stale: bool
    refreshing: bool
    last_checked: str | None
    last_error: str | None
