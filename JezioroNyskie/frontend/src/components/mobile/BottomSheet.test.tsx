import { readFileSync } from 'node:fs';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { meta } from '../../test/fixtures';
import type { ParameterPanelProps } from '../panel/ParameterPanel';
import { BottomSheet } from './BottomSheet';
import { MobileHeader } from './MobileHeader';

const NB = '\u00a0';
// Vitest ma css: false (importy CSS są puste, także ?raw), więc czytamy źródło z dysku.
const mobileCss = readFileSync('src/components/mobile/mobile.css', 'utf8');

function panelProps(over: Partial<ParameterPanelProps['draft']> = {}) {
  const onDraft = vi.fn();
  const panel: ParameterPanelProps = {
    draft: {
      value: 1.2,
      presets: [{ label: 'Omega', draft: 0.9 }],
      limits: { draft: meta.limits.draft },
      onChange: onDraft,
      ...over,
    },
    level: {
      mode: 'level',
      h: 195.2,
      slider: { ...meta.slider, obsMin: meta.h_min_obs, obsMax: meta.h_max_obs, npp: meta.npp, maxPp: meta.max_pp },
      level: { capacityAtLevel: 45.6, aboveNpp: `0,70${NB}m poniżej NPP` },
      capacity: { value: 45.6, hFromCapacity: 195.2, inTable: true },
      warnings: [],
      onModeChange: vi.fn(),
      onLevelChange: vi.fn(),
      onCapacityChange: vi.fn(),
    },
    layers: {
      visible: { zones: true, bottom: false, uncertainty: false, shorelines: false, marinas: true },
      basemap: 'map',
      variant: 'list',
      onToggle: vi.fn(),
      onBasemap: vi.fn(),
    },
    margin: { value: 0.3, limits: { margin: meta.limits.margin }, defaultValue: 0.3, onChange: vi.fn() },
  };
  return { panel, onDraft };
}

function setup(withPanel = true) {
  const { panel, onDraft } = panelProps();
  render(
    <BottomSheet
      panel={withPanel ? panel : undefined}
      legend={withPanel ? { draft: 1.2, margin: 0.3, summary: 'Jacht 1,20 m · bezpieczne 40% akwenu' } : undefined}
    />,
  );
  return { panel, onDraft };
}

const handle = () => screen.getByRole('button', { name: /^(Zwiń panel|Rozwiń panel parametrów)$/ });

describe('BottomSheet', () => {
  it('collapsed: draft stepper, level shortcut, mini legend and summary only', () => {
    setup();
    expect(handle()).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: 'Zmniejsz zanurzenie' })).toBeInTheDocument();
    expect(screen.getByText(/^1,20\s+m$/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Poziom wody.*195,20/ })).toBeInTheDocument();
    const legend = screen.getByRole('region', { name: 'Legenda' });
    expect(within(legend).getByText('Bezpieczna')).toBeInTheDocument();
    expect(screen.getByText('Jacht 1,20 m · bezpieczne 40% akwenu')).toBeInTheDocument();
    // pełny panel jest ukryty
    expect(screen.queryByRole('slider')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Pokaż mapę' })).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Warstwy' })).not.toBeInTheDocument();
  });

  it('collapsed stepper changes the draft by 0,05 within limits', async () => {
    const { onDraft } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'Zwiększ zanurzenie' }));
    expect(onDraft).toHaveBeenLastCalledWith(1.25);
    await userEvent.click(screen.getByRole('button', { name: 'Zmniejsz zanurzenie' }));
    expect(onDraft).toHaveBeenLastCalledWith(1.15);
  });

  it('tapping the level shortcut expands the sheet; „Pokaż mapę” collapses it', async () => {
    setup();
    await userEvent.click(screen.getByRole('button', { name: /Poziom wody.*195,20/ }));
    expect(handle()).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('slider')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Warstwy' })).toBeInTheDocument(); // chipy
    expect(screen.getByRole('button', { name: 'Ustawienia zaawansowane' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Podaj pojemność (mln m³)' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Legenda' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Pokaż mapę' }));
    expect(handle()).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('slider')).not.toBeInTheDocument();
  });

  it('handle toggles and aria-controls points at the sheet body', async () => {
    setup();
    const id = handle().getAttribute('aria-controls')!;
    expect(document.getElementById(id)).toBeInTheDocument();
    await userEvent.click(handle());
    expect(handle()).toHaveAttribute('aria-expanded', 'true');
    expect(handle()).toHaveAccessibleName('Zwiń panel');
    await userEvent.click(handle());
    expect(handle()).toHaveAttribute('aria-expanded', 'false');
  });

  it('disclaimer is visible in both states and without panel data', async () => {
    setup();
    const text = /Nie służy do nawigacji/;
    expect(screen.getByText(text)).toBeInTheDocument();
    await userEvent.click(handle());
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it('without panel data it still shows the disclaimer', () => {
    setup(false);
    expect(screen.getByText(/Nie służy do nawigacji/)).toBeInTheDocument();
  });
});

describe('MobileHeader', () => {
  it('has name and icon links with aria-labels', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <MobileHeader />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'Mielizna' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Historia linii brzegowych' })).toHaveAttribute('href', '/historia');
    expect(screen.getByRole('link', { name: 'O metodzie' })).toHaveAttribute('href', '/metoda');
  });
});

// jsdom nie ma układu, więc sprawdzamy regułę w źródle CSS i to, że elementy dostają tę klasę.
function rule(css: string, cls: string): string {
  const re = new RegExp(`(?:^|[\\s,}])\\.${cls}(?![\\w-])[^{]*\\{([^}]*)\\}`, 'gm');
  return [...css.matchAll(re)].map((m) => m[1]).join(';');
}

describe('touch targets >= 44 px', () => {
  it.each(['mheader__link', 'sheet__handle', 'sheet__step', 'sheet__level', 'sheet__close'])(
    '.%s has min-width and min-height 44px in mobile.css',
    (cls) => {
      const body = rule(mobileCss, cls);
      expect(body).toMatch(/min-height:\s*44px/);
      expect(body).toMatch(/min-width:\s*44px/);
    },
  );

  it('the buttons really use those classes', async () => {
    setup();
    expect(handle()).toHaveClass('sheet__handle');
    expect(screen.getByRole('button', { name: 'Zmniejsz zanurzenie' })).toHaveClass('sheet__step');
    expect(screen.getByRole('button', { name: 'Zwiększ zanurzenie' })).toHaveClass('sheet__step');
    const level = screen.getByRole('button', { name: /Poziom wody/ });
    expect(level).toHaveClass('sheet__level');
    await userEvent.click(level);
    expect(screen.getByRole('button', { name: 'Pokaż mapę' })).toHaveClass('sheet__close');
  });

  it('header links use .mheader__link', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <MobileHeader />
      </MemoryRouter>,
    );
    for (const l of screen.getAllByRole('link')) expect(l).toHaveClass('mheader__link');
  });

  it('sheet heights: 290px collapsed, 760px capped expanded', () => {
    expect(rule(mobileCss, 'sheet--collapsed')).toMatch(/height:\s*290px/);
    expect(rule(mobileCss, 'sheet--expanded')).toMatch(/height:\s*min\(760px,/);
  });
});
