import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ErrorOverlay } from './ErrorOverlay';
import { LoadingSkeleton } from './LoadingSkeleton';
import { OfflineBar } from './OfflineBar';
import { RecalcPill } from './RecalcPill';

const NB = '\u00a0';

describe('stany', () => {
  it('A: skeleton is a status with the loading text', () => {
    render(<LoadingSkeleton />);
    expect(screen.getByRole('status')).toHaveTextContent('Wczytuję model dna i strefy…');
  });

  it('B: pill shows the pending draft', () => {
    render(<RecalcPill draft={1.35} />);
    expect(screen.getByRole('status').textContent).toContain(`Przeliczam strefy dla 1,35${NB}m…`);
  });

  it('D: alert with last good params and retry button; busy state disables it', async () => {
    const onRetry = vi.fn();
    const { rerender } = render(<ErrorOverlay lastOk={{ draft: 1.2, h: 195.2 }} retrying={false} onRetry={onRetry} />);
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Nie udało się przeliczyć stref');
    expect(alert.textContent).toContain(`Widzisz wynik dla poprzednich parametrów (1,20${NB}m · 195,20${NB}m n.p.m.).`);
    await userEvent.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    rerender(<ErrorOverlay lastOk={{ draft: 1.2, h: 195.2 }} retrying onRetry={onRetry} />);
    const busy = screen.getByRole('button', { name: /Ponawiam/ });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute('aria-busy', 'true');
  });

  it('D: without any good result the params sentence is omitted', () => {
    render(<ErrorOverlay retrying={false} onRetry={() => {}} />);
    expect(screen.getByRole('alert')).not.toHaveTextContent('poprzednich parametrów');
  });

  it('E: offline bar shows HH:MM of last good zones and retries', async () => {
    const onRetry = vi.fn();
    render(<OfflineBar lastOkAt={new Date(2026, 9, 28, 10, 42)} onRetry={onRetry} />);
    expect(screen.getByRole('status')).toHaveTextContent('Brak połączenia. Strefy z 10:42 mogą być nieaktualne.');
    await userEvent.click(screen.getByRole('button', { name: 'Ponów' }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('E: offline bar without a last good time', () => {
    render(<OfflineBar onRetry={() => {}} />);
    expect(screen.getByRole('status')).toHaveTextContent(/^Brak połączenia\.\s*Ponów$/);
  });
});
