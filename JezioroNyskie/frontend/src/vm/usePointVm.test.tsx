import { QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Point } from '../api/client';
import { meta, pointAlwaysWater, pointLand, pointModel, pointOutside } from '../test/fixtures';
import { createQueryClient } from './queryClient';
import { toPopupModel, usePointVm } from './usePointVm';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, point: vi.fn(), meta: vi.fn() } };
});
import { api } from '../api/client';

const pointMock = vi.mocked(api.point);
const NB = '\u00a0';

describe('toPopupModel', () => {
  it.each([
    [pointModel, 'A', `1,00–2,00${NB}m`],
    [pointAlwaysWater, 'B', `≥ 1,95${NB}m`],
    [pointLand, 'C', 'Ląd'],
    [pointOutside, 'D', 'Poza obszarem modelu'],
  ] as const)('variant from kind', (resp, variant, value) => {
    const m = toPopupModel(resp, meta);
    expect(m.variant).toBe(variant);
    expect(m.value).toBe(value);
    expect(JSON.stringify(m)).not.toMatch(/null|NaN|Infinity|undefined|—/);
  });

  it('A: clearance, margin, bottom height, scenes, location; zone from API', () => {
    const m = toPopupModel(
      { ...pointModel, depth_min: 1.4, depth_max: 1.9, clearance_min: 0.2, clearance_max: 0.7, z: 193.55, unc: 0.25, obs_count: 14, zone: 'risk' },
      meta,
    );
    expect(m.value).toBe(`1,40–1,90${NB}m`);
    expect(m.title).toBe('Głębokość w tym miejscu');
    expect(m.note).toBe(`Pod kilem 0,20 do 0,70${NB}m · wymagany zapas 0,30${NB}m`);
    expect(m.zone).toEqual({ key: 'risk', name: 'Ryzykowna', label: `dla jachtu 1,20${NB}m` });
    expect(m.rows).toContainEqual({ term: 'Wysokość dna', desc: `193,55${NB}m n.p.m. ± 0,25` });
    expect(m.rows).toContainEqual({ term: 'Obserwacje satelitarne', desc: '14 scen' });
    expect(m.rows.find((r) => r.term === 'Położenie')?.desc).toMatch(/50,4500.*17,0500/);
  });

  it('A: zone label follows API zone, never computed', () => {
    expect(toPopupModel({ ...pointModel, zone: 'safe' }, meta).zone?.name).toBe('Bezpieczna');
    expect(toPopupModel({ ...pointModel, zone: 'danger' }, meta).zone?.name).toBe('Zbyt płytka / ląd');
    expect(toPopupModel({ ...pointModel, zone: null }, meta).zone).toBeUndefined();
  });

  it('A: negative or missing clearance and missing optional numbers produce no artefacts', () => {
    const m = toPopupModel({ ...pointModel, clearance_min: null, clearance_max: null, z: null, unc: null, obs_count: null }, meta);
    expect(JSON.stringify(m)).not.toMatch(/null|NaN|Infinity|undefined|—/);
    expect(m.rows.map((r) => r.term)).toEqual(['Położenie']);
    const neg = toPopupModel({ ...pointModel, clearance_min: -0.5, clearance_max: -0.1 }, meta);
    expect(neg.note).not.toMatch(/-|−/);
  });

  it('B: deeper-than sentence uses lowest observed level from meta; bottom below floor', () => {
    const m = toPopupModel(pointAlwaysWater, meta);
    expect(m.note).toBe(`Głębiej niż 1,95${NB}m (poniżej najniższego zaobserwowanego stanu 192,90${NB}m n.p.m.)`);
    expect(m.rows).toContainEqual({ term: 'Wysokość dna', desc: `< 193,05${NB}m n.p.m.` });
    expect(m.rows).toContainEqual({ term: 'Obserwacje satelitarne', desc: 'brak (zawsze woda)' });
    expect(m.zone?.name).toBe('Bezpieczna');
  });

  it('B: floor falls back to meta.z_max_floor when z_max is null', () => {
    const m = toPopupModel({ ...pointAlwaysWater, z_max: null }, meta);
    expect(m.rows).toContainEqual({ term: 'Wysokość dna', desc: `< 193,05${NB}m n.p.m.` });
  });

  it('C: range above water, open-ended upper bound, level from response', () => {
    const range = toPopupModel({ ...pointLand, bottom_above_water_min: 0.2, bottom_above_water_max: 0.6 }, meta);
    expect(range.title).toBe('W tym miejscu');
    expect(range.note).toBe(`Dno 0,20–0,60${NB}m powyżej lustra wody przy 195,00${NB}m n.p.m.`);
    expect(range.zone?.name).toBe('Zbyt płytka / ląd');
    expect(range.rows).toContainEqual({ term: 'Wysokość terenu', desc: `196,50${NB}m n.p.m. ± 0,30` });
    const open = toPopupModel(pointLand, meta);
    expect(open.note).toBe(`Dno co najmniej 1,00${NB}m powyżej lustra wody`);
  });

  it('D: model coverage up to Max PP from meta, no zone', () => {
    const m = toPopupModel(pointOutside, meta);
    expect(m.note).toBe(`Model obejmuje czaszę zbiornika do rzędnej Max PP 198,89${NB}m n.p.m. Tutaj nie ma danych o dnie.`);
    expect(m.noZone).toBe('Bez oceny strefy');
    expect(m.zone).toBeUndefined();
    expect(m.rows).toEqual([]);
  });

  it('survives non-finite numbers from a broken backend', () => {
    const bad: Point = { ...pointModel, depth_min: NaN, depth_max: Infinity, z: NaN, unc: Infinity, obs_count: NaN };
    expect(JSON.stringify(toPopupModel(bad, meta))).not.toMatch(/null|NaN|Infinity|undefined|—/);
    const bad2: Point = { ...pointLand, bottom_above_water_min: NaN, bottom_above_water_max: NaN };
    expect(JSON.stringify(toPopupModel(bad2, meta))).not.toMatch(/null|NaN|Infinity|undefined|—/);
  });
});

function setup(initial: { pin?: { lon: number; lat: number }; params: { h: number; draft: number; margin: number } }) {
  const client = createQueryClient({ retry: false });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook((p: typeof initial) => usePointVm(p.pin, p.params), { wrapper, initialProps: initial });
}

describe('usePointVm', () => {
  beforeEach(() => {
    pointMock.mockReset();
    pointMock.mockResolvedValue(pointModel);
    vi.mocked(api.meta).mockReset();
    vi.mocked(api.meta).mockResolvedValue(meta);
  });

  it('is idle and does not call the API without a pin', async () => {
    const { result } = setup({ params: { h: 195, draft: 1.2, margin: 0.3 } });
    await new Promise((r) => setTimeout(r, 30));
    expect(result.current.status).toBe('idle');
    expect(result.current.popup).toBeUndefined();
    expect(pointMock).not.toHaveBeenCalled();
  });

  it('requests with rounded coords/params, passes signal, returns popup', async () => {
    const { result } = setup({ pin: { lon: 17.0500004, lat: 50.4499996 }, params: { h: 195.02, draft: 1.2, margin: 0.3 } });
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.popup?.variant).toBe('A');
    expect(pointMock).toHaveBeenCalledWith(
      { lon: 17.05, lat: 50.45, h: 195, draft: 1.2, margin: 0.3 },
      expect.any(AbortSignal),
    );
  });

  it('refreshes for new params and keeps the old popup meanwhile; new pin drops it', async () => {
    const { result, rerender } = setup({ pin: { lon: 17.05, lat: 50.45 }, params: { h: 195, draft: 1.2, margin: 0.3 } });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    pointMock.mockResolvedValueOnce(pointLand);
    rerender({ pin: { lon: 17.05, lat: 50.45 }, params: { h: 196, draft: 1.2, margin: 0.3 } });
    expect(result.current.popup?.variant).toBe('A');
    await waitFor(() => expect(result.current.popup?.variant).toBe('C'));
    pointMock.mockResolvedValueOnce(pointOutside);
    rerender({ pin: { lon: 17.06, lat: 50.46 }, params: { h: 196, draft: 1.2, margin: 0.3 } });
    expect(result.current.popup).toBeUndefined();
    await waitFor(() => expect(result.current.popup?.variant).toBe('D'));
  });

  it('reports error status', async () => {
    pointMock.mockRejectedValue(new Error('boom'));
    const { result } = setup({ pin: { lon: 17.05, lat: 50.45 }, params: { h: 195, draft: 1.2, margin: 0.3 } });
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.popup).toBeUndefined();
  });
});
