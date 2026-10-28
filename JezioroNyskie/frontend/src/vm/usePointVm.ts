import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { api, type Meta, type Point, type ZoneParams } from '../api/client';
import type { PopupModel, ZoneKey } from '../components/popup/types';
import { fmtLevel, fmtM, fmtNum, plScenes, round05 } from '../format';
import { queryKeys } from './queryClient';
import { useDebounced } from './useDebounced';
import { useMetaVm } from './useMetaVm';

export type PointStatus = 'idle' | 'loading' | 'ready' | 'error';
export interface PointVm {
  popup?: PopupModel;
  status: PointStatus;
}

const GRAVEL_TERM = 'Dno zmienne (eksploatacja kruszywa)';
const NBSP = '\u00a0';
const ZONE_NAMES: Record<ZoneKey, string> = { safe: 'Bezpieczna', risk: 'Ryzykowna', danger: 'Zbyt płytka / ląd' };

// Każda liczba z API może być null (a zepsuty backend da NaN); brakujące wiersze po prostu pomijamy.
const num = (x: number | null | undefined): x is number => typeof x === 'number' && Number.isFinite(x);

// Przedział [z_min, z_max] zawiera teren w ok. 6 % pikseli kontrolnych (raport §5.2) — żeglarz musi to wiedzieć przy zakresie.
const RANGE_CAVEAT = 'Zakres głębokości jest orientacyjny — nie jest przedziałem ufności.';

const range = (a: number, b: number) => (a === b ? fmtM(a) : `${fmtNum(a, 2)}–${fmtNum(b, 2)}${NBSP}m`);

function zoneOf(p: Point, withLabel: boolean): PopupModel['zone'] {
  if (!p.zone) return undefined;
  return { key: p.zone, name: ZONE_NAMES[p.zone], label: withLabel ? `dla jachtu ${fmtM(p.draft)}` : '' };
}

function clearanceNote(p: Point): string | undefined {
  const { clearance_min: lo, clearance_max: hi } = p;
  const margin = `wymagany zapas ${fmtM(p.margin)}`;
  let keel: string;
  if (num(lo) && num(hi) && lo >= 0) keel = `Pod kilem ${fmtNum(lo, 2)} do ${fmtM(hi)}`;
  else if (num(hi) && hi >= 0) keel = `Pod kilem co najwyżej ${fmtM(hi)}`;
  else if (num(hi)) keel = 'Zanurzenie większe niż głębokość';
  else return undefined;
  return `${keel} · ${margin}`;
}

const location = (p: Point) => ({
  term: 'Położenie',
  desc: `${fmtNum(p.lat, 4)}° N, ${fmtNum(p.lon, 4)}° E`,
});

function scenes(p: Point) {
  return num(p.obs_count) ? [{ term: 'Obserwacje satelitarne', desc: plScenes(p.obs_count) }] : [];
}

function heightRow(term: string, p: Point) {
  if (!num(p.z)) return [];
  return [{ term, desc: `${fmtLevel(p.z)}${num(p.unc) ? ` ± ${fmtNum(p.unc, 2)}` : ''}` }];
}

/** Czysta funkcja: odpowiedź /api/point + meta → model popupu (§16.7). Strefa zawsze z API. */
export function toPopupModel(p: Point, meta: Meta): PopupModel {
  const model = baseModel(p, meta);
  if (!p.gravel) return model;
  return { ...model, rows: [...model.rows, { term: GRAVEL_TERM, desc: 'model może być nieaktualny.', warning: true }] };
}

function baseModel(p: Point, meta: Meta): PopupModel {
  switch (p.kind) {
    case 'model': {
      const { depth_min: lo, depth_max: hi } = p;
      const depth = num(lo) && num(hi) ? range(lo, hi) : undefined;
      return {
        variant: 'A',
        title: 'Głębokość w tym miejscu',
        value: depth ?? 'Brak oceny głębokości',
        note: clearanceNote(p),
        zone: zoneOf(p, true),
        rows: [...heightRow('Wysokość dna', p), ...scenes(p), location(p)],
        ...(depth ? { caveat: RANGE_CAVEAT } : {}),
      };
    }
    case 'always_water': {
      const floor = num(p.z_max) ? p.z_max : meta.z_max_floor;
      return {
        variant: 'B',
        title: 'Głębokość w tym miejscu',
        value: num(p.depth_min) ? `≥ ${fmtM(p.depth_min)}` : 'Głęboko',
        note: `${num(p.depth_min) ? `Głębiej niż ${fmtM(p.depth_min)}` : 'Głęboko'} (poniżej najniższego zaobserwowanego stanu ${fmtLevel(meta.h_min_obs)}).`,
        zone: zoneOf(p, true),
        rows: [
          ...(num(floor) ? [{ term: 'Wysokość dna', desc: `< ${fmtLevel(floor)}` }] : []),
          { term: 'Obserwacje satelitarne', desc: 'brak (zawsze woda)' },
          location(p),
        ],
      };
    }
    case 'land': {
      const { bottom_above_water_min: lo, bottom_above_water_max: hi } = p;
      let note: string;
      if (num(lo) && num(hi)) note = `Dno ${range(lo, hi)} powyżej lustra wody przy ${fmtLevel(p.h)}`;
      else if (num(lo)) note = `Dno co najmniej ${fmtM(lo)} powyżej lustra wody`;
      else note = `Dno powyżej lustra wody przy ${fmtLevel(p.h)}`;
      return {
        variant: 'C',
        title: 'W tym miejscu',
        value: 'Ląd',
        note,
        zone: zoneOf(p, false),
        rows: [...heightRow('Wysokość terenu', p), ...scenes(p), location(p)],
      };
    }
    default:
      return {
        variant: 'D',
        title: 'W tym miejscu',
        value: 'Poza obszarem modelu',
        note: `Model obejmuje czaszę zbiornika do rzędnej Max PP ${fmtLevel(meta.max_pp)} Tutaj nie ma danych o dnie.`,
        noZone: 'Bez oceny strefy',
        rows: [],
      };
  }
}

export function usePointVm(pin: { lon: number; lat: number } | undefined, input: ZoneParams): PointVm {
  const { meta } = useMetaVm();
  const rh = round05(input.h);
  const rd = round05(input.draft);
  const rm = round05(input.margin);
  const rounded = useMemo(() => ({ h: rh, draft: rd, margin: rm }), [rh, rd, rm]);
  const params = useDebounced(rounded, 250);
  const lon = pin ? Number(pin.lon.toFixed(6)) : NaN;
  const lat = pin ? Number(pin.lat.toFixed(6)) : NaN;
  const enabled = !!pin && [params.h, params.draft, params.margin].every(Number.isFinite);

  const q = useQuery({
    queryKey: queryKeys.point(lon, lat, params),
    queryFn: ({ signal }) => api.point({ lon, lat, ...params }, signal),
    enabled,
    // Po zmianie parametrów stary popup zostaje do odpowiedzi, ale tylko dla tego samego punktu.
    placeholderData: (prev, prevQuery) =>
      prevQuery && prevQuery.queryKey[1] === lon && prevQuery.queryKey[2] === lat ? prev : undefined,
  });

  if (!pin) return { status: 'idle' };
  if (q.isError) return { status: 'error' };
  if (!q.data || !meta) return { status: 'loading' };
  return { popup: toPopupModel(q.data, meta), status: q.isPlaceholderData ? 'loading' : 'ready' };
}
