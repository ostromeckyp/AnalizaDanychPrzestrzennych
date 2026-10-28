import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { fmtM, round05 } from '../format';
import { queryKeys } from './queryClient';
import { useDebounced } from './useDebounced';
import { useMetaVm } from './useMetaVm';

export interface CapacityVm {
  hFromCapacity?: number;
  capacityAtLevel?: number;
  aboveNpp?: string;
  /** Czy wartość mieści się w tabeli pojemności (inaczej to ekstrapolacja/brak). */
  inTable?: boolean;
}

/** `capacity`: input = V (mln m³) → poziom; `level`: input = h (m n.p.m.) → pojemność. */
export function useCapacityVm(mode: 'level' | 'capacity', input: number): CapacityVm {
  const rounded = round05(input);
  const value = useDebounced(rounded, 250);
  const valid = Number.isFinite(value);
  const { slider } = useMetaVm();

  const cap = useQuery({
    queryKey: queryKeys.capacity(value),
    queryFn: ({ signal }) => api.capacityToLevel(value, signal),
    enabled: valid && mode === 'capacity',
  });
  const lvl = useQuery({
    queryKey: queryKeys.levelCapacity(value),
    queryFn: ({ signal }) => api.levelToCapacity(value, signal),
    enabled: valid && mode === 'level',
  });

  if (!valid) return {};
  if (mode === 'capacity') {
    return { hFromCapacity: cap.data?.h ?? undefined, inTable: cap.data?.in_table };
  }
  let aboveNpp: string | undefined;
  if (slider) {
    const diff = value - slider.npp;
    aboveNpp = `${fmtM(Math.abs(round05(diff)))} ${diff >= 0 ? 'powyżej' : 'poniżej'} NPP`;
  }
  return { capacityAtLevel: lvl.data?.v ?? undefined, aboveNpp, inTable: lvl.data?.in_table };
}
