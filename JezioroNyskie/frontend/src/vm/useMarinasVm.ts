import { useQuery } from '@tanstack/react-query';
import { api, type Marinas } from '../api/client';
import { queryKeys } from './queryClient';

/** Przystanie i slipy z OSM; dane bez filtrowania, warstwa jest dodatkiem i jej błąd nie blokuje mapy. */
export function useMarinasVm(): { marinas?: Marinas } {
  const q = useQuery({ queryKey: queryKeys.marinas(), queryFn: ({ signal }) => api.marinas(signal) });
  return { marinas: q.data };
}
