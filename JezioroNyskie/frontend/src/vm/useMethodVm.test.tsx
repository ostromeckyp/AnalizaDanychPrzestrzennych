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
    metaMock.mockResolvedValue({
      ...meta,
      accuracy: { ...meta.accuracy, bottom_rmse_nmt: 1.508, bottom_bias_nmt: 1.157, bottom_in_bounds_nmt: 0.0642 },
    });
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const t = result.current.tiles.find((x) => x.label === 'RMSE dna')!;
    expect(t.value).toBe('1,51\u00a0m');
    expect(t.sub).toBe(
      'vs NMT LiDAR, bloki walidacyjne; obciążenie +1,16\u00a0m na odsłoniętym brzegu (przyczyna nieustalona)' +
        ' · przedział [z_min, z_max] zawiera teren w 6% pikseli — to nie jest przedział ufności',
    );
    expect(t.sub).not.toMatch(/układu wysokości|datum/);
  });

  it('RMSE tile omits bias and in-bounds parts when they are missing', async () => {
    metaMock.mockResolvedValue({ ...meta, accuracy: { ...meta.accuracy, bottom_rmse_nmt: 1.508 } });
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.tiles.find((x) => x.label === 'RMSE dna')!.sub).toBe('vs NMT LiDAR, bloki walidacyjne');
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

  it('deep band: KŻ interpolation error instead of "brak danych" when kz_loo present, else unchanged', async () => {
    const mk = (kz_loo: { n: number; mae: number; p5: number; p95: number } | null) => ({
      ...meta,
      validation: {
        checks: [],
        lidar_note: 'x',
        bands: [
          { band: '< 192,9 m', range_m: null, dominant: null, note: 'nota głęboka', ...(kz_loo ? { kz_loo } : {}) },
        ],
      },
    });
    metaMock.mockResolvedValue(mk({ n: 93, mae: 1.034, p5: -1.59, p95: 3.05 }));
    const a = setup();
    await waitFor(() => expect(a.result.current.status).toBe('ready'));
    const withLoo = a.result.current.validation!.bands[0];
    expect(withLoo.range).toBe('—');
    expect(withLoo.dominant).toBe('błąd interpolacji KŻ: MAE 1,03\u00a0m');
    expect(withLoo.note).toBe('nota głęboka');

    metaMock.mockResolvedValue(mk(null));
    const b = setup();
    await waitFor(() => expect(b.result.current.status).toBe('ready'));
    const without = b.result.current.validation!.bands[0];
    expect(without.range).toBe('brak danych');
    expect(without.dominant).toBe('—');
  });

  it('band note explains the deep cell is the KŻ map interpolation error, only when that cell is shown', async () => {
    const mk = (withLoo: boolean) => ({
      ...meta,
      validation: {
        checks: [],
        lidar_note: 'x',
        bands: [
          { band: '< 192,9 m', range_m: null, dominant: null, note: 'n', ...(withLoo ? { kz_loo: { n: 93, mae: 1.034, p5: -1.59, p95: 3.05 } } : {}) },
        ],
      },
    });
    metaMock.mockResolvedValue(mk(true));
    const a = setup();
    await waitFor(() => expect(a.result.current.status).toBe('ready'));
    expect(a.result.current.validation!.bandsNote).toMatch(/< 192,9 m .*błąd interpolacji mapy KŻ .*nie błąd modelu/);
    metaMock.mockResolvedValue(mk(false));
    const b = setup();
    await waitFor(() => expect(b.result.current.status).toBe('ready'));
    expect(b.result.current.validation!.bandsNote).toBe('Główne źródło = kontrola z największym błędem w paśmie.');
  });

  it('deep-bottom paragraph: KŻ interpolation error (never "dokładność"), calibration as extrapolation', async () => {
    metaMock.mockResolvedValue({
      ...meta,
      accuracy: { ...meta.accuracy, calibration_coverage: 0.9017, holdout_in_bounds: 0.1718 },
      validation: {
        checks: [],
        lidar_note: 'x',
        bands: [{ band: '< 192,9 m', range_m: null, dominant: null, note: 'n', kz_loo: { n: 93, mae: 1.034, p5: -1.59, p95: 3.05 } }],
      },
    });
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const [kz, cal] = result.current.deepBottom!.paragraphs;
    expect(kz).toContain('Błąd interpolacji mapy KŻ (każdy punkt odłożony i odtworzony z pozostałych, n = 93): MAE 1,03\u00a0m.');
    expect(kz).toContain('nie całkowity błąd dna');
    expect(kz).toContain('„Dno wg mapy KŻ”');
    expect(kz).not.toMatch(/dokładnoś/i);
    expect(cal).toContain('ok. 90% sprawdzonych przypadków (przed poszerzeniem 17%); ten wynik wynika z konstrukcji');
    expect(kz).toContain('mniej więcej o połowę mniej');
    expect(kz).not.toMatch(/najczęściej|większoś/);
    expect(cal).toContain('ekstrapolacja');
  });

  it('deep-bottom paragraph without eval numbers has no placeholders', async () => {
    metaMock.mockResolvedValue({ ...meta, validation: undefined });
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const text = result.current.deepBottom!.paragraphs.join(' ');
    expect(text).not.toMatch(/MAE|NaN|undefined|—%/);
    const kz = result.current.deepBottom!.paragraphs[0];
    expect(kz).toContain('Błąd tej mapy liczymy, sprawdzając ją samą ze sobą; to nie jest całkowity błąd dna.');
    expect(kz).not.toContain('To błąd mapy sprawdzonej samą sobą');
  });

  it('sources list the KŻ deep-bottom layer with the UWAGA terms', async () => {
    metaMock.mockResolvedValue(meta);
    const { result } = setup();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const row = result.current.sources.find((s) => s.name.startsWith('Dno wg mapy KŻ'))!;
    expect(row.license).toContain('warunki „UWAGA”');
    expect(row.license).toContain('całość ryzyka korzystania ponosi użytkownik');
    expect(row.license).toContain('niekomercyjnych');
  });
});

