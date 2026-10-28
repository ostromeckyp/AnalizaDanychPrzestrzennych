import { useQuery } from '@tanstack/react-query';
import { api, type Gravel } from '../api/client';
import { queryKeys } from './queryClient';

/** Obrys żwirowni (dno zmienne) i atrybucja z API. 404 (brak pliku) lub błąd = brak warstwy, bez blokowania mapy. */
export function useGravelVm(): { gravel?: Gravel; attribution?: string } {
  const q = useQuery({ queryKey: queryKeys.gravel(), queryFn: ({ signal }) => api.gravel(signal), retry: false });
  const data = q.data;
  return { gravel: data, attribution: data?.features[0]?.properties.attribution };
}
