import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { LevelChart } from './LevelChart';
import { SceneCard } from './SceneCard';
import { SceneList } from './SceneList';
import type { SceneRow } from './types';

const row = (date: string, h: number, extra: Partial<SceneRow> = {}): SceneRow => ({
  date,
  dateLabel: `${date.slice(8)}.${date.slice(5, 7)}.${date.slice(0, 4)}`,
  h,
  level: `${h} m n.p.m.`,
  area: '12,3 km²',
  source: 'Sentinel-2 · zachm. 1,3%',
  color: '#2a6fa3',
  dashed: false,
  mapHref: `/?h=${h}`,
  ...extra,
});
const rows = [row('2026-10-20', 194.2), row('2026-09-30', 193.9), row('2025-04-12', 193.6)];

const wrap = (ui: React.ReactElement) => (
  <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>{ui}</MemoryRouter>
);

describe('LevelChart', () => {
  it('is an img with aria-label describing range, draws NPP line and dots', () => {
    const { container } = render(<LevelChart scenes={rows} npp={195.91} selected="2026-10-20" />);
    const svg = screen.getByRole('img');
    const label = svg.getAttribute('aria-label')!;
    expect(label).toContain('12.04.2025');
    expect(label).toContain('20.10.2026');
    expect(label).toMatch(/193,60.*194,20/);
    expect(container.querySelectorAll('circle')).toHaveLength(3);
    expect(container.querySelector('svg')!.textContent).toContain('NPP 195,91');
  });
  it('renders without NPP and with a single scene', () => {
    const { container } = render(<LevelChart scenes={[rows[0]]} />);
    expect(container.querySelectorAll('circle')).toHaveLength(1);
    expect(container.textContent).not.toContain('NPP');
    expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
  });
});

describe('SceneCard', () => {
  it('shows date, level, area, source and link', () => {
    render(wrap(<SceneCard scene={rows[0]} />));
    expect(screen.getByText('20.10.2026')).toBeInTheDocument();
    expect(screen.getByText('Sentinel-2 · zachm. 1,3%')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ustaw ten poziom na mapie' })).toHaveAttribute('href', '/?h=194.2');
  });
});

describe('SceneList', () => {
  const base = {
    years: [2026, 2025],
    year: 'all' as const,
    counter: '3 sceny · nałożone: 1',
    rows,
    selected: '2026-10-20',
    overlay: ['2026-09-30'],
    onYear: vi.fn(),
    onSelect: vi.fn(),
    onToggle: vi.fn(),
    onReset: vi.fn(),
  };
  it('renders year chips, counter, rows and checkboxes', async () => {
    const onYear = vi.fn();
    const onToggle = vi.fn();
    const onSelect = vi.fn();
    render(<SceneList {...base} onYear={onYear} onToggle={onToggle} onSelect={onSelect} />);
    expect(screen.getByText('3 sceny · nałożone: 1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Wszystkie' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: '2025' }));
    expect(onYear).toHaveBeenCalledWith(2025);
    const cb = screen.getByRole('checkbox', { name: 'Nałóż linię brzegową z 30.09.2026' });
    expect(cb).toBeChecked();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Nałóż linię brzegową z 20.10.2026' }));
    expect(onToggle).toHaveBeenCalledWith('2026-10-20');
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(3);
    await userEvent.click(within(items[1]).getByRole('button'));
    expect(onSelect).toHaveBeenCalledWith('2026-09-30');
    expect(within(items[0]).getByRole('button')).toHaveAttribute('aria-pressed', 'true');
  });
  it('shows an inline error for a failed overlay row', () => {
    render(<SceneList {...base} rows={[row('2026-10-20', 194.2, { overlayStatus: 'error' })]} />);
    expect(screen.getByText('Nie udało się pobrać linii')).toBeInTheDocument();
  });
  it('empty state with reset', async () => {
    const onReset = vi.fn();
    render(<SceneList {...base} year={2019} rows={[]} counter="0 scen · nałożone: 0" onReset={onReset} />);
    expect(screen.getByText('Brak scen dla tego filtra')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Pokaż wszystkie sceny' }));
    expect(onReset).toHaveBeenCalled();
  });
  it('no scenes at all: no reset button or year hint', () => {
    render(<SceneList {...base} year="all" years={[]} rows={[]} counter="0 scen · nałożone: 0" />);
    expect(screen.getByText('Brak scen dla tego filtra')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Pokaż wszystkie sceny' })).toBeNull();
    expect(screen.queryByText(/Wybierz inny rok/)).toBeNull();
  });
});
