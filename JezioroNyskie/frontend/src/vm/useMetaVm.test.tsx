import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { meta } from '../test/fixtures';
import { createQueryClient } from './queryClient';
import { useMetaVm } from './useMetaVm';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, meta: vi.fn() } };
});
import { api } from '../api/client';

const metaMock = vi.mocked(api.meta);

function setup() {
  const client = createQueryClient({ retry: false });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useMetaVm(), { wrapper });
}

beforeEach(() => metaMock.mockReset());

describe('useMetaVm', () => {
  it('maps slider and presets from meta', async () => {
    metaMock.mockResolvedValue(meta);
    const { result } = setup();
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.slider).toEqual({
      min: meta.slider.min,
      max: meta.slider.max,
      step: meta.slider.step,
      obsMin: meta.h_min_obs,
      obsMax: meta.h_max_obs,
      npp: meta.npp,
      maxPp: meta.max_pp,
    });
    expect(result.current.presets).toEqual(meta.draft_presets);
    expect(result.current.meta).toBe(meta);
  });

  it('error then retry', async () => {
    metaMock.mockRejectedValueOnce(new Error('down')).mockResolvedValue(meta);
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('error'));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.status).toBe('ready'));
  });
});
