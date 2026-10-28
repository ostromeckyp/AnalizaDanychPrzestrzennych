import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { meta } from '../test/fixtures';
import { createQueryClient } from './queryClient';
import { useMethodVm } from './useMethodVm';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, meta: vi.fn() } };
});
import { api } from '../api/client';

const metaMock = vi.mocked(api.meta);

function setup() {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={createQueryClient({ retry: false })}>{children}</QueryClientProvider>
  );
  return renderHook(() => useMethodVm(), { wrapper });
}

beforeEach(() => metaMock.mockReset());

describe('useMethodVm', () => {
  it('formats tiles from meta, RMSE pending', async () => {
    metaMock.mockResolvedValue(meta);
    const { result } = setup();
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const t = Object.fromEntries(result.current.tiles.map((x) => [x.label, x]));
    expect(t['Zgodność maski wody (OA)'].value).toBe('81,6%');
    expect(t['Zrównoważona trafność (BA)'].value).toBe('77,2%');
    expect(t['Zrównoważona trafność (BA)'].sub).toContain('75,5%');
    expect(t['Liczba scen'].value).toBe('3');
    expect(t['Liczba scen'].sub).toBe('okres 12.04.2025–20.10.2026');
    expect(t['Zakres poziomów'].value).toBe('192,90–197,92');
    expect(t['RMSE dna'].value).toMatch(/w przygotowaniu/);
  });

  it('RMSE tile shows the NMT value when present, pending otherwise', async () => {
    metaMock.mockResolvedValue({ ...meta, accuracy: { ...meta.accuracy, bottom_rmse_nmt: 1.508, bottom_bias_nmt: 1.157 } });
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const t = result.current.tiles.find((x) => x.label === 'RMSE dna')!;
    expect(t.value).toBe('1,51\u00a0m');
    expect(t.sub).toBe('vs NMT LiDAR, bloki walidacyjne; obciążenie +1,16\u00a0m (w tym możliwe przesunięcie układu wysokości)');
  });

  it('KŻ agreement tile: bias and RMSE when present, pending otherwise', async () => {
    metaMock.mockResolvedValue(meta);
    const pending = setup();
    await waitFor(() => expect(pending.result.current.status).toBe('ready'));
    expect(pending.result.current.tiles.find((x) => x.label === 'Zgodność z mapą KŻ')!.value).toMatch(/w przygotowaniu/);
    metaMock.mockResolvedValue({ ...meta, accuracy: { ...meta.accuracy, kz_rmse: 0.62, kz_bias: -0.2 } });
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const t = result.current.tiles.find((x) => x.label === 'Zgodność z mapą KŻ')!;
    expect(t.value).toBe('RMSE 0,62\u00a0m');
    expect(t.sub).toContain('obciążenie -0,20\u00a0m');
    expect(t.sub).toMatch(/sprzed powodzi/);
    expect(t.sub).toMatch(/komórka modelu 10 m pod punktem/);
    expect(t.sub).not.toMatch(/50 m/);
  });

  it('step 03 describes variant A as working with its scene count; step 04 states the model period', async () => {
    metaMock.mockResolvedValue({ ...meta, n_scenes_by_method: { A: 36, B: 61, C: 10 }, model_period: 'post_flood', model_period_reason: 'Powód z API.' });
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const s3 = result.current.steps[2].text;
    expect(s3).toContain('Kalibracja poziomu według NMT z LiDAR (wariant A): 36 scen.');
    expect(s3).not.toMatch(/w przygotowaniu/);
    expect(result.current.steps[3].text).toContain('po powodzi');
    expect(result.current.steps[3].text).toContain('Powód z API.');
  });

  it('chart data: numbers from meta, legend only for present methods, null levels skipped', async () => {
    metaMock.mockResolvedValue({
      ...meta,
      area_level: {
        ...meta.area_level,
        points: [
          ...meta.area_level.points,
          { date: '2026-01-01', area_otsu_km2: 12.5, h_t: null, h_method: 'C' },
          { date: '2026-02-01', area_otsu_km2: 12.6, h_t: 194.5, h_method: 'Z' },
        ],
      },
    });
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const c = result.current.chart!;
    expect(c.points).toHaveLength(4);
    expect(c.npp).toBe(meta.npp);
    expect(c.maxPp).toBe(meta.max_pp);
    expect(c.nodes).toEqual([
      { area: 10.5, h: 192.9 },
      { area: 12.0, h: 194.0 },
      { area: 14.0, h: 197.0 },
    ]);
    expect(c.legend.map((l) => l.code)).toEqual(['B', 'Z']);
    expect(c.legend[0].label).toBe('komunikat RZGW');
    expect(c.legend[1].label).toBe('Z');
  });

  it('step texts mention RZGW and curve, fill numbers from meta', async () => {
    metaMock.mockResolvedValue(meta);
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const s3 = result.current.steps[2].text;
    expect(s3).toMatch(/RZGW/);
    expect(s3).toMatch(/krzywej powierzchnia–poziom/);
    expect(result.current.steps[3].text).toMatch(/przedziały zalania/);
    expect(result.current.steps[3].text).not.toMatch(/interpolacj/i);
  });

  it('step 03 declension and variant R counts', async () => {
    metaMock.mockResolvedValue({ ...meta, n_scenes: 218, n_scenes_by_method: { B: 153, C: 63, R: 2 } });
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const s3 = result.current.steps[2].text;
    expect(s3).toContain('153 sceny');
    expect(s3).toContain('63 sceny');
    expect(s3).toContain('Pomiar wodowskazowy (wariant R): 2 sceny.');
    expect(result.current.steps[0].text).toContain('218 scen ');
    expect(result.current.steps[0].text).toContain('12.04.2025–20.10.2026');
  });

  it('missing scene dates omit the period text', async () => {
    metaMock.mockResolvedValue({ ...meta, first_scene_date: null, last_scene_date: null });
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.steps[0].text).toMatch(/W modelu: 3 sceny\.$/);
    expect(result.current.steps[0].text).not.toContain('—');
    expect(result.current.tiles.find((t) => t.label === 'Liczba scen')!.sub).toBe('okres niedostępny');
  });

  it('legend labels variant R', async () => {
    metaMock.mockResolvedValue({
      ...meta,
      area_level: { ...meta.area_level, points: [{ date: '2025-05-01', area_otsu_km2: 11, h_t: 197.9, h_method: 'R' }] },
    });
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.chart!.legend).toEqual([
      { code: 'R', label: 'znany pomiar wodowskazowy', color: 'var(--risk)' },
    ]);
  });

  it('error exposes retry', async () => {
    metaMock.mockRejectedValueOnce(new Error('down')).mockResolvedValue(meta);
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('error'));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.status).toBe('ready'));
  });
});
