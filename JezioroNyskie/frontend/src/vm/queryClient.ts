// Klient TanStack Query i klucze zapytań. Klucze zawierają już zaokrąglone parametry (round05),
// więc każdy zestaw parametrów ma własny wpis w cache i spóźniona odpowiedź nie nadpisze nowszej.
import { QueryClient } from '@tanstack/react-query';
import type { ZoneParams } from '../api/client';

export function createQueryClient(opts: { retry?: number | false } = {}): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: opts.retry ?? 1, staleTime: 5 * 60 * 1000 } },
  });
}

export const queryClient = createQueryClient();

/** Współrzędne do 6 miejsc (~0,1 m), żeby szum zmiennoprzecinkowy nie mnożył wpisów w cache. */
const r6 = (x: number) => Number(x.toFixed(6));

export const queryKeys = {
  meta: () => ['meta'] as const,
  zones: (p: ZoneParams) => ['zones', p.h, p.draft, p.margin] as const,
  point: (lon: number, lat: number, p: ZoneParams) =>
    ['point', r6(lon), r6(lat), p.h, p.draft, p.margin] as const,
  scenes: () => ['scenes'] as const,
  shoreline: (date: string) => ['shoreline', date] as const,
  marinas: () => ['marinas'] as const,
  currentLevel: () => ['current-level'] as const,
  capacity: (v: number) => ['capacity', v] as const,
  levelCapacity: (h: number) => ['level-capacity', h] as const,
};
