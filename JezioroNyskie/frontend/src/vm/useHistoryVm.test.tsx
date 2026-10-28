import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { meta, scenes } from '../test/fixtures';
import { createQueryClient } from './queryClient';
import { useHistoryVm } from './useHistoryVm';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, meta: vi.fn(), scenes: vi.fn(), shoreline: vi.fn() } };
});
import { api } from '../api/client';

const m = vi.mocked(api);
const NB = '\u00a0';

function setup() {
  const client = createQueryClient({ retry: false });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useHistoryVm(), { wrapper });
}

beforeEach(() => {
  m.meta.mockReset().mockResolvedValue(meta);
  m.scenes.mockReset().mockResolvedValue(scenes);
  m.shoreline.mockReset().mockImplementation(async (date) => ({
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: [[17, 50]] },
    properties: scenes.find((s) => s.date === date)!,
  }));
});

describe('useHistoryVm', () => {
  it('loads scenes, years descending, default year = newest, newest scene selected', async () => {
    const { result } = setup();
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.years).toEqual([2026, 2025]);
    expect(result.current.year).toBe(2026);
    expect(result.current.scenes.map((s) => s.date)).toEqual(['2026-10-20', '2026-09-30']);
    expect(result.current.selected?.date).toBe('2026-10-20');
    expect(result.current.allScenes).toHaveLength(3);
    expect(result.current.npp).toBe(meta.npp);
  });

  it('rows carry Polish formatting, level colour and dashed rule', async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const r = result.current.scenes[0];
    expect(r.dateLabel).toBe('20.10.2026');
    expect(r.level).toBe(`194,20${NB}m n.p.m.`);
    expect(r.area).toBe(`12,3${NB}km²`);
    expect(r.color).toMatch(/^#[0-9a-f]{6}$/);
    expect(r.dashed).toBe(true); // 194.2 < npp 195.91
  });

  it('year filter and counter with Polish plural', async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.counter).toBe('2 sceny · nałożone: 0');
    act(() => result.current.setYear(2025));
    expect(result.current.counter).toBe('1 scena · nałożone: 0');
    act(() => result.current.setYear('all'));
    expect(result.current.counter).toMatch(/^3 sceny · nałożone: 0$/);
  });

  it('overlay fetches only selected shorelines and merges them', async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(m.shoreline).not.toHaveBeenCalled();
    expect(result.current.shorelines.features).toHaveLength(0);
    act(() => result.current.toggleOverlay('2026-10-20'));
    await waitFor(() => expect(result.current.shorelines.features).toHaveLength(1));
    expect(m.shoreline).toHaveBeenCalledTimes(1);
    expect(m.shoreline).toHaveBeenCalledWith('2026-10-20', expect.anything());
    expect(result.current.counter).toBe('2 sceny · nałożone: 1');
    act(() => result.current.toggleOverlay('2026-10-20'));
    expect(result.current.shorelines.features).toHaveLength(0);
    expect(result.current.overlay).toEqual([]);
  });

  it('failed shoreline marks only that row, no crash', async () => {
    m.shoreline.mockRejectedValue(new Error('boom'));
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    act(() => result.current.toggleOverlay('2026-10-20'));
    await waitFor(() =>
      expect(result.current.scenes.find((s) => s.date === '2026-10-20')?.overlayStatus).toBe('error'),
    );
    expect(result.current.scenes.find((s) => s.date === '2026-09-30')?.overlayStatus).toBeUndefined();
    expect(result.current.shorelines.features).toHaveLength(0);
  });

  it('empty filter: year without scenes gives empty list, no selection; reset via setYear all', async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    act(() => result.current.setYear(2019));
    expect(result.current.scenes).toEqual([]);
    expect(result.current.selected).toBeUndefined();
    expect(result.current.counter).toBe('0 scen · nałożone: 0');
    act(() => result.current.setYear('all'));
    expect(result.current.scenes).toHaveLength(3);
  });

  it('select sets selected; card link sets level on map', async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.selected?.mapHref).toBe('/?h=194.2');
    expect(result.current.selected?.source).toBe(`Sentinel-2 · zachm. 0,5%`);
    act(() => result.current.select('2026-09-30'));
    expect(result.current.selected?.date).toBe('2026-09-30');
    expect(result.current.selected?.mapHref).toBe('/?h=193.9');
  });

  it('omits cloud part when local_cloud_pct is null', async () => {
    m.scenes.mockResolvedValue([{ ...scenes[2], local_cloud_pct: null }]);
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.selected?.source).toBe('Sentinel-2');
  });

  it('scenes error then retry', async () => {
    m.scenes.mockRejectedValueOnce(new Error('x'));
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('error'));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.status).toBe('ready'));
  });

  it('years cover the full range including gap years, so an empty year is selectable', async () => {
    m.scenes.mockResolvedValue([
      { ...scenes[0], date: '2023-05-01' },
      { ...scenes[2], date: '2026-10-20' },
    ]);
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.years).toEqual([2026, 2025, 2024, 2023]);
    act(() => result.current.setYear(2025));
    expect(result.current.scenes).toEqual([]);
    expect(result.current.counter).toBe('0 scen · nałożone: 0');
  });

  it('rerender without changes keeps shorelines identity', async () => {
    const { result, rerender } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    act(() => result.current.toggleOverlay('2026-10-20'));
    await waitFor(() => expect(result.current.shorelines.features).toHaveLength(1));
    const first = result.current.shorelines;
    rerender();
    expect(result.current.shorelines).toBe(first);
  });
});
