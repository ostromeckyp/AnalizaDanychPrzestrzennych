import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './client';
import { currentLevel, meta, scenes } from '../test/fixtures';

function mockFetch(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
  vi.stubGlobal('fetch', f);
  return f;
}

afterEach(() => vi.unstubAllGlobals());

describe('api', () => {
  it('zones: kropki dziesiętne i ApiError z detail', async () => {
    const detail = [{ loc: ['query', 'h'], msg: 'x', type: 'value_error' }];
    const f = mockFetch(422, { detail });
    const err = await api.zones({ h: 195.25, draft: 1.2, margin: 0.3 }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 422, detail });
    expect(f).toHaveBeenCalledWith('/api/zones?h=195.25&draft=1.2&margin=0.3', expect.anything());
  });

  it('przekazuje signal', async () => {
    const f = mockFetch(200, {});
    const ac = new AbortController();
    await api.zones({ h: 1, draft: 1, margin: 0 }, ac.signal);
    expect(f.mock.calls[0][1]).toMatchObject({ signal: ac.signal });
  });

  it('point: wszystkie parametry', async () => {
    const f = mockFetch(200, {});
    await api.point({ lon: 17.1, lat: 50.5, h: 194.2, draft: 1.2, margin: 0.3 });
    expect(f.mock.calls[0][0]).toBe('/api/point?lon=17.1&lat=50.5&h=194.2&draft=1.2&margin=0.3');
  });

  it.each([
    ['meta', () => api.meta(), '/api/meta', meta],
    ['scenes', () => api.scenes(), '/api/scenes', scenes],
    ['marinas', () => api.marinas(), '/api/marinas', { type: 'FeatureCollection', features: [] }],
    ['currentLevel', () => api.currentLevel(), '/api/current-level', currentLevel],
    ['shoreline', () => api.shoreline('2026-10-20'), '/api/shorelines?date=2026-10-20', {}],
    ['capacityToLevel', () => api.capacityToLevel(45.6), '/api/capacity-to-level?v=45.6', {}],
    ['levelToCapacity', () => api.levelToCapacity(194.2), '/api/level-to-capacity?h=194.2', {}],
  ])('%s: ścieżka i zwrot JSON', async (_n, call, url, body) => {
    const f = mockFetch(200, body);
    await expect(call()).resolves.toEqual(body);
    expect(f.mock.calls[0][0]).toBe(url);
  });

  it('błąd bez JSON: ApiError z detail undefined', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 503, json: async () => { throw new Error('no json'); },
    }));
    await expect(api.meta()).rejects.toMatchObject({ status: 503, detail: undefined });
  });
});
