// Wspólne dane testowe zgodne ze schematem API (wartości punktów jak w fixture backendu).
import type { CurrentLevel, Meta, Point, Scene, Zones, ZoneFeature } from '../api/client';

const corners: [number, number][] = [
  [17.0, 50.5],
  [17.1, 50.5],
  [17.1, 50.4],
  [17.0, 50.4],
];

export const meta: Meta = {
  model_version: 'testver00001',
  period: 'all',
  period_dates: ['2017-01-01', '2026-12-31'],
  n_scenes: 3,
  n_scenes_by_method: { B: 2, C: 1 },
  first_scene_date: '2025-04-12',
  last_scene_date: '2026-10-20',
  h_min_obs: 192.9,
  h_max_obs: 197.92,
  npp: 195.91,
  max_pp: 198.89,
  slider: { min: 192.4, max: 198.9, step: 0.05 },
  defaults: { h: 194.2, draft: 1.2, margin: 0.3 },
  limits: { draft: [0.1, 3.0], margin: [0, 1] },
  draft_presets: [
    { label: 'Omega', draft: 0.9 },
    { label: 'Sasanka 660 miecz w górze', draft: 0.4 },
    { label: 'Sasanka 660 miecz w dole', draft: 1.25 },
  ],
  presets_provisional: true,
  bbox_wgs84: [17.0, 50.4, 17.1, 50.5],
  crs: 'EPSG:2180',
  z_max_floor: 193.05,
  accuracy: { rf_oa: 0.8162, rf_ba: 0.7718, rf_kappa: 0.3731, otsu_ba: 0.7554, n_labels: 185 },
  area_level: {
    nodes_area_km2: [10.5, 12.0, 14.0],
    nodes_h: [192.9, 194.0, 197.0],
    rmse_loo: 0.4,
    rmse_loyo: 0.45,
    points: [
      { date: '2025-04-12', area_otsu_km2: 11.2, h_t: 193.6, h_method: 'B' },
      { date: '2026-09-30', area_otsu_km2: 11.8, h_t: 193.9, h_method: 'B' },
      { date: '2026-10-20', area_otsu_km2: 12.1, h_t: 194.2, h_method: 'B' },
    ],
  },
  layers: {
    bottom: {
      url: '/api/layers/bottom.png',
      coordinates: corners,
      breaks: [193.0, 193.6, 194.2, 194.8, 195.4, 196.0],
    },
    uncertainty: { url: '/api/layers/uncertainty.png', coordinates: corners, min_unc: 0.1 },
  },
};

const square = (x: number, y: number): number[][][] => [
  [[x, y], [x + 0.01, y], [x + 0.01, y - 0.01], [x, y - 0.01], [x, y]],
];

const feature = (zone: ZoneFeature['properties']['zone'], x: number): ZoneFeature => ({
  type: 'Feature',
  geometry: { type: 'Polygon', coordinates: square(x, 50.5) },
  properties: { zone },
});

/** Budowniczy odpowiedzi /api/zones: 3 obiekty, params = argumenty. */
export function zones(h: number, draft: number, margin: number): Zones {
  return {
    type: 'FeatureCollection',
    features: [feature('safe', 17.0), feature('risk', 17.02), feature('danger', 17.04)],
    stats: {
      water_km2: 12.0,
      safe_km2: 7.44,
      risk_km2: 2.76,
      danger_km2: 1.8,
      safe_pct: 62,
      risk_pct: 23,
      danger_pct: 15,
    },
    params: { h, draft, margin },
    warnings: [],
    model_version: 'testver00001',
  };
}

const base = { lon: 17.05, lat: 50.45, h: 195.0, draft: 1.2, margin: 0.3 };

export const pointModel: Point = {
  ...base,
  kind: 'model',
  zone: 'risk',
  depth_min: 1.0,
  depth_max: 2.0,
  clearance_min: -0.2,
  clearance_max: 0.8,
  z_min: 193.0,
  z_max: 194.0,
  z: 193.5,
  unc: 0.2,
  bottom_above_water_min: null,
  bottom_above_water_max: null,
  obs_count: 5,
};

export const pointAlwaysWater: Point = {
  ...base,
  kind: 'always_water',
  zone: 'safe',
  depth_min: 1.95,
  depth_max: null,
  clearance_min: 0.75,
  clearance_max: null,
  z_min: null,
  z_max: 193.05,
  z: 193.0,
  unc: 0.3,
  bottom_above_water_min: null,
  bottom_above_water_max: null,
  obs_count: 5,
};

export const pointLand: Point = {
  ...base,
  kind: 'land',
  zone: 'danger',
  depth_min: 0,
  depth_max: -1.0,
  clearance_min: null,
  clearance_max: -2.2,
  z_min: 196.0,
  z_max: null,
  z: 196.5,
  unc: 0.3,
  bottom_above_water_min: 1.0,
  bottom_above_water_max: null,
  obs_count: 5,
};

export const pointOutside: Point = {
  ...base,
  kind: 'outside',
  zone: null,
  depth_min: null,
  depth_max: null,
  clearance_min: null,
  clearance_max: null,
  z_min: null,
  z_max: null,
  z: null,
  unc: null,
  bottom_above_water_min: null,
  bottom_above_water_max: null,
  obs_count: null,
};

const scene = (date: string, h_t: number, area: number): Scene => ({
  date,
  h_t,
  h_sigma: 0.15,
  h_method: 'B',
  area_km2: area,
  area_otsu_km2: area - 0.2,
  otsu_threshold: 0.1,
  local_cloud_pct: 0.5,
  lake_nodata_pct: 0.1,
});

export const scenes: Scene[] = [
  scene('2025-04-12', 193.6, 11.4),
  scene('2026-09-30', 193.9, 12.0),
  scene('2026-10-20', 194.2, 12.3),
];

export const currentLevel: CurrentLevel = {
  source: 'pipeline',
  scene_date: '2026-10-20',
  acq_id: null,
  h: 194.2,
  h_sigma: 0.15,
  h_method: 'B',
  extrapolated: false,
  area_biased: false,
  ice_unverified: false,
  local_cloud_pct: 0.5,
  area_otsu_km2: 12.1,
  shoreline: null,
  computed_at: '2026-10-21T06:00:00+00:00',
  age_days: 1,
  stale: false,
  refreshing: false,
  last_checked: null,
  last_error: null,
};
