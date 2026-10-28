import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { meta, scenes } from '../test/fixtures';
import { createQueryClient } from '../vm/queryClient';
import { HistoryPage } from './HistoryPage';

const mapProps = vi.hoisted(() => ({ last: undefined as Record<string, unknown> | undefined }));
vi.mock('../components/map/MapView', () => ({
  MapView: (props: Record<string, unknown>) => {
    mapProps.last = props;
    return <div data-testid="map" />;
  },
}));
vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, meta: vi.fn(), scenes: vi.fn(), shoreline: vi.fn() } };
});
import { api } from '../api/client';
const m = vi.mocked(api);

function renderPage() {
  return render(
    <QueryClientProvider client={createQueryClient({ retry: false })}>
      <MemoryRouter initialEntries={['/historia']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <HistoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  m.meta.mockReset().mockResolvedValue(meta);
  m.scenes.mockReset().mockResolvedValue(scenes);
  m.shoreline.mockReset().mockResolvedValue({
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: [[17, 50]] },
    properties: scenes[2],
  });
});

describe('HistoryPage', () => {
  it('shows loading status then list, chart, card and map with shorelines', async () => {
    renderPage();
    expect(screen.getByRole('status')).toHaveTextContent('Ładuję sceny');
    expect(await screen.findByText('2 sceny · nałożone: 0')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Wykres poziomu wody/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ustaw ten poziom na mapie' })).toHaveAttribute('href', '/?h=194.2');
    await waitFor(() => expect(screen.getByTestId('map')).toBeInTheDocument());
    expect(mapProps.last).toMatchObject({ visible: { shorelines: true, zones: false }, npp: meta.npp });
    await userEvent.click(screen.getByRole('checkbox', { name: 'Nałóż linię brzegową z 20.10.2026' }));
    await waitFor(() =>
      expect((mapProps.last!.shorelines as { features: unknown[] }).features).toHaveLength(1),
    );
  });

  it('scenes error offers retry', async () => {
    m.scenes.mockRejectedValueOnce(new Error('x'));
    renderPage();
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }));
    expect(await screen.findByText('2 sceny · nałożone: 0')).toBeInTheDocument();
  });
});
