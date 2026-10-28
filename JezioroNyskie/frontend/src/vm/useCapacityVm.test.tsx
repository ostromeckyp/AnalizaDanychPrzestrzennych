import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { meta } from '../test/fixtures';
import { createQueryClient } from './queryClient';
import { useCapacityVm } from './useCapacityVm';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, meta: vi.fn(), capacityToLevel: vi.fn(), levelToCapacity: vi.fn() } };
});
import { ApiError, api } from '../api/client';

function wrap() {
  const client = createQueryClient({ retry: false });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

// Mock odwzorowuje zakresy backendu: h 180–210, v 0–200 (poza nimi 422).
beforeEach(() => {
  vi.mocked(api.meta).mockReset().mockResolvedValue(meta);
  vi.mocked(api.capacityToLevel)
    .mockReset()
    .mockImplementation(async (v) => {
      if (!(v > 0 && v <= 200)) throw new ApiError(422, 'v');
      return { v, h: 195.2, in_table: true };
    });
  vi.mocked(api.levelToCapacity)
    .mockReset()
    .mockImplementation(async (h) => {
      if (!(h >= 180 && h <= 210)) throw new ApiError(422, 'h');
      return { h, v: 50, in_table: true };
    });
});

type P = { mode: 'level' | 'capacity'; input: number };

describe('useCapacityVm: przełączanie trybu', () => {
  it('po level→capacity nie wysyła poziomu jako pojemności ani nie pokazuje „poza tabelą”', async () => {
    const { result, rerender } = renderHook((p: P) => useCapacityVm(p.mode, p.input), {
      wrapper: wrap(),
      initialProps: { mode: 'level', input: 196.1 } as P,
    });
    await waitFor(() => expect(result.current.capacityAtLevel).toBe(50));
    rerender({ mode: 'capacity', input: 45.6 });
    // okno debounce: brak wyników starego trybu i brak błędnych wywołań
    expect(result.current.inTable).toBeUndefined();
    expect(vi.mocked(api.capacityToLevel)).not.toHaveBeenCalledWith(196.1, expect.anything());
    await waitFor(() => expect(result.current.hFromCapacity).toBe(195.2));
    expect(result.current.inTable).toBe(true);
    expect(vi.mocked(api.capacityToLevel)).toHaveBeenCalledTimes(1);
  });

  it('po capacity→level nie wysyła pojemności jako poziomu ani nie liczy aboveNpp z niej', async () => {
    const { result, rerender } = renderHook((p: P) => useCapacityVm(p.mode, p.input), {
      wrapper: wrap(),
      initialProps: { mode: 'capacity', input: 45.6 } as P,
    });
    await waitFor(() => expect(result.current.hFromCapacity).toBe(195.2));
    rerender({ mode: 'level', input: 196.1 });
    expect(result.current.aboveNpp).toBeUndefined();
    expect(result.current.hFromCapacity).toBeUndefined();
    await waitFor(() => expect(result.current.capacityAtLevel).toBe(50));
    expect(result.current.aboveNpp).toMatch(/powyżej NPP/);
    expect(vi.mocked(api.levelToCapacity)).not.toHaveBeenCalledWith(45.6, expect.anything());
    expect(vi.mocked(api.levelToCapacity)).toHaveBeenCalledTimes(1);
  });

  it('w trybie level zachowuje poprzednią pojemność między krokami suwaka', async () => {
    const { result, rerender } = renderHook((p: P) => useCapacityVm(p.mode, p.input), {
      wrapper: wrap(),
      initialProps: { mode: 'level', input: 196.1 } as P,
    });
    await waitFor(() => expect(result.current.capacityAtLevel).toBe(50));
    vi.mocked(api.levelToCapacity).mockImplementation(() => new Promise(() => {}));
    rerender({ mode: 'level', input: 196.3 });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 400));
    });
    expect(result.current.capacityAtLevel).toBe(50);
  });
});

describe('useCapacityVm: błąd 4xx', () => {
  it('pojemność poza zakresem backendu (422) → inTable:false', async () => {
    const { result } = renderHook(() => useCapacityVm('capacity', 250), { wrapper: wrap() });
    await waitFor(() => expect(result.current.inTable).toBe(false));
    expect(result.current.hFromCapacity).toBeUndefined();
  });
});
