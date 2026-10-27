"""Kontrakt API (modele pydantic v2) - źródło `openapi.json` dla frontu.

Co robi: opisuje kształt odpowiedzi `/api/meta`, `/api/zones`, `/api/point`, `/api/scenes` i `/api/capacity-to-level` / `/api/level-to-capacity`
  (kolejne zadania dopisują swoje modele).
Dlaczego tak: front (React) generuje typy TypeScript z `openapi.json`, więc kontrakt ma być jawny i
  ścisły. Pola, które mogą być nieskończone lub NaN, mają typ `float | None` i serializują się jako
  `null` - JSON nigdy nie zawiera `NaN`/`Infinity`. Cechy GeoJSON niosą dodatkowe klucze (`id`, `bbox`),
  dlatego typujemy je luźno (`dict[str, Any]`).
Wejście → wyjście: słowniki z `app.main` → walidowane modele → JSON.
Jak to obronić: zmiana modelu zmienia `openapi.json`, a test migawki wymusza jej świadome odświeżenie
  (`uv run python scripts/export_openapi.py`).
"""
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


class ZonesResponse(BaseModel):
    type: str
    features: list[dict[str, Any]]
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


class MetaResponse(BaseModel):
    model_version: str
    period: str
    period_dates: list[str]
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


class CapacityToLevel(BaseModel):
    v: float
    h: float | None
    in_table: bool


class LevelToCapacity(BaseModel):
    h: float
    v: float | None
    in_table: bool
