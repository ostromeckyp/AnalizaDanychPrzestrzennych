import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { meta } from '../../test/fixtures';
import { LevelControl, type LevelControlProps } from './LevelControl';

const slider = {
  ...meta.slider,
  obsMin: meta.h_min_obs,
  obsMax: meta.h_max_obs,
  npp: meta.npp,
  maxPp: meta.max_pp,
};

function setup(over: Partial<LevelControlProps> = {}) {
  const props: LevelControlProps = {
    mode: 'level',
    h: 195.2,
    slider,
    level: { capacityAtLevel: 45.6, aboveNpp: '0,70\u00a0m poniżej NPP' },
    capacity: { value: 45.6, hFromCapacity: 195.2, inTable: true },
    currentLevel: { h: 195.1, label: 'Aktualny: 195,10 m n.p.m.' } as never,
    warnings: [],
    onModeChange: vi.fn(),
    onLevelChange: vi.fn(),
    onCapacityChange: vi.fn(),
    ...over,
  };
  render(<LevelControl {...props} />);
  return props;
}

describe('LevelControl', () => {
  it('slider has aria-valuetext and markers from meta', () => {
    setup();
    const s = screen.getByRole('slider');
    expect(s).toHaveAttribute('aria-valuetext', '195,20\u00a0metra nad poziomem morza');
    expect(s).toHaveAttribute('min', String(meta.slider.min));
    expect(s).toHaveAttribute('max', String(meta.slider.max));
    expect(screen.getByText(/min\. obs\./)).toHaveTextContent('192,90');
    expect(screen.getByText(/^NPP/)).toHaveTextContent('195,91');
    expect(screen.getByText('Max PP')).toBeInTheDocument();
  });

  it('slider change reports a number', () => {
    const p = setup();
    fireEvent.change(screen.getByRole('slider'), { target: { value: '195.35' } });
    expect(p.onLevelChange).toHaveBeenCalledWith(195.35);
  });

  it('level mode shows the big value, capacity and NPP delta', () => {
    setup({ level: { capacityAtLevel: 45.6, aboveNpp: '0,20\u00a0m powyżej NPP' } });
    expect(screen.getByText(/195,20.*m n\.p\.m\./)).toBeInTheDocument();
    expect(screen.getByText(/≈ 45,6.*mln m³ · 0,20.*m powyżej NPP/)).toBeInTheDocument();
  });

  it('mode toggle uses aria-pressed and calls back', async () => {
    const p = setup();
    expect(screen.getByRole('button', { name: 'Rzędna' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Pojemność' }));
    expect(p.onModeChange).toHaveBeenCalledWith('capacity');
  });

  it('out-of-range warning is an alert with meta numbers (en dash)', () => {
    setup({ warnings: ['h_out_of_range'] });
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Poziom poza zakresem obserwacji (192,90–197,92 m n.p.m.). Model dna jest tu ekstrapolowany, wynik jest mniej pewny.',
    );
  });

  it('below_observed_bottom warning, unknown codes ignored', () => {
    setup({ warnings: ['below_observed_bottom', 'whatever'] });
    const alerts = screen.getAllByRole('alert');
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent(
      'Dna poniżej 192,90 m n.p.m. nie obserwowano — przy tym poziomie i zanurzeniu nie ma strefy bezpiecznej.',
    );
  });

  it('no alert without warnings', () => {
    setup();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the current level label', () => {
    setup();
    expect(screen.getByText('Aktualny: 195,10 m n.p.m.')).toBeInTheDocument();
  });

  it('capacity mode shows converted level', () => {
    setup({ mode: 'capacity', capacity: { value: 45.6, hFromCapacity: 195.2, inTable: true } });
    expect(screen.getByLabelText(/Pojemność z komunikatu RZGW/)).toHaveValue('45,6');
    expect(screen.getByText(/→ poziom/)).toHaveTextContent('→ poziom 195,20 m n.p.m.');
  });

  it('capacity mode shows out-of-table', () => {
    setup({ mode: 'capacity', capacity: { value: 999, inTable: false } });
    expect(screen.getByText('poza tabelą pojemności')).toBeInTheDocument();
  });

  it.each([
    ['45,7', 45.7],
    ['45.7', 45.7],
    [' 45,7 ', 45.7],
  ])('capacity accepts %j', async (s, n) => {
    const p = setup({ mode: 'capacity' });
    const f = screen.getByLabelText(/Pojemność z komunikatu RZGW/);
    await userEvent.clear(f);
    await userEvent.type(f, s);
    await userEvent.tab();
    expect(p.onCapacityChange).toHaveBeenLastCalledWith(n);
  });

  it.each(['abc', '0', '-3'])('capacity rejects %j', async (s) => {
    const p = setup({ mode: 'capacity' });
    const f = screen.getByLabelText(/Pojemność z komunikatu RZGW/);
    await userEvent.clear(f);
    await userEvent.type(f, s);
    await userEvent.tab();
    expect(p.onCapacityChange).not.toHaveBeenCalled();
    expect(f).toHaveAttribute('aria-invalid', 'true');
    expect(f).toHaveValue(s);
  });
});
