import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { fmtDate } from '../format';
import { queryKeys } from './queryClient';

const REFRESH_MS = 30 * 60 * 1000;

export interface CurrentLevelVm {
  level?: { h: number; label: string; note?: string };
  status: 'loading' | 'error' | 'ready';
}

export function useCurrentLevelVm(): CurrentLevelVm {
  const q = useQuery({
    queryKey: queryKeys.currentLevel(),
    queryFn: ({ signal }) => api.currentLevel(signal),
    refetchInterval: REFRESH_MS,
  });
  const d = q.data;
  if (!d) return { status: q.isError ? 'error' : 'loading' };

  const fromSatellite = d.source === 'satellite' || d.h_method === 'C';
  const label = `poziom z ${fmtDate(d.scene_date)}, ${fromSatellite ? 'wyznaczony z obrazu satelitarnego' : 'z komunikatu RZGW'}`;
  const notes: string[] = [];
  if (d.ice_unverified) notes.push('możliwy lód — poziom niezweryfikowany');
  if (d.stale) notes.push('ostatnia znana wartość');
  return { status: 'ready', level: { h: d.h, label, note: notes.length ? notes.join(' · ') : undefined } };
}
