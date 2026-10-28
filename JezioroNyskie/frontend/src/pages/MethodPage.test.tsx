import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { meta } from '../test/fixtures';
import { createQueryClient } from '../vm/queryClient';
import { MethodPage } from './MethodPage';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, meta: vi.fn() } };
});
import { api } from '../api/client';
const m = vi.mocked(api);

function renderPage() {
  return render(
    <QueryClientProvider client={createQueryClient({ retry: false })}>
      <MemoryRouter initialEntries={['/metoda']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <MethodPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const tile = (name: string) => screen.getByRole('group', { name });

beforeEach(() => m.meta.mockReset().mockResolvedValue(meta));

describe('MethodPage', () => {
  it('shows loading status then content', async () => {
    renderPage();
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Jak powstaje mapa głębokości' })).toBeInTheDocument();
  });

  it('accuracy tiles from meta, Polish numbers, RMSE pending', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Jak powstaje mapa głębokości' });
    expect(tile('Zgodność maski wody (OA)')).toHaveTextContent('81,6%');
    expect(tile('Zrównoważona trafność (BA)')).toHaveTextContent('77,2%');
    expect(tile('Liczba scen')).toHaveTextContent('3okres 12.04.2025–20.10.2026');
    expect(tile('Zakres poziomów')).toHaveTextContent('192,90–197,92');
    expect(tile('RMSE dna')).toHaveTextContent(/w przygotowaniu/);
  });

  it('RMSE tile shows the value from the API with its caption', async () => {
    m.meta.mockResolvedValue({ ...meta, accuracy: { ...meta.accuracy, bottom_rmse_nmt: 1.51 } });
    renderPage();
    await screen.findByRole('heading', { name: 'Jak powstaje mapa głębokości' });
    expect(tile('RMSE dna')).toHaveTextContent('1,51 mvs NMT LiDAR, bloki walidacyjne');
  });

  it('chart renders one dot per area_level point and NPP/Max PP lines', async () => {
    const { container } = renderPage();
    await screen.findByRole('heading', { name: 'Jak powstaje mapa głębokości' });
    expect(container.querySelectorAll('.chart__svg circle')).toHaveLength(meta.area_level.points.length);
    expect(screen.getByRole('img', { name: /^NPP 195,91\sm n\.p\.m\.$/ })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /^Max PP 198,89\sm n\.p\.m\.$/ })).toBeInTheDocument();
  });

  it('step 03 mentions RZGW and the area–level curve, not only RZGW', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Jak powstaje mapa głębokości' });
    const card = screen.getByRole('heading', { name: 'Linie brzegowe' }).closest('li')!;
    expect(card).toHaveTextContent(/RZGW/);
    expect(card).toHaveTextContent(/krzywej powierzchnia–poziom/);
  });

  it('sources table, author footer and disclaimer', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Jak powstaje mapa głębokości' });
    const table = screen.getByRole('table', { name: 'Źródła danych' });
    for (const s of ['Copernicus Sentinel-2', 'Wody Polskie \\(RZGW\\)', 'Wiktor Wróblewski', 'OpenStreetMap', 'GUGiK']) {
      expect(within(table).getAllByText(new RegExp(s)).length).toBeGreaterThan(0);
    }
    expect(
      screen.getByText('Projekt na przedmiot Analiza Danych Przestrzennych, Politechnika Opolska · Paweł Ostromecki'),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Nie służy do nawigacji/).length).toBeGreaterThan(0);
  });

  it('error offers retry', async () => {
    m.meta.mockReset().mockRejectedValueOnce(new Error('x')).mockResolvedValue(meta);
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Spróbuj ponownie' }));
    expect(await screen.findByRole('heading', { name: 'Jak powstaje mapa głębokości' })).toBeInTheDocument();
  });
});
