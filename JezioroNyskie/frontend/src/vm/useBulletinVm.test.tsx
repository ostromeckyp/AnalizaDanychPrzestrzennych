import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryClient } from './queryClient';
import { useBulletinVm } from './useBulletinVm';

vi.mock('../api/client', async (orig) => {
  const mod = await orig<typeof import('../api/client')>();
  return { ...mod, api: { ...mod.api, bulletinLatest: vi.fn() } };
});
import { ApiError, api } from '../api/client';

const NB = ' ';
const bulletin = {
  bulletin_date: '2026-10-27',
  reading_utc: '06:00',
  v_current: 41.5,
  h: 195.123,
  in_table: true,
  v_npp: 65.7,
  url: 'https://www.gov.pl/attachment/x',
  fetched_at: '2026-10-28T08:00:00Z',
  stale: false,
  source: 'govpl' as const,
};

function wrap() {
  const client = createQueryClient({ retry: false });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.mocked(api.bulletinLatest).mockReset().mockResolvedValue(bulletin);
});

describe('useBulletinVm', () => {
  it('nie pobiera nic przy starcie', () => {
    const { result } = renderHook(() => useBulletinVm(vi.fn()), { wrapper: wrap() });
    expect(result.current.status).toBe('idle');
    expect(api.bulletinLatest).not.toHaveBeenCalled();
  });

  it('po kliknięciu: ładowanie, potem wynik i ustawienie pojemności', async () => {
    const onApply = vi.fn();
    let release!: () => void;
    vi.mocked(api.bulletinLatest).mockReturnValue(new Promise((res) => (release = () => res(bulletin))));
    const { result } = renderHook(() => useBulletinVm(onApply), { wrapper: wrap() });
    act(() => result.current.fetch());
    await waitFor(() => expect(result.current.status).toBe('loading'));
    expect(onApply).not.toHaveBeenCalled();
    act(() => release());
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(onApply).toHaveBeenCalledWith(41.5);
    expect(result.current.summary).toBe(
      `Komunikat RZGW z 27.10.2026, odczyt 06:00 UTC — 41,5${NB}mln m³ → 195,12${NB}m n.p.m.`,
    );
    expect(result.current.url).toBe(bulletin.url);
    expect(result.current.note).toBeUndefined();
    expect(result.current.error).toBeUndefined();
  });

  it('bez godziny odczytu pomija „odczyt”', async () => {
    vi.mocked(api.bulletinLatest).mockResolvedValue({ ...bulletin, reading_utc: null });
    const { result } = renderHook(() => useBulletinVm(vi.fn()), { wrapper: wrap() });
    act(() => result.current.fetch());
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.summary).not.toContain('odczyt');
  });

  it('stale: dopisuje, że to ostatni dostępny komunikat', async () => {
    vi.mocked(api.bulletinLatest).mockResolvedValue({ ...bulletin, stale: true, source: 'pipeline' });
    const { result } = renderHook(() => useBulletinVm(vi.fn()), { wrapper: wrap() });
    act(() => result.current.fetch());
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.note).toBe('(ostatni dostępny komunikat, nie udało się pobrać nowszego)');
  });

  it('in_table=false: komunikat o pojemności poza tabelą, bez poziomu', async () => {
    vi.mocked(api.bulletinLatest).mockResolvedValue({ ...bulletin, v_current: 150, h: null, in_table: false });
    const onApply = vi.fn();
    const { result } = renderHook(() => useBulletinVm(onApply), { wrapper: wrap() });
    act(() => result.current.fetch());
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.summary).toBe(
      `Komunikat RZGW z 27.10.2026, odczyt 06:00 UTC — 150,0${NB}mln m³, pojemność poza tabelą pojemności (brak poziomu)`,
    );
    expect(onApply).toHaveBeenCalledWith(150);
  });

  it('błąd 404: pokazuje komunikat z API i nie ustawia pojemności', async () => {
    vi.mocked(api.bulletinLatest).mockRejectedValue(new ApiError(404, 'Brak komunikatu'));
    const onApply = vi.fn();
    const { result } = renderHook(() => useBulletinVm(onApply), { wrapper: wrap() });
    act(() => result.current.fetch());
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toBe('Brak komunikatu');
    expect(result.current.summary).toBeUndefined();
    expect(onApply).not.toHaveBeenCalled();
  });

  it('błąd sieci: komunikat ogólny po polsku; ponowny klik pobiera na nowo', async () => {
    vi.mocked(api.bulletinLatest).mockRejectedValueOnce(new TypeError('failed'));
    const { result } = renderHook(() => useBulletinVm(vi.fn()), { wrapper: wrap() });
    act(() => result.current.fetch());
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toMatch(/Nie udało się pobrać komunikatu/);
    act(() => result.current.fetch());
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(api.bulletinLatest).toHaveBeenCalledTimes(2);
  });
});
