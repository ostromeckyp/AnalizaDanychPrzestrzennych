import { useQuery } from '@tanstack/react-query';
import { ApiError, api, type Gravel } from '../api/client';
import { queryKeys } from './queryClient';

/** Brak pliku obrysu (404) jest stanem stałym: bez ponowień; inne błędy ponawiamy najwyżej dwa razy. */
export const gravelRetry = (failures: number, err: unknown) =>
  !(err instanceof ApiError && err.status === 404) && failures < 2;

/** Obrys żwirowni (dno zmienne) i atrybucja z API. 404 (brak pliku) lub błąd = brak warstwy, bez blokowania mapy. */
export function useGravelVm(): { gravel?: Gravel; attribution?: string } {
  const q = useQuery({ queryKey: queryKeys.gravel(), queryFn: ({ signal }) => api.gravel(signal), retry: gravelRetry });
  const data = q.data;
  return { gravel: data, attribution: data?.features[0]?.properties.attribution };
}
