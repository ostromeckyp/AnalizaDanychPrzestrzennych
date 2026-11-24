import { useQuery } from '@tanstack/react-query';
import { api, type HazardFeature, type Hazards } from '../api/client';
import type { HazardPopupModel } from '../components/popup/types';
import { fmtM, fmtNum } from '../format';
import { queryKeys } from './queryClient';

const NBSP = ' ';

/** Przeszkody z locji KŻ Nysa i atrybucja z API. Pusta odpowiedź lub błąd = brak warstwy, bez blokowania mapy. */
export function useHazardsVm(): { hazards?: Hazards; attribution?: string } {
  const q = useQuery({ queryKey: queryKeys.hazards(), queryFn: ({ signal }) => api.hazards(signal) });
  const data = q.data && q.data.features.length > 0 ? q.data : undefined;
  return { hazards: data, attribution: data?.source || undefined };
}

/** Czysta funkcja: cecha z API + bieżący poziom wody h → model popupu. Bez skończonego h pomijamy położenie względem wody. */
export function toHazardPopupModel(f: HazardFeature, h: number): HazardPopupModel {
  const p = f.properties;
  const diff = Math.abs(p.z - h);
  return {
    title: p.name,
    level: `Rzędna ${p.z_kind}: ${fmtNum(p.z, 1)}${NBSP}m n.p.m.`,
    relation: Number.isFinite(h)
      ? p.z < h
        ? { kind: 'under', text: `pod wodą: ${fmtM(diff)}` }
        : { kind: 'over', text: `nad wodą: ${fmtM(diff)}` }
      : undefined,
    description: p.description,
    note: p.note || undefined,
    sourceLabel: 'Źródło: Locja KŻ Nysa',
    sourceUrl: p.source_url,
    disclaimer: 'Położenie orientacyjne, nie znak nawigacyjny.',
  };
}
