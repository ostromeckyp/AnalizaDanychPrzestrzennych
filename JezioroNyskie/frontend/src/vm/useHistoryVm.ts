import { useQueries, useQuery } from '@tanstack/react-query';
import { useCallback, useMemo, useState } from 'react';
import { api, type Scene, type Shoreline } from '../api/client';
import type { SceneRow, YearFilter } from '../components/history/types';
import { fmtDate, fmtKm2, fmtLevel, fmtNum, plScenes, round05 } from '../format';
import { levelColor } from '../theme';
import { queryKeys } from './queryClient';
import { useMetaVm } from './useMetaVm';

export interface HistoryVm {
  status: 'loading' | 'error' | 'ready';
  retry(): void;
  years: number[];
  year: YearFilter;
  /** Sceny po filtrze roku, od najnowszej. */
  scenes: SceneRow[];
  /** Wszystkie sceny (wykres), od najstarszej. */
  allScenes: SceneRow[];
  overlay: string[];
  selected?: SceneRow;
  shorelines: { type: 'FeatureCollection'; features: Shoreline[] };
  counter: string;
  npp?: number;
  bbox?: [number, number, number, number];
  setYear(y: YearFilter): void;
  toggleOverlay(date: string): void;
  select(date: string): void;
}

type OverlayInfo = { features: Shoreline[]; status: Record<string, 'loading' | 'error'> };
const NONE: Shoreline[] = [];

function toRow(s: Scene, npp: number | undefined): SceneRow | null {
  // Scena bez poziomu nie ma koloru ani miejsca na wykresie.
  if (s.h_t == null) return null;
  const cloud = s.local_cloud_pct;
  return {
    date: s.date,
    dateLabel: fmtDate(s.date),
    h: s.h_t,
    level: fmtLevel(s.h_t),
    area: s.area_km2 == null ? '—' : fmtKm2(s.area_km2),
    source: cloud == null ? 'Sentinel-2' : `Sentinel-2 · zachm. ${fmtNum(cloud, 1)}%`,
    color: levelColor(s.h_t),
    dashed: npp != null && s.h_t < npp,
    // Poziom zaokrąglony do 0,05, jak wszędzie w zapytaniach o strefy.
    mapHref: `/?h=${round05(s.h_t)}`,
  };
}

export function useHistoryVm(): HistoryVm {
  const metaVm = useMetaVm();
  const npp = metaVm.slider?.npp;
  const q = useQuery({ queryKey: queryKeys.scenes(), queryFn: ({ signal }) => api.scenes(signal) });

  const refetch = q.refetch;
  const [yearSel, setYearSel] = useState<YearFilter | undefined>();
  const [overlay, setOverlay] = useState<string[]>([]);
  const [selDate, setSelDate] = useState<string | undefined>();

  const all = useMemo(() => {
    const rows = (q.data ?? []).flatMap((s) => toRow(s, npp) ?? []);
    return rows.sort((a, b) => (a.date < b.date ? 1 : -1)); // najnowsze pierwsze
  }, [q.data, npp]);

  // Pełny zakres lat (także bez scen), żeby pusty rok dało się wybrać (stan F).
  const years = useMemo(() => {
    if (all.length === 0) return [];
    const ys = all.map((r) => Number(r.date.slice(0, 4)));
    const out: number[] = [];
    for (let y = Math.max(...ys); y >= Math.min(...ys); y--) out.push(y);
    return out;
  }, [all]);
  const year: YearFilter = yearSel ?? years[0] ?? 'all';

  const filtered = useMemo(
    () => (year === 'all' ? all : all.filter((r) => Number(r.date.slice(0, 4)) === year)),
    [all, year],
  );

  // Stabilna funkcja: wynik zmienia tożsamość tylko, gdy zmienią się dane.
  const combine = useCallback(
    (results: { data?: Shoreline; isError: boolean }[]): OverlayInfo => {
      const features: Shoreline[] = [];
      const status: OverlayInfo['status'] = {};
      results.forEach((r, i) => {
        if (r.data) features.push(r.data);
        else status[overlay[i]] = r.isError ? 'error' : 'loading';
      });
      return { features, status };
    },
    [overlay],
  );

  const info = useQueries({
    queries: overlay.map((date) => ({
      queryKey: queryKeys.shoreline(date),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.shoreline(date, signal),
    })),
    combine,
  });

  const shorelines = useMemo(
    () => ({ type: 'FeatureCollection' as const, features: info.features.length ? info.features : NONE }),
    [info.features],
  );

  const scenes = useMemo(
    () => filtered.map((r) => (info.status[r.date] ? { ...r, overlayStatus: info.status[r.date] } : r)),
    [filtered, info.status],
  );
  const selected = scenes.find((r) => r.date === selDate) ?? scenes[0];

  return {
    status: q.isError ? 'error' : q.data ? 'ready' : 'loading',
    retry: useCallback(() => void refetch(), [refetch]),
    years,
    year,
    scenes,
    allScenes: useMemo(() => [...all].reverse(), [all]),
    overlay,
    selected,
    shorelines,
    counter: `${plScenes(filtered.length)} · nałożone: ${overlay.length}`,
    npp,
    bbox: metaVm.meta?.bbox_wgs84 as HistoryVm['bbox'],
    setYear: setYearSel,
    toggleOverlay: (date) =>
      setOverlay((o) => (o.includes(date) ? o.filter((d) => d !== date) : [...o, date])),
    select: setSelDate,
  };
}
