import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Meta } from '../api/client';
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

const validation: NonNullable<Meta['validation']> = {
  checks: [
    { name: 'Hold-out roczny', compared_with: 'linie wody tego roku', result: 'MAE 0,5 m' },
    { name: 'NMT LiDAR', compared_with: 'teren odsłonięty', result: 'MAE 1,2 m' },
    { name: 'Mapa KŻ', compared_with: 'model sprzed powodzi', result: 'MAE 0,8 m' },
    { name: 'Tabela pojemności', compared_with: 'poziomy RZGW', result: 'zgodna' },
    { name: 'Objętość', compared_with: 'komunikaty RZGW', result: 'rząd wielkości' },
  ],
  bands: [
    { band: '≥ 194,8 m', range_m: [0.6, 1.3], dominant: 'NMT LiDAR', note: 'n1' },
    { band: '192,9–194,8 m', range_m: [1.04, 1.34], dominant: 'mapa KŻ (model sprzed powodzi)', note: 'n2' },
    { band: '< 192,9 m', range_m: null, dominant: null, note: 'Brak pomiarów w tym paśmie.' },
  ],
  lidar_note: 'LiDAR obejmuje tylko odsłonięty teren.',
};

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

  it('validation section: heading, five checks, bands with ranges and no-data row', async () => {
    m.meta.mockResolvedValue({ ...meta, validation });
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Jak sprawdziliśmy model' })).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Kontrole modelu' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(5);
    expect(list).toHaveTextContent('Hold-out roczny — linie wody tego roku');
    const table = screen.getByRole('table', { name: 'Zakres błędu dna' });
    expect(within(table).getByText('1,04–1,34 m')).toBeInTheDocument();
    expect(within(table).getByText('mapa KŻ (model sprzed powodzi)')).toBeInTheDocument();
    const row = within(table).getByText('< 192,9 m').closest('tr')!;
    expect(row).toHaveTextContent('brak danych');
    expect(row).toHaveTextContent('Brak pomiarów w tym paśmie.');
    expect(screen.getByText('Główne źródło = kontrola z największym błędem w paśmie.')).toBeInTheDocument();
    expect(within(table).getByText('1,04–1,34 m')).toHaveClass('val__range');
    expect(screen.getByText('LiDAR obejmuje tylko odsłonięty teren.')).toBeInTheDocument();
  });

  it('no validation: section hidden', async () => {
    m.meta.mockResolvedValue({ ...meta, validation: null });
    renderPage();
    await screen.findByRole('heading', { name: 'Jak powstaje mapa głębokości' });
    expect(screen.queryByRole('heading', { name: 'Jak sprawdziliśmy model' })).not.toBeInTheDocument();
  });

  it('hold-out tile only when holdout_mae is present', async () => {
    m.meta.mockResolvedValue({ ...meta, accuracy: { ...meta.accuracy, holdout_mae: 0.52, holdout_n_scenes: 155 } });
    renderPage();
    await screen.findByRole('heading', { name: 'Jak powstaje mapa głębokości' });
    expect(tile('Hold-out roczny (MAE)')).toHaveTextContent(
      '0,52 mmodel bez danego roku vs linie wody tego roku, 155 scen',
    );
  });

  it('no hold-out tile when holdout_mae is null', async () => {
    m.meta.mockResolvedValue({ ...meta, accuracy: { ...meta.accuracy, holdout_mae: null } });
    renderPage();
    await screen.findByRole('heading', { name: 'Jak powstaje mapa głębokości' });
    expect(screen.queryByRole('group', { name: 'Hold-out roczny (MAE)' })).not.toBeInTheDocument();
  });
});
