import { QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { kzDeep } from '../test/fixtures';
import { createQueryClient } from './queryClient';
import { useKzDeepVm } from './useKzDeepVm';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, kzDeep: vi.fn() } };
});
import { api } from '../api/client';

const mock = vi.mocked(api.kzDeep);
const setup = () =>
  renderHook(() => useKzDeepVm(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={createQueryClient({ retry: false })}>{children}</QueryClientProvider>
    ),
  });

beforeEach(() => {
  mock.mockReset();
});

describe('useKzDeepVm', () => {
  it('returns the surface and attribution', async () => {
    mock.mockResolvedValue(kzDeep);
    const { result } = setup();
    await waitFor(() => expect(result.current.kzDeep).toBeDefined());
    expect(result.current.attribution).toBe('Mapa KŻ Nysa (W. Wróblewski, 2023)');
  });

  it('empty collection means no layer', async () => {
    mock.mockResolvedValue({ type: 'FeatureCollection', features: [] });
    const { result } = setup();
    await waitFor(() => expect(mock).toHaveBeenCalled());
    await waitFor(() => expect(result.current.attribution).toBeUndefined());
    expect(result.current.kzDeep).toBeUndefined();
  });

  it('error leaves the layer absent', async () => {
    mock.mockRejectedValue(new ApiError(404, 'brak'));
    const { result } = setup();
    await waitFor(() => expect(mock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.kzDeep).toBeUndefined();
    expect(mock).toHaveBeenCalledTimes(1);
  });
});
