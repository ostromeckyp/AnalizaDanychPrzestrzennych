import { QueryClientProvider, onlineManager } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Meta } from '../api/client';
import {
  currentLevel,
  meta,
  pointModel,
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
      capacityToLevel: vi.fn(),
      levelToCapacity: vi.fn(),
    },
  };
});
import { api } from '../api/client';

const m = vi.mocked(api);

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
  m.capacityToLevel.mockResolvedValue({ h: 195, in_table: true } as never);
  m.levelToCapacity.mockResolvedValue({ v: 45.6, in_table: true } as never);
});

afterEach(() => {
  act(() => onlineManager.setOnline(true));
});


function mockViewport(width: number) {
  window.matchMedia = vi.fn((q: string) => ({
    matches: q.includes('min-width: 768px') ? width >= 768 : false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as never;
}

afterEach(() => {
  // @ts-expect-error sprzątanie atrapy
  delete window.matchMedia;
});

describe('MapPage mobile (< 768 px)', () => {
  beforeEach(() => mockViewport(390));

  it('renders header, collapsed sheet with the same VM data, and the disclaimer; no desktop nav', async () => {
    renderPage();
    expect(await screen.findByRole('button', { name: 'Zwiększ zanurzenie' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Historia linii brzegowych' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'O metodzie' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Widoki' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^(Zwiń panel|Rozwiń panel parametrów)$/ })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: /Poziom wody.*195,60/ })).toBeInTheDocument();
    expect(screen.getByText(/Nie służy do nawigacji/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Legenda' })).toBeInTheDocument();
    expect(screen.getByTestId('map')).toBeInTheDocument();
  });

  it('skeleton state still shows the disclaimer', () => {
    renderPage();
    expect(screen.getByRole('status')).toHaveTextContent('Wczytuję model dna i strefy…');
    expect(screen.getByText(/Nie służy do nawigacji/)).toBeInTheDocument();
  });

  it('stepper in the collapsed sheet drives the shared VM: zones refetch, recalc pill', async () => {
    renderPage();
    await screen.findByRole('button', { name: 'Zwiększ zanurzenie' });
    await waitFor(() => expect(screen.queryByText('Wczytuję model dna i strefy…')).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Zwiększ zanurzenie' }));
    expect(screen.getByText(/Przeliczam strefy dla 1,25/)).toBeInTheDocument();
    await waitFor(() => expect(m.zones).toHaveBeenLastCalledWith(expect.objectContaining({ draft: 1.25 }), expect.anything()));
  });

  it('expanding via the level shortcut shows the full panel, chips and short mobile texts', async () => {
    m.zones.mockImplementation(async (p) => ({ ...zonesFixture(p.h, p.draft, p.margin), warnings: ['h_out_of_range'] }));
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: /Poziom wody/ }));
    expect(screen.getByRole('slider')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Strefy dla jachtu' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Podaj pojemność (mln m³)' })).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('Poza zakresem obserwacji. Model dna jest ekstrapolowany');
    await userEvent.click(screen.getByRole('button', { name: 'Pokaż mapę' }));
    expect(screen.queryByRole('slider')).not.toBeInTheDocument();
  });

  it('popup works on mobile (anchored overlay from the same VM)', async () => {
    renderPage();
    await screen.findByRole('button', { name: 'Zwiększ zanurzenie' });
    await userEvent.click(screen.getByRole('button', { name: 'klik-mapa' }));
    const dlg = await screen.findByRole('dialog', { name: 'Informacje o punkcie' });
    await within(dlg).findByText(/Ryzykowna/);
    await userEvent.click(within(dlg).getByRole('button', { name: 'Zamknij' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('state D: error overlay renders on mobile with retry', async () => {
    renderPage();
    await screen.findByRole('button', { name: 'Zwiększ zanurzenie' });
    await waitFor(() => expect(screen.queryByText('Wczytuję model dna i strefy…')).not.toBeInTheDocument());
    m.zones.mockRejectedValueOnce(new Error('boom'));
    await userEvent.click(screen.getByRole('button', { name: 'Zwiększ zanurzenie' }));
    expect(await screen.findByRole('alert', {}, { timeout: 2000 })).toHaveTextContent('Nie udało się przeliczyć stref');
    expect(screen.getByRole('button', { name: 'Spróbuj ponownie' })).toBeInTheDocument();
    expect(screen.getByText(/Nie służy do nawigacji/)).toBeInTheDocument();
  });

  it('state E: offline bar renders on mobile', async () => {
    renderPage();
    await screen.findByRole('button', { name: 'Zwiększ zanurzenie' });
    await waitFor(() => expect(screen.queryByText('Wczytuję model dna i strefy…')).not.toBeInTheDocument());
    act(() => onlineManager.setOnline(false));
    expect(await screen.findByText(/Brak połączenia\. Strefy z \d{2}:\d{2}/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ponów' })).toBeInTheDocument();
  });

  it('the page root carries the mobile modifier', async () => {
    renderPage();
    await screen.findByRole('button', { name: 'Zwiększ zanurzenie' });
    expect(screen.getByRole('main')).toHaveClass('mappage--mobile');
  });
});

describe('MapPage at >= 768 px', () => {
  it('keeps the desktop layout', async () => {
    mockViewport(1024);
    renderPage();
    expect(await screen.findByRole('region', { name: 'Parametry' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Widoki' })).toBeInTheDocument();
    expect(screen.getByRole('main')).not.toHaveClass('mappage--mobile');
  });
});
