import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
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

beforeEach(() => {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: false,
    media: q,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
  vi.mocked(api).meta.mockReset().mockResolvedValue({
    ...meta,
    validation: {
      checks: [{ name: 'Hold-out roczny', compared_with: 'linie wody', result: 'MAE 0,5 m' }],
      bands: [{ band: '< 192,9 m', range_m: null, dominant: null, note: 'Brak pomiarów.' }],
      lidar_note: 'Uwaga LiDAR.',
    },
  });
});

describe('MethodPage mobile', () => {
  it('renders the validation section with a scrollable table container', async () => {
    const { container } = render(
      <QueryClientProvider client={createQueryClient({ retry: false })}>
        <MemoryRouter initialEntries={['/metoda']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <MethodPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole('heading', { name: 'Jak sprawdziliśmy model' })).toBeInTheDocument();
    expect(container.querySelector('.method--mobile')).not.toBeNull();
    expect(container.querySelector('.sources table[aria-label="Zakres błędu dna"]')).not.toBeNull();
  });
});
