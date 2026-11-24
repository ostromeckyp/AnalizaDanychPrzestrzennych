import { QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hazards } from '../test/fixtures';
import { createQueryClient } from './queryClient';
import { toHazardPopupModel, useHazardsVm } from './useHazardsVm';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, hazards: vi.fn() } };
});
import { api } from '../api/client';

const hazardsMock = vi.mocked(api.hazards);
const NB = '\u00a0';
const setup = () =>
  renderHook(() => useHazardsVm(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={createQueryClient({ retry: false })}>{children}</QueryClientProvider>
    ),
  });

beforeEach(() => {
  hazardsMock.mockReset();
});

describe('useHazardsVm', () => {
  it('returns the points and the source as attribution', async () => {
    hazardsMock.mockResolvedValue(hazards);
    const { result } = setup();
    await waitFor(() => expect(result.current.hazards).toBeDefined());
    expect(result.current.attribution).toBe('Klub Żeglarski NYSA, Locja Jeziora Nyskiego');
  });

  it('empty collection leaves the layer absent', async () => {
    hazardsMock.mockResolvedValue({ ...hazards, features: [], source: '' });
    const { result } = setup();
    await waitFor(() => expect(hazardsMock).toHaveBeenCalled());
    expect(result.current.hazards).toBeUndefined();
    expect(result.current.attribution).toBeUndefined();
  });

  it('request failure leaves the layer absent', async () => {
    hazardsMock.mockRejectedValue(new Error('x'));
    const { result } = setup();
    await waitFor(() => expect(hazardsMock).toHaveBeenCalled());
    expect(result.current.hazards).toBeUndefined();
  });
});

describe('toHazardPopupModel', () => {
  const [rafa, grzbiet] = hazards.features;

  it('below the water level: under water with a decimal comma', () => {
    const m = toHazardPopupModel(rafa, 195.25);
    expect(m.title).toBe('Miedniki – żelbetowa rafa');
    expect(m.level).toBe(`Rzędna wierzchołek: 193,7${NB}m n.p.m.`);
    expect(m.relation).toEqual({ kind: 'under', text: `pod wodą: 1,55${NB}m` });
    expect(m.note).toBe('Rzędna z podpisu zdjęcia.');
  });

  it('above the water level: over water; equal level counts as over water', () => {
    expect(toHazardPopupModel(grzbiet, 195.25).relation).toEqual({ kind: 'over', text: `nad wodą: 0,25${NB}m` });
    expect(toHazardPopupModel(rafa, 193.7).relation).toEqual({ kind: 'over', text: `nad wodą: 0,00${NB}m` });
  });

  it('empty note is omitted; unknown level omits the relation', () => {
    const m = toHazardPopupModel(grzbiet, NaN);
    expect(m.note).toBeUndefined();
    expect(m.relation).toBeUndefined();
    expect(m.sourceUrl).toBe('https://kz.nysa.pl/jezioro-nyskie/locja/');
    expect(m.disclaimer).toBe('Położenie orientacyjne, nie znak nawigacyjny.');
  });
});
