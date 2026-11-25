import { useQuery } from '@tanstack/react-query';
import { api, type KzDeep } from '../api/client';
import { queryKeys } from './queryClient';
import { gravelRetry } from './useGravelVm';

/** Powierzchnia „Dno wg mapy KŻ” i atrybucja z API. Pusta kolekcja, 404 lub błąd = brak warstwy, bez blokowania mapy. */
export function useKzDeepVm(): { kzDeep?: KzDeep; attribution?: string } {
  const q = useQuery({ queryKey: queryKeys.kzDeep(), queryFn: ({ signal }) => api.kzDeep(signal), retry: gravelRetry });
  const data = q.data && q.data.features.length > 0 ? q.data : undefined;
  return { kzDeep: data, attribution: data?.features[0]?.properties.attribution };
}
