// Klient API: czyste funkcje fetch. Tylko warstwa vm/ ma z niego korzystać (test architektury).
import type { components } from './schema';

type S = components['schemas'];
export type Meta = S['MetaResponse'];
export type Zones = S['ZonesResponse'];
export type ZoneFeature = S['ZoneFeature'];
export type Point = S['PointResponse'];
export type Scene = S['SceneOut'];
export type Shoreline = S['ShorelineFeature'];
export type Marinas = S['MarinasResponse'];
export type Gravel = S['GravelResponse'];
export type CurrentLevel = S['CurrentLevelResponse'];
export type BulletinLatest = S['BulletinLatest'];
export type CapacityToLevel = S['CapacityToLevel'];
export type LevelToCapacity = S['LevelToCapacity'];

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(`API ${status}`);
    this.name = 'ApiError';
  }
}

export interface ZoneParams {
  h: number;
  draft: number;
  margin: number;
}

async function get<T>(path: string, params?: Record<string, number | string>, signal?: AbortSignal): Promise<T> {
  // String(number) daje kropkę dziesiętną niezależnie od ustawień przeglądarki.
  const qs = params
    ? '?' + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()
    : '';
  const res = await fetch(`${path}${qs}`, { signal });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json())?.detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  meta: (signal?: AbortSignal) => get<Meta>('/api/meta', undefined, signal),
  zones: (p: ZoneParams, signal?: AbortSignal) => get<Zones>('/api/zones', { ...p }, signal),
  point: (p: ZoneParams & { lon: number; lat: number }, signal?: AbortSignal) =>
    get<Point>('/api/point', { lon: p.lon, lat: p.lat, h: p.h, draft: p.draft, margin: p.margin }, signal),
  scenes: (signal?: AbortSignal) => get<Scene[]>('/api/scenes', undefined, signal),
  shoreline: (date: string, signal?: AbortSignal) => get<Shoreline>('/api/shorelines', { date }, signal),
  marinas: (signal?: AbortSignal) => get<Marinas>('/api/marinas', undefined, signal),
  gravel: (signal?: AbortSignal) => get<Gravel>('/api/gravel', undefined, signal),
  currentLevel: (signal?: AbortSignal) => get<CurrentLevel>('/api/current-level', undefined, signal),
  bulletinLatest: (signal?: AbortSignal) => get<BulletinLatest>('/api/bulletin/latest', undefined, signal),
  capacityToLevel: (v: number, signal?: AbortSignal) => get<CapacityToLevel>('/api/capacity-to-level', { v }, signal),
  levelToCapacity: (h: number, signal?: AbortSignal) => get<LevelToCapacity>('/api/level-to-capacity', { h }, signal),
};
