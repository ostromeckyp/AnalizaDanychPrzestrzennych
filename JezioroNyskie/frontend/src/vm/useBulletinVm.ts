import { useQuery } from '@tanstack/react-query';
import { useRef } from 'react';
import { ApiError, api } from '../api/client';
import { fmtCapacity, fmtDate, fmtLevel } from '../format';
import { queryKeys } from './queryClient';

const GENERIC_ERROR = 'Nie udało się pobrać komunikatu Wód Polskich. Spróbuj ponownie za chwilę.';
const REFRESHING_NOTE = '(trwa pobieranie nowszego komunikatu — kliknij ponownie za chwilę)';
const STALE_NOTE = '(ostatni dostępny komunikat, nie udało się pobrać nowszego)';

export interface BulletinVm {
  status: 'idle' | 'loading' | 'ready' | 'error';
  /** Ręczne pobranie (klik); nic nie jest pobierane automatycznie. */
  fetch(): void;
  /** „Komunikat RZGW z {data}, odczyt {godzina} UTC — {v} → {h}”. */
  summary?: string;
  /** Adres PDF komunikatu (źródło). */
  url?: string;
  /** Adnotacja, gdy to nie jest świeżo pobrany komunikat. */
  note?: string;
  error?: string;
}

/**
 * Przycisk „Pobierz stan z Wód Polskich”: zapytanie wyłączone (enabled: false), uruchamiane ręcznie przez refetch.
 * Po sukcesie wywołuje `onApply(v_current)`, czyli ustawia tryb pojemności jak ręczne wpisanie wartości.
 */
export function useBulletinVm(onApply: (capacity: number) => void): BulletinVm {
  const apply = useRef(onApply);
  apply.current = onApply;
  const q = useQuery({
    queryKey: queryKeys.bulletinLatest(),
    queryFn: ({ signal }) => api.bulletinLatest(signal),
    enabled: false,
    retry: false,
    gcTime: 0,
  });

  const fetch = () => {
    if (q.isFetching) return;
    void q.refetch().then((r) => {
      if (r.isSuccess && r.data) apply.current(r.data.v_current);
    });
  };

  if (q.isFetching) return { status: 'loading', fetch };
  if (q.isError) {
    const detail = q.error instanceof ApiError && typeof q.error.detail === 'string' ? q.error.detail : undefined;
    return { status: 'error', fetch, error: detail ?? GENERIC_ERROR };
  }
  const d = q.data;
  if (!d) return { status: 'idle', fetch };

  const head = `Komunikat RZGW z ${fmtDate(d.bulletin_date)}${d.reading_utc ? `, odczyt ${d.reading_utc} UTC` : ''}`;
  const summary =
    d.h === null || d.h === undefined
      ? `${head} — ${fmtCapacity(d.v_current)}, poza tabelą pojemności — brak poziomu`
      : `${head} — ${fmtCapacity(d.v_current)} → ${fmtLevel(d.h)}`;
  return { status: 'ready', fetch, summary, url: d.url ?? undefined, note: d.refreshing ? REFRESHING_NOTE : d.stale ? STALE_NOTE : undefined };
}
