import { keepPreviousData, onlineManager, useQuery } from '@tanstack/react-query';
import { useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { api, type ZoneParams, type Zones } from '../api/client';
import { fmtLevel, fmtM, fmtPct, round05 } from '../format';
import { queryKeys } from './queryClient';
import { useDebounced } from './useDebounced';

export type ZonesStatus = 'first-load' | 'ready' | 'recalculating' | 'error' | 'offline';

export interface ZonesVm {
  zones?: Zones;
  summary?: string;
  status: ZonesStatus;
  lastOkAt?: Date;
  lastOkParams?: ZoneParams;
  warnings: string[];
  /** Trwa ponowienie po błędzie (status zostaje `error` do sukcesu). */
  isRetrying: boolean;
  retry(): void;
}

export const DEBOUNCE_MS = 250;

const useOnline = () =>
  useSyncExternalStore(
    (cb) => onlineManager.subscribe(cb),
    () => onlineManager.isOnline(),
  );

export function useZonesVm(input: ZoneParams): ZonesVm {
  // Zaokrąglenie przed debounce: drobne ruchy suwaka w obrębie tego samego kroku nic nie zmieniają.
  // Memo po zaokrąglonych liczbach: ruch poniżej kroku nie tworzy nowego obiektu, więc nie ma fałszywego „przeliczam”.
  const rh = round05(input.h);
  const rd = round05(input.draft);
  const rm = round05(input.margin);
  const rounded = useMemo(() => ({ h: rh, draft: rd, margin: rm }), [rh, rd, rm]);
  const params = useDebounced(rounded, DEBOUNCE_MS);
  const valid = [params.h, params.draft, params.margin].every(Number.isFinite);

  const q = useQuery({
    queryKey: queryKeys.zones(params),
    queryFn: ({ signal }) => api.zones(params, signal),
    enabled: valid,
    placeholderData: keepPreviousData,
  });
  const online = useOnline();
  // Przy nowym kluczu TanStack zrzuca stan błędu na czas refetchu, więc „ponawiam” trzymamy sami.
  const [retrying, setRetrying] = useState(false);

  // Ostatnie poprawne strefy: po błędzie nowego klucza TanStack nie zwraca już danych poprzedniego.
  const lastOk = useRef<{ zones: Zones; at: Date } | undefined>(undefined);
  if (q.data && !q.isPlaceholderData && lastOk.current?.zones !== q.data) {
    lastOk.current = { zones: q.data, at: new Date(q.dataUpdatedAt) };
  }

  const zones = q.data ?? lastOk.current?.zones;
  const pending = params !== rounded; // debounce jeszcze trwa
  let status: ZonesStatus;
  if (!online) status = 'offline';
  else if (q.isError || retrying) status = 'error';
  else if (!zones) status = 'first-load';
  else if (q.isPlaceholderData || pending) status = 'recalculating';
  else status = 'ready';

  // Podsumowanie z parametrów pokazywanych stref, żeby zawsze zgadzało się z mapą.
  const summary = zones
    ? `Jacht ${fmtM(zones.params.draft)} · poziom ${fmtLevel(zones.params.h)} · bezpieczne ${fmtPct(Math.round(zones.stats.safe_pct))} akwenu`
    : undefined;

  return {
    zones,
    summary,
    status,
    lastOkAt: lastOk.current?.at,
    lastOkParams: lastOk.current?.zones.params,
    warnings: zones?.warnings ?? [],
    isRetrying: retrying,
    retry: () => {
      setRetrying(true);
      void q.refetch().finally(() => setRetrying(false));
    },
  };
}
