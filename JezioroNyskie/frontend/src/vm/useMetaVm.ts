import { useQuery } from '@tanstack/react-query';
import { api, type Meta } from '../api/client';
import { queryKeys } from './queryClient';

export interface MetaVm {
  status: 'loading' | 'error' | 'ready';
  meta?: Meta;
  slider?: { min: number; max: number; step: number; obsMin: number; obsMax: number; npp: number; maxPp: number };
  presets?: { label: string; draft: number }[];
  retry(): void;
}

export function useMetaVm(): MetaVm {
  const q = useQuery({ queryKey: queryKeys.meta(), queryFn: ({ signal }) => api.meta(signal) });
  const retry = () => void q.refetch();
  const meta = q.data;
  if (!meta) return { status: q.isError ? 'error' : 'loading', retry };
  return {
    status: 'ready',
    meta,
    slider: {
      min: meta.slider.min,
      max: meta.slider.max,
      step: meta.slider.step,
      obsMin: meta.h_min_obs,
      obsMax: meta.h_max_obs,
      npp: meta.npp,
      maxPp: meta.max_pp,
    },
    presets: meta.draft_presets.map((p) => ({ label: p.label, draft: p.draft })),
    retry,
  };
}
