import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { PointPopup } from './PointPopup';
import type { PopupModel } from './types';

const A: PopupModel = {
  variant: 'A',
  title: 'Głębokość w tym miejscu',
  value: '1,40–1,90 m',
  note: 'Pod kilem 0,20 do 0,70 m · wymagany zapas 0,30 m',
  zone: { key: 'risk', name: 'Ryzykowna', label: 'dla jachtu 1,20 m' },
  rows: [
    { term: 'Wysokość dna', desc: '193,55 m n.p.m. ± 0,25' },
    { term: 'Obserwacje satelitarne', desc: '14 scen' },
  ],
};
const D: PopupModel = {
  variant: 'D',
  title: 'W tym miejscu',
  value: 'Poza obszarem modelu',
  note: 'Model obejmuje czaszę zbiornika do rzędnej Max PP 198,89 m n.p.m. Tutaj nie ma danych o dnie.',
  noZone: 'Bez oceny strefy',
  rows: [],
};

describe('PointPopup', () => {
  it('variant A: dialog with value, zone bar, rows and a labelled close button', async () => {
    const onClose = vi.fn();
    render(<PointPopup model={A} onClose={onClose} />);
    const dlg = screen.getByRole('dialog', { name: 'Informacje o punkcie' });
    expect(within(dlg).getByText('Głębokość w tym miejscu')).toBeInTheDocument();
    expect(within(dlg).getByText('1,40–1,90 m')).toBeInTheDocument();
    expect(within(dlg).getByText('Ryzykowna')).toBeInTheDocument();
    expect(within(dlg).getByText(/dla jachtu 1,20 m/)).toBeInTheDocument();
    expect(within(dlg).getByText('Wysokość dna')).toBeInTheDocument();
    expect(within(dlg).getByText('14 scen')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Zamknij' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('variant D: no zone bar, shows "Bez oceny strefy", no definition list', () => {
    render(<PointPopup model={D} onClose={() => {}} />);
    expect(screen.getByText('Poza obszarem modelu')).toBeInTheDocument();
    expect(screen.getByText('Bez oceny strefy')).toBeInTheDocument();
    expect(screen.queryByText('Ryzykowna')).not.toBeInTheDocument();
    expect(document.querySelector('dl')).toBeNull();
  });

  it('without model shows a loading status, or an alert on error; both closable', async () => {
    const onClose = vi.fn();
    const { rerender } = render(<PointPopup state="loading" onClose={onClose} />);
    expect(screen.getByRole('status')).toHaveTextContent('Sprawdzam punkt…');
    rerender(<PointPopup state="error" onClose={onClose} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Nie udało się pobrać danych punktu.');
    await userEvent.click(screen.getByRole('button', { name: 'Zamknij' }));
    expect(onClose).toHaveBeenCalled();
  });
});
