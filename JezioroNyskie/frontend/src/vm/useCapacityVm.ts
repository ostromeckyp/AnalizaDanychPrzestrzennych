import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { ApiError, api } from '../api/client';
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
  // Debounce pary (tryb, wartość): stara wartość nie może trafić do zapytania nowego trybu.
  const debounced = useDebounced(
    useMemo(() => ({ mode, v: rounded }), [mode, rounded]),
    250,
  );
  const value = debounced.v;
  const settled = debounced.mode === mode;
  const valid = Number.isFinite(value) && settled;
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
    // Bez migania przy kroku suwaka; placeholder dotyczy tylko tego samego trybu.
    placeholderData: keepPreviousData,
  });

  if (!valid) return {};
  if (mode === 'capacity') {
    // Odrzucenie 4xx (wartość poza zakresem API) traktujemy jak „poza tabelą”.
    const rejected = cap.error instanceof ApiError && cap.error.status >= 400 && cap.error.status < 500;
    return { hFromCapacity: cap.data?.h ?? undefined, inTable: rejected ? false : cap.data?.in_table };
  }
  let aboveNpp: string | undefined;
  if (slider) {
    const diff = round05(value - slider.npp);
    aboveNpp =
      diff === 0 ? 'na poziomie NPP' : `${fmtM(Math.abs(diff))} ${diff > 0 ? 'powyżej' : 'poniżej'} NPP`;
  }
  return { capacityAtLevel: lvl.data?.v ?? undefined, aboveNpp, inTable: lvl.data?.in_table };
}
