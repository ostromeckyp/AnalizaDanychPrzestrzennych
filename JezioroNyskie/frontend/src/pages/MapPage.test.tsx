import { QueryClientProvider, onlineManager } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Meta } from '../api/client';
import {
  currentLevel,
  meta,
  pointLand,
  pointModel,
  pointOutside,
  zones as zonesFixture,
} from '../test/fixtures';
import { createQueryClient } from '../vm/queryClient';
import { MapPage } from './MapPage';

// Atrapa mapy: zapamiętuje ostatnie propsy i pozwala „kliknąć” w mapę.
const mapProps = vi.hoisted(() => ({ last: undefined as Record<string, unknown> | undefined }));
vi.mock('../components/map/MapView', () => ({
  MapView: (props: { onMapClick: (lon: number, lat: number) => void; pin?: unknown } & Record<string, unknown>) => {
    mapProps.last = props;
    return (
      <div data-testid="map">
        <button onClick={() => props.onMapClick(17.05, 50.45)}>klik-mapa</button>
        <button onClick={() => props.onMapClick(17.07, 50.43)}>klik-mapa-2</button>
        {props.pin ? (props.pinOverlay as React.ReactNode) : null}
      </div>
    );
  },
}));

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return {
    ...mod,
    api: {
      ...mod.api,
      meta: vi.fn(),
      zones: vi.fn(),
      point: vi.fn(),
      currentLevel: vi.fn(),
      marinas: vi.fn(),
      gravel: vi.fn(),
      capacityToLevel: vi.fn(),
      levelToCapacity: vi.fn(),
    },
  };
});
import { api } from '../api/client';

const NB = ' ';
const m = vi.mocked(api);
const visibleNow = () => mapProps.last!.visible as Record<string, boolean>;

function renderPage(url = '/', metaOverride?: Partial<Meta>) {
  m.meta.mockResolvedValue({ ...meta, ...metaOverride });
  const client = createQueryClient({ retry: false });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <MapPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mapProps.last = undefined;
  for (const f of Object.values(m)) if (typeof f === 'function' && 'mockReset' in f) (f as ReturnType<typeof vi.fn>).mockReset();
  m.zones.mockImplementation(async (p) => zonesFixture(p.h, p.draft, p.margin));
  m.point.mockResolvedValue(pointModel);
  m.currentLevel.mockResolvedValue({ ...currentLevel, h: 195.6 });
  m.marinas.mockResolvedValue({ type: 'FeatureCollection', features: [] });
  m.gravel.mockRejectedValue(new Error('404'));
  m.capacityToLevel.mockResolvedValue({ h: 195, in_table: true } as never);
  m.levelToCapacity.mockResolvedValue({ v: 45.6, in_table: true } as never);
});

afterEach(() => {
  act(() => onlineManager.setOnline(true));
});

describe('MapPage', () => {
  it('state A: skeleton until meta and first zones arrive, then the panel', async () => {
    renderPage();
    expect(screen.getByRole('status')).toHaveTextContent('Wczytuję model dna i strefy…');
    expect(await screen.findByRole('region', { name: 'Parametry' })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Wczytuję model dna i strefy…')).not.toBeInTheDocument());
    expect(screen.getByRole('contentinfo')).toHaveTextContent('Nie służy do nawigacji');
    expect(screen.getByRole('link', { name: 'O metodzie' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Legenda' })).toBeInTheDocument();
  });

  describe('initial h', () => {
    const firstZonesH = async () => {
      await waitFor(() => expect(m.zones).toHaveBeenCalled());
      return m.zones.mock.calls[0][0].h;
    };
    it('?h= beats current level', async () => {
      renderPage('/?h=195.25');
      expect(await firstZonesH()).toBe(195.25);
    });
    it('current level beats meta default; invalid ?h= is ignored', async () => {
      renderPage('/?h=abc');
      expect(await firstZonesH()).toBe(195.6);
    });
    it('meta default when current level fails', async () => {
      m.currentLevel.mockRejectedValue(new Error('x'));
      renderPage();
      expect(await firstZonesH()).toBe(meta.defaults.h);
    });
    it('clamped to slider range and rounded to 0,05', async () => {
      renderPage('/?h=250');
      expect(await firstZonesH()).toBe(meta.slider.max);
    });
    it('clamps low values too', async () => {
      renderPage('/?h=100');
      expect(await firstZonesH()).toBe(meta.slider.min);
    });
    it('is decided once: the user moving the slider is not overridden by a later current level', async () => {
      renderPage('/?h=195.25');
      const slider = await screen.findByRole('slider');
      fireEvent.change(slider, { target: { value: '196' } });
      await waitFor(() => expect(m.zones).toHaveBeenLastCalledWith(expect.objectContaining({ h: 196 }), expect.anything()));
    });
  });

  it('state D: error shows last good params, retry refetches', async () => {
    renderPage();
    await screen.findByRole('region', { name: 'Parametry' });
    await waitFor(() => expect(m.zones).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText('Wczytuję model dna i strefy…')).not.toBeInTheDocument());
    m.zones.mockRejectedValueOnce(new Error('boom'));
    await userEvent.click(screen.getByRole('button', { name: 'Zwiększ zanurzenie o 0,05 m' }));
    const alert = await screen.findByRole('alert', {}, { timeout: 2000 });
    expect(alert).toHaveTextContent('Nie udało się przeliczyć stref');
    expect(alert.textContent).toContain(`(1,20${NB}m · 195,60${NB}m n.p.m.)`);
    const calls = m.zones.mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }));
    await waitFor(() => expect(m.zones.mock.calls.length).toBeGreaterThan(calls));
    await waitFor(() => expect(screen.queryByText('Nie udało się przeliczyć stref')).not.toBeInTheDocument());
  });

  it('state E: offline bar shows time of last good zones; retry button present', async () => {
    renderPage();
    await waitFor(() => expect(screen.queryByText('Wczytuję model dna i strefy…')).not.toBeInTheDocument());
    await screen.findByRole('region', { name: 'Parametry' });
    act(() => onlineManager.setOnline(false));
    const bar = await screen.findByText(/Brak połączenia\. Strefy z \d{2}:\d{2} mogą być nieaktualne\./);
    expect(bar).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ponów' })).toBeInTheDocument();
  });

  it('state B + changing draft re-requests zones, does not close the popup, popup refreshes', async () => {
    renderPage();
    await waitFor(() => expect(screen.queryByText('Wczytuję model dna i strefy…')).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'klik-mapa' }));
    const dlg = await screen.findByRole('dialog', { name: 'Informacje o punkcie' });
    await within(dlg).findByText(/Ryzykowna/);
    expect(m.point).toHaveBeenLastCalledWith(expect.objectContaining({ draft: 1.2 }), expect.anything());

    await userEvent.click(screen.getByRole('button', { name: 'Zwiększ zanurzenie o 0,05 m' }));
    expect(screen.getByText(/Przeliczam strefy dla 1,25/)).toBeInTheDocument();
    await waitFor(() => expect(m.zones).toHaveBeenLastCalledWith(expect.objectContaining({ draft: 1.25 }), expect.anything()));
    await waitFor(() => expect(m.point).toHaveBeenLastCalledWith(expect.objectContaining({ draft: 1.25 }), expect.anything()));
    expect(screen.getByRole('dialog', { name: 'Informacje o punkcie' })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/Przeliczam strefy dla/)).not.toBeInTheDocument());
  });

  it('state C: warning alert in panel forces the uncertainty layer without flipping the user toggle', async () => {
    m.zones.mockImplementation(async (p) => ({ ...zonesFixture(p.h, p.draft, p.margin), warnings: p.h < 195 ? ['h_out_of_range'] : [] }));
    renderPage('/?h=192.5');
    const alert = await screen.findByText(/Poziom poza zakresem obserwacji/);
    expect(alert.closest('[role="alert"]')).toBeInTheDocument();
    await waitFor(() => expect(visibleNow().uncertainty).toBe(true));
    fireEvent.change(screen.getByRole('slider'), { target: { value: '196' } });
    await waitFor(() => expect(visibleNow().uncertainty).toBe(false));
  });

  it('popup: hint without pin; variants from API kind; close clears pin', async () => {
    renderPage();
    await screen.findByRole('region', { name: 'Parametry' });
    expect(await screen.findByText('Kliknij w wodę, aby sprawdzić głębokość')).toBeInTheDocument();
    m.point.mockResolvedValue(pointLand);
    await userEvent.click(screen.getByRole('button', { name: 'klik-mapa' }));
    expect(mapProps.last!.pin).toEqual({ lon: 17.05, lat: 50.45 });
    const dlg = await screen.findByRole('dialog', { name: 'Informacje o punkcie' });
    await within(dlg).findByText('Ląd');
    expect(screen.queryByText('Kliknij w wodę, aby sprawdzić głębokość')).not.toBeInTheDocument();
    expect(dlg.textContent).not.toMatch(/null|NaN|Infinity|undefined/);
    await userEvent.click(within(dlg).getByRole('button', { name: 'Zamknij' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mapProps.last!.pin).toBeUndefined();

    m.point.mockResolvedValue(pointOutside);
    await userEvent.click(screen.getByRole('button', { name: 'klik-mapa-2' }));
    expect(await screen.findByText('Poza obszarem modelu')).toBeInTheDocument();
    expect(screen.getByText('Bez oceny strefy')).toBeInTheDocument();
  });

  it('popup shows an error message when the point request fails', async () => {
    renderPage();
    await screen.findByRole('region', { name: 'Parametry' });
    m.point.mockRejectedValue(new Error('x'));
    await userEvent.click(screen.getByRole('button', { name: 'klik-mapa' }));
    expect(await screen.findByText('Nie udało się pobrać danych punktu.')).toBeInTheDocument();
  });

  it('passes raw layer urls (theme suffix belongs to MapView) and meta bbox/npp to the map', async () => {
    renderPage();
    await waitFor(() => expect(mapProps.last?.npp).toBe(meta.npp));
    expect(mapProps.last!.bbox).toEqual(meta.bbox_wgs84);
    expect((mapProps.last!.bottomLayer as { url: string }).url).toBe('/api/layers/bottom.png');
    expect(mapProps.last!.basemap).toBe('osm');
  });

  it('?h= does not wait for a slow current-level query', async () => {
    m.currentLevel.mockReturnValue(new Promise(() => {}));
    renderPage('/?h=195.25');
    await waitFor(() => expect(m.zones).toHaveBeenCalledWith(expect.objectContaining({ h: 195.25 }), expect.anything()));
  });

  it('Escape closes the focused popup', async () => {
    renderPage();
    await screen.findByText('Kliknij w wodę, aby sprawdzić głębokość');
    await userEvent.click(screen.getByRole('button', { name: 'klik-mapa' }));
    const dlg = await screen.findByRole('dialog', { name: 'Informacje o punkcie' });
    await waitFor(() => expect(dlg).toHaveFocus());
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('capacity mode: map level always equals the panel result after mode round-trips', async () => {
    renderPage('/?h=194');
    await screen.findByText('Kliknij w wodę, aby sprawdzić głębokość');
    await userEvent.click(screen.getByRole('button', { name: 'Pojemność' }));
    await screen.findByText(/→ poziom/);
    await waitFor(() => expect(m.zones).toHaveBeenLastCalledWith(expect.objectContaining({ h: 195 }), expect.anything()));
    await userEvent.click(screen.getByRole('button', { name: 'Rzędna' }));
    fireEvent.change(screen.getByRole('slider'), { target: { value: '196' } });
    await waitFor(() => expect(m.zones).toHaveBeenLastCalledWith(expect.objectContaining({ h: 196 }), expect.anything()));
    await userEvent.click(screen.getByRole('button', { name: 'Pojemność' }));
    await screen.findByText(/→ poziom/);
    // strefy dla 195 są już w cache, więc sprawdzamy to, co dostaje mapa
    await waitFor(() => expect((mapProps.last!.zones as { params: { h: number } }).params.h).toBe(195));
    expect(screen.getByRole('slider')).toHaveValue('195');
  });
});
