import { QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CurrentLevel } from '../api/client';
import { currentLevel, meta } from '../test/fixtures';
import { createQueryClient } from './queryClient';
import { useCapacityVm } from './useCapacityVm';
import { useCurrentLevelVm } from './useCurrentLevelVm';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return {
    ...mod,
    api: { ...mod.api, currentLevel: vi.fn(), meta: vi.fn(), capacityToLevel: vi.fn(), levelToCapacity: vi.fn() },
  };
});
import { api } from '../api/client';

const NB = ' ';

function wrap() {
  const client = createQueryClient({ retry: false });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

async function level(patch: Partial<CurrentLevel>) {
  vi.mocked(api.currentLevel).mockResolvedValue({ ...currentLevel, scene_date: '2026-10-26', ...patch });
  const { result } = renderHook(() => useCurrentLevelVm(), { wrapper: wrap() });
  await waitFor(() => expect(result.current.status).toBe('ready'));
  return result.current;
}

beforeEach(() => {
  vi.mocked(api.currentLevel).mockReset();
  vi.mocked(api.meta).mockReset().mockResolvedValue(meta);
  vi.mocked(api.capacityToLevel).mockReset();
  vi.mocked(api.levelToCapacity).mockReset();
});

describe('useCurrentLevelVm', () => {
  it('RZGW label for method B, satellite label for C and source satellite', async () => {
    const b = await level({ h_method: 'B' });
    expect(b.level).toEqual({ h: currentLevel.h, label: 'poziom z 26.10.2026, z komunikatu RZGW', note: undefined });
    expect((await level({ h_method: 'R' })).level?.label).toBe('poziom z 26.10.2026, z komunikatu RZGW');
    expect((await level({ h_method: 'C' })).level?.label).toBe(
      'poziom z 26.10.2026, wyznaczony z obrazu satelitarnego',
    );
    expect((await level({ source: 'satellite', h_method: 'B' })).level?.label).toBe(
      'poziom z 26.10.2026, wyznaczony z obrazu satelitarnego',
    );
  });

  it('stale and ice notes', async () => {
    expect((await level({ stale: true })).level?.note).toBe('ostatnia znana wartość');
    expect((await level({ ice_unverified: true })).level?.note).toBe('możliwy lód — poziom niezweryfikowany');
  });

  it('error status', async () => {
    vi.mocked(api.currentLevel).mockRejectedValue(new Error('x'));
    const { result } = renderHook(() => useCurrentLevelVm(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.level).toBeUndefined();
  });
});

describe('useCapacityVm', () => {
  it('capacity mode → level via API (rounded input)', async () => {
    vi.mocked(api.capacityToLevel).mockResolvedValue({ v: 45.6, h: 195.2, in_table: true });
    const { result } = renderHook(() => useCapacityVm('capacity', 45.62), { wrapper: wrap() });
    await waitFor(() => expect(result.current.hFromCapacity).toBe(195.2));
    expect(api.capacityToLevel).toHaveBeenCalledWith(45.6, expect.anything());
    expect(result.current.inTable).toBe(true);
    expect(api.levelToCapacity).not.toHaveBeenCalled();
  });

  it('level mode → capacity and distance from NPP', async () => {
    vi.mocked(api.levelToCapacity).mockResolvedValue({ h: 196.1, v: 50, in_table: true });
    const { result } = renderHook(() => useCapacityVm('level', 196.11), { wrapper: wrap() });
    await waitFor(() => expect(result.current.capacityAtLevel).toBe(50));
    expect(api.levelToCapacity).toHaveBeenCalledWith(196.1, expect.anything());
    expect(result.current.aboveNpp).toBe(`0,20${NB}m powyżej NPP`);
  });

  it('below NPP and non-finite input skips the API', async () => {
    vi.mocked(api.levelToCapacity).mockResolvedValue({ h: 195.7, v: 40, in_table: true });
    const below = renderHook(() => useCapacityVm('level', 195.7), { wrapper: wrap() });
    await waitFor(() => expect(below.result.current.aboveNpp).toBe(`0,20${NB}m poniżej NPP`));
    vi.mocked(api.levelToCapacity).mockClear();
    const bad = renderHook(() => useCapacityVm('level', NaN), { wrapper: wrap() });
    expect(bad.result.current.capacityAtLevel).toBeUndefined();
    expect(bad.result.current.aboveNpp).toBeUndefined();
    expect(api.levelToCapacity).not.toHaveBeenCalled();
  });

  it('level at NPP (within rounding) says "na poziomie NPP"', async () => {
    vi.mocked(api.levelToCapacity).mockResolvedValue({ h: 195.9, v: 40, in_table: true });
    const { result } = renderHook(() => useCapacityVm('level', 195.9), { wrapper: wrap() });
    await waitFor(() => expect(result.current.aboveNpp).toBe('na poziomie NPP'));
  });
});
