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
// Szukamy placeholderów (null/NaN/„—”) w danych; stałe zastrzeżenie `caveat` ma myślnik celowo, więc je pomijamy.
const artefacts = (m: ReturnType<typeof toPopupModel>) => JSON.stringify({ ...m, caveat: undefined });

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
    expect(artefacts(m)).not.toMatch(/null|NaN|Infinity|undefined|—/);
  });

  it('popup adds gravel warning row only when gravel is true', () => {
    expect(toPopupModel(pointModel, meta).rows.some((r) => /Dno zmienne/.test(r.term))).toBe(false);
    const row = toPopupModel({ ...pointModel, gravel: true }, meta).rows.at(-1)!;
    expect(row.term).toMatch(/Dno zmienne \(eksploatacja kruszywa\)/);
    expect(row.desc).toBe('model może być nieaktualny.');
    expect(row.warning).toBe(true);
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

  it('A: depth range carries the "not a confidence interval" caveat; single value and other variants do not', () => {
    const caveat = 'Przedział obejmuje dno w ok. 90 % sprawdzonych przypadków.';
    expect(toPopupModel(pointModel, meta).caveat).toBe(caveat);
    expect(toPopupModel({ ...pointModel, depth_min: 1.5, depth_max: 1.5 }, meta).caveat).toBe(caveat);
    expect(toPopupModel({ ...pointModel, depth_min: null, depth_max: null }, meta).caveat).toBeUndefined();
    for (const p of [pointAlwaysWater, pointLand, pointOutside]) expect(toPopupModel(p, meta).caveat).toBeUndefined();
  });

  it('A: caveat uses calibration coverage from meta rounded to whole percent, with a fallback', () => {
    const withCov = (c: number | null) => ({ ...meta, accuracy: { ...meta.accuracy, calibration_coverage: c } });
    expect(toPopupModel(pointModel, withCov(0.9)).caveat).toBe('Przedział obejmuje dno w ok. 90 % sprawdzonych przypadków.');
    expect(toPopupModel(pointModel, withCov(0.874)).caveat).toBe('Przedział obejmuje dno w ok. 87 % sprawdzonych przypadków.');
    expect(toPopupModel(pointModel, withCov(null)).caveat).toBe('Zakres głębokości jest orientacyjny — nie jest przedziałem ufności.');
  });

  it('A: bottom source row for satellite and for KŻ (interpolation error as deeper/shallower than the map, own caveat)', () => {
    const sat = toPopupModel(pointModel, meta);
    expect(sat.rows).toContainEqual({ term: 'Dno', desc: 'model satelitarny' });
    expect(sat.caveat).not.toMatch(/Mapa KŻ/);
    const kz = toPopupModel({ ...pointModel, bottom_source: 'kz', kz_interp: { p5: -2.0, p95: 3.02 } }, meta);
    expect(kz.rows).toContainEqual({
      term: 'Dno',
      desc: `mapa KŻ 2023 (orientacyjne): dno do 3,0${NB}m głębiej albo do 2,0${NB}m płycej niż na mapie (błąd interpolacji)`,
    });
    // dno z mapy KŻ: bez pokrycia kalibracji satelity (P5–P95 to z definicji 90 % błędów sprawdzianu)
    expect(kz.caveat).toBe(
      'Przedział dna z mapy KŻ obejmuje 90 % błędów interpolacji ze sprawdzianu (punkt odłożony).' +
        ' Mapa KŻ opisuje dno z 2023 r.; poniżej 192,5 m jest orientacyjna. Mapa amatorska; ryzyko korzystania ponosi użytkownik.',
    );
    expect(kz.caveat).not.toMatch(/sprawdzonych przypadków/);
    expect(kz.value).toBe(`1,00–2,00${NB}m`);
    expect(artefacts(kz)).not.toMatch(/null|NaN|Infinity|undefined|—/);
    expect(kz.caveat).not.toMatch(/null|NaN|Infinity|undefined|—/);
    const kzNoInterp = toPopupModel({ ...pointModel, bottom_source: 'kz', kz_interp: null }, meta);
    expect(kzNoInterp.rows).toContainEqual({ term: 'Dno', desc: 'mapa KŻ 2023 (orientacyjne)' });
    const kzNoDepth = toPopupModel({ ...pointModel, bottom_source: 'kz', depth_min: null, depth_max: null }, meta);
    expect(kzNoDepth.caveat).toBe('Mapa KŻ opisuje dno z 2023 r.; poniżej 192,5 m jest orientacyjna. Mapa amatorska; ryzyko korzystania ponosi użytkownik.');
  });

  it('A: without combined bounds the caveat never quotes calibration coverage', () => {
    const raw = { ...meta, accuracy: { ...meta.accuracy, combined_bounds: false } };
    expect(toPopupModel(pointModel, raw).caveat).toBe('Zakres głębokości jest orientacyjny — nie jest przedziałem ufności.');
  });

  it('B: KŻ conflict adds a warning row next to the satellite source row', () => {
    const m = toPopupModel({ ...pointAlwaysWater, kz_conflict: true }, meta);
    expect(m.rows).toContainEqual({
      term: 'Mapa KŻ jest tu sprzeczna z satelitą',
      desc: 'pokazujemy tylko model satelitarny.',
      warning: true,
    });
    expect(m.rows).toContainEqual({ term: 'Dno', desc: 'model satelitarny' });
    expect(artefacts(m)).not.toMatch(/null|NaN|Infinity|undefined|—/);
    expect(toPopupModel(pointAlwaysWater, meta).rows.some((r) => /sprzeczna z satelitą/.test(r.term))).toBe(false);
  });

  // piksel „zawsze woda” bez KŻ, którego skalibrowana górna granica dna leży nie niżej niż h − zanurzenie
  const awUnassessed: Point = {
    ...pointAlwaysWater, h: 195.0, draft: 0.5, z_max: 195.28, z_max_sat: 193.05,
    depth_min: 0, clearance_min: -0.5, zone: 'risk',
  };
  const NOTE_UNASSESSED =
    `Satelita widział tu zawsze wodę: dno poniżej 193,05${NB}m n.p.m. (najniższy zaobserwowany stan). ` +
    'Po poszerzeniu przedziałów — ekstrapolacji, której tu nie zmierzyliśmy — górna granica dna to ' +
    `195,28${NB}m, więc nie gwarantujemy minimalnej głębokości.`;
  // stałe myślniki w nocie są celowe; skan szuka placeholderów w danych
  const scan = (m: ReturnType<typeof toPopupModel>) =>
    artefacts(m).replace(' — ekstrapolacji, której tu nie zmierzyliśmy — ', ' ');

  it('B: always water with calibrated upper bound near the surface: depth not assessed, both bounds', () => {
    const m = toPopupModel(awUnassessed, meta);
    expect(m.variant).toBe('B');
    expect(m.value).toBe('Głębokość nieoceniona');
    expect(m.note).toBe(NOTE_UNASSESSED);
    expect(m.rows).toContainEqual({ term: 'Dno', desc: 'model satelitarny' });
    expect(m.zone).toEqual({ key: 'risk', name: 'Ryzykowna', label: `dla jachtu 0,50${NB}m` });
    expect(scan(m)).not.toMatch(/null|NaN|Infinity|undefined|—/);
    // granica dokładnie na h − zanurzenie też jest nieoceniona; z_max_sat brak → próg z meta
    expect(toPopupModel({ ...awUnassessed, depth_min: 0.5 }, meta).value).toBe('Głębokość nieoceniona');
    expect(toPopupModel({ ...awUnassessed, z_max_sat: null }, meta).note).toContain(`dno poniżej 193,05${NB}m n.p.m.`);
    const conflict = toPopupModel({ ...awUnassessed, kz_conflict: true }, meta);
    expect(conflict.value).toBe('Głębokość nieoceniona');
    expect(conflict.rows.at(-1)).toEqual({ term: 'Mapa KŻ jest tu sprzeczna z satelitą', desc: 'pokazujemy tylko model satelitarny.', warning: true });
    expect(scan(conflict)).not.toMatch(/null|NaN|Infinity|undefined|—/);
  });

  it('B: unassessed always water outside KŻ reach names the nearest KŻ spot (information only)', () => {
    const m = toPopupModel({ ...awUnassessed, kz_nearest: { z: 189.5, distance_m: 347.2 } }, meta);
    expect(m.value).toBe('Głębokość nieoceniona');
    expect(m.note).toBe(NOTE_UNASSESSED);
    expect(m.rows).toContainEqual({
      term: 'Najbliższy punkt mapy KŻ',
      desc: `189,5${NB}m n.p.m., 350${NB}m stąd (poza zasięgiem interpolacji)`,
    });
    expect(m.zone?.key).toBe('risk');
    expect(scan(m)).not.toMatch(/null|NaN|Infinity|undefined|—/);
    expect(toPopupModel(awUnassessed, meta).rows.some((r) => r.term === 'Najbliższy punkt mapy KŻ')).toBe(false);
    const bad = toPopupModel({ ...awUnassessed, kz_nearest: { z: NaN, distance_m: Infinity } }, meta);
    expect(bad.rows.some((r) => r.term === 'Najbliższy punkt mapy KŻ')).toBe(false);
  });

  it('B: unassessed always water in the gravel pit: gravel sentence first, then the satellite bounds', () => {
    const m = toPopupModel({ ...awUnassessed, gravel: true }, meta);
    expect(m.value).toBe('Wyrobisko żwirowni');
    expect(m.note).toBe(`Wyrobisko żwirowni: dno zmienne, mapa KŻ go nie opisuje. ${NOTE_UNASSESSED}`);
    expect(m.rows.some((r) => r.term === 'Najbliższy punkt mapy KŻ')).toBe(false);
    expect(m.rows.at(-1)).toEqual({ term: 'Dno zmienne (eksploatacja kruszywa)', desc: 'model może być nieaktualny.', warning: true });
    expect(m.zone?.key).toBe('risk');
    expect(scan(m)).not.toMatch(/null|NaN|Infinity|undefined|—/);
  });

  it('B: always water deeper than the draft keeps the deeper-than text and gains the source row', () => {
    const m = toPopupModel(pointAlwaysWater, meta);
    expect(m.value).toBe(`≥ 1,95${NB}m`);
    expect(m.rows).toContainEqual({ term: 'Dno', desc: 'model satelitarny' });
  });

  it('C: land shows the bottom source; KŻ land keeps the UWAGA caveat', () => {
    expect(toPopupModel(pointLand, meta).rows).toContainEqual({ term: 'Dno', desc: 'model satelitarny' });
    const kz = toPopupModel({ ...pointLand, bottom_source: 'kz', kz_interp: { p5: -2.0, p95: 3.02 } }, meta);
    expect(kz.rows.some((r) => r.term === 'Dno' && r.desc.startsWith('mapa KŻ 2023'))).toBe(true);
    expect(kz.caveat).toBe('Mapa KŻ opisuje dno z 2023 r.; poniżej 192,5 m jest orientacyjna. Mapa amatorska; ryzyko korzystania ponosi użytkownik.');
    expect(artefacts(kz)).not.toMatch(/null|NaN|Infinity|undefined|—/);
  });

  it('A: zone label follows API zone, never computed', () => {
    expect(toPopupModel({ ...pointModel, zone: 'safe' }, meta).zone?.name).toBe('Bezpieczna');
    expect(toPopupModel({ ...pointModel, zone: 'danger' }, meta).zone?.name).toBe('Zbyt płytka / ląd');
    expect(toPopupModel({ ...pointModel, zone: null }, meta).zone).toBeUndefined();
  });

  it('A: negative or missing clearance and missing optional numbers produce no artefacts', () => {
    const m = toPopupModel({ ...pointModel, clearance_min: null, clearance_max: null, z: null, unc: null, obs_count: null }, meta);
    expect(artefacts(m)).not.toMatch(/null|NaN|Infinity|undefined|—/);
    expect(m.rows.map((r) => r.term)).toEqual(['Dno', 'Położenie']);
    const neg = toPopupModel({ ...pointModel, clearance_min: -0.5, clearance_max: -0.1 }, meta);
    expect(neg.note).not.toMatch(/-|−/);
  });

  it('B: deeper-than sentence uses lowest observed level from meta; bottom below floor', () => {
    const m = toPopupModel(pointAlwaysWater, meta);
    expect(m.note).toBe(`Głębiej niż 1,95${NB}m (poniżej najniższego zaobserwowanego stanu 192,90${NB}m n.p.m.).`);
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
