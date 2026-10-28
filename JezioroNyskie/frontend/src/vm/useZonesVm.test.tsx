import { QueryClientProvider, onlineManager } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Zones } from '../api/client';
import { zones as zonesFixture } from '../test/fixtures';
import { createQueryClient } from './queryClient';
import { useZonesVm } from './useZonesVm';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, zones: vi.fn() } };
});
import { api } from '../api/client';

const zonesMock = vi.mocked(api.zones);
const NB = ' ';

function setup(initial: { h: number; draft: number; margin: number }) {
  const client = createQueryClient({ retry: false });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook((p: { h: number; draft: number; margin: number }) => useZonesVm(p), {
    wrapper,
    initialProps: initial,
  });
}

function deferred() {
  let resolve!: (z: Zones) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<Zones>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms));

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  zonesMock.mockReset();
  zonesMock.mockImplementation(async (p) => zonesFixture(p.h, p.draft, p.margin));
});

afterEach(() => {
  act(() => onlineManager.setOnline(true));
  vi.useRealTimers();
});

describe('useZonesVm', () => {
  it('production client keeps retry: 1 and 5 min staleTime', () => {
    const o = createQueryClient().getDefaultOptions().queries!;
    expect(o.retry).toBe(1);
    expect(o.staleTime).toBe(5 * 60 * 1000);
  });

  it('first load, then ready', async () => {
    const { result } = setup({ h: 195, draft: 1.2, margin: 0.3 });
    expect(result.current.status).toBe('first-load');
    expect(result.current.zones).toBeUndefined();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.lastOkAt).toBeInstanceOf(Date);
  });

  it('debounces and rounds: 5 changes in 200 ms → 1 request with rounded params', async () => {
    const { result, rerender } = setup({ h: 195, draft: 1.2, margin: 0.3 });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    zonesMock.mockClear();
    for (const h of [195.21, 195.22, 195.23, 195.24, 195.245]) {
      rerender({ h, draft: 1.2, margin: 0.3 });
      await advance(40);
    }
    expect(zonesMock).not.toHaveBeenCalled();
    await advance(250);
    await waitFor(() => expect(result.current.zones?.params.h).toBe(195.25));
    expect(zonesMock).toHaveBeenCalledTimes(1);
    expect(zonesMock).toHaveBeenLastCalledWith({ h: 195.25, draft: 1.2, margin: 0.3 }, expect.anything());
  });

  it('late response for old params never replaces newer result', async () => {
    const a = deferred();
    const b = deferred();
    zonesMock.mockReset();
    zonesMock.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const { result, rerender } = setup({ h: 195.0, draft: 1.2, margin: 0.3 });
    await waitFor(() => expect(zonesMock).toHaveBeenCalledTimes(1));
    rerender({ h: 195.5, draft: 1.2, margin: 0.3 });
    await advance(250);
    await waitFor(() => expect(zonesMock).toHaveBeenCalledTimes(2));
    // starsze zapytanie dostaje sygnał przerwania
    expect((zonesMock.mock.calls[0][1] as AbortSignal).aborted).toBe(true);
    await act(async () => b.resolve(zonesFixture(195.5, 1.2, 0.3)));
    await waitFor(() => expect(result.current.zones?.params.h).toBe(195.5));
    await act(async () => a.resolve(zonesFixture(195.0, 1.2, 0.3)));
    expect(result.current.zones?.params.h).toBe(195.5);
    expect(result.current.status).toBe('ready');
  });

  it('keeps previous zones while recalculating', async () => {
    const { result, rerender } = setup({ h: 195.0, draft: 1.2, margin: 0.3 });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const next = deferred();
    zonesMock.mockReturnValueOnce(next.promise);
    rerender({ h: 195.5, draft: 1.2, margin: 0.3 });
    await advance(250);
    await waitFor(() => expect(result.current.status).toBe('recalculating'));
    expect(result.current.zones?.params.h).toBe(195.0);
    await act(async () => next.resolve(zonesFixture(195.5, 1.2, 0.3)));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.zones?.params.h).toBe(195.5);
  });

  it('error keeps last good zones and params; retry recovers', async () => {
    const { result, rerender } = setup({ h: 195, draft: 1.2, margin: 0.3 });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const okAt = result.current.lastOkAt;
    zonesMock.mockRejectedValueOnce(new Error('boom'));
    rerender({ h: 195.5, draft: 1.2, margin: 0.3 });
    await advance(250);
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.lastOkParams).toEqual({ h: 195, draft: 1.2, margin: 0.3 });
    expect(result.current.lastOkAt).toEqual(okAt);
    expect(result.current.zones).toBeDefined();
    expect(result.current.zones?.params.h).toBe(195);
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.zones?.params.h).toBe(195.5);
  });

  it('offline status from onlineManager', async () => {
    const { result } = setup({ h: 195, draft: 1.2, margin: 0.3 });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    act(() => onlineManager.setOnline(false));
    expect(result.current.status).toBe('offline');
    expect(result.current.zones).toBeDefined();
    act(() => onlineManager.setOnline(true));
    await waitFor(() => expect(result.current.status).toBe('ready'));
  });

  it('summary text', async () => {
    const { result } = setup({ h: 195, draft: 1.2, margin: 0.3 });
    await waitFor(() => expect(result.current.summary).toBeDefined());
    expect(result.current.summary).toBe(
      `Jacht 1,20${NB}m · poziom 195,00${NB}m n.p.m. · bezpieczne 62% akwenu`,
    );
  });

  it('exposes backend warning codes', async () => {
    zonesMock.mockResolvedValue({ ...zonesFixture(190, 1.2, 0.3), warnings: ['h_out_of_range'] });
    const { result } = setup({ h: 190, draft: 1.2, margin: 0.3 });
    await waitFor(() => expect(result.current.warnings).toEqual(['h_out_of_range']));
  });

  it('does not call the API for non-finite params', async () => {
    const { result } = setup({ h: NaN, draft: 1.2, margin: 0.3 });
    await advance(300);
    expect(zonesMock).not.toHaveBeenCalled();
    expect(result.current.zones).toBeUndefined();
  });

  it('sub-step jitter (same rounded params) does not flip to recalculating', async () => {
    const { result, rerender } = setup({ h: 195, draft: 1.2, margin: 0.3 });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    rerender({ h: 195.004, draft: 1.2, margin: 0.3 });
    expect(result.current.status).toBe('ready');
    await advance(10);
    expect(result.current.status).toBe('ready');
  });

  it('isRetrying is true only while retry() refetches after an error', async () => {
    const { result, rerender } = setup({ h: 195, draft: 1.2, margin: 0.3 });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.isRetrying).toBe(false);
    zonesMock.mockRejectedValueOnce(new Error('boom'));
    rerender({ h: 195.5, draft: 1.2, margin: 0.3 });
    await advance(250);
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.isRetrying).toBe(false);
    const next = deferred();
    zonesMock.mockReturnValueOnce(next.promise);
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.isRetrying).toBe(true));
    await act(async () => next.resolve(zonesFixture(195.5, 1.2, 0.3)));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.isRetrying).toBe(false);
  });
});
