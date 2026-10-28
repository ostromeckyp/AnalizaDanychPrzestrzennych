import { QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { gravel } from '../test/fixtures';
import { createQueryClient } from './queryClient';
import { useGravelVm } from './useGravelVm';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, gravel: vi.fn() } };
});
import { api } from '../api/client';

const gravelMock = vi.mocked(api.gravel);
const setup = () =>
  renderHook(() => useGravelVm(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={createQueryClient({ retry: false })}>{children}</QueryClientProvider>
    ),
  });

beforeEach(() => {
  gravelMock.mockReset();
});

describe('useGravelVm', () => {
  it('returns the outline and the attribution from the API', async () => {
    gravelMock.mockResolvedValue(gravel);
    const { result } = setup();
    await waitFor(() => expect(result.current.gravel).toBeDefined());
    expect(result.current.attribution).toBe('Obrys wg mapy KŻ Nysa (W. Wróblewski, 2023)');
  });

  it('404 (no outline file) leaves the layer absent', async () => {
    gravelMock.mockImplementation(async () => {
      throw new ApiError(404, 'brak');
    });
    const { result } = setup();
    await waitFor(() => expect(gravelMock).toHaveBeenCalled());
    expect(result.current.gravel).toBeUndefined();
    expect(result.current.attribution).toBeUndefined();
  });
});
