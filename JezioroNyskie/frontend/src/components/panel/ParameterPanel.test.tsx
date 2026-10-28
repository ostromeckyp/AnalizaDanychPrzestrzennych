import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { meta } from '../../test/fixtures';
import { ParameterPanel } from './ParameterPanel';

describe('ParameterPanel', () => {
  it('composes all sections', () => {
    const noop = vi.fn();
    render(
      <ParameterPanel
        draft={{ value: 1.2, presets: meta.draft_presets, limits: meta.limits, onChange: noop }}
        level={{
          mode: 'level',
          h: 195.2,
          slider: { ...meta.slider, obsMin: meta.h_min_obs, obsMax: meta.h_max_obs, npp: meta.npp, maxPp: meta.max_pp },
          level: {},
          capacity: { value: 40 },
          warnings: [],
          onModeChange: noop,
          onLevelChange: noop,
          onCapacityChange: noop,
        }}
        layers={{
          visible: { zones: true, bottom: false, uncertainty: false, shorelines: false, marinas: false, gravel: false },
          basemap: 'map',
          variant: 'list',
          onToggle: noop,
          onBasemap: noop,
        }}
        margin={{ value: 0.3, limits: meta.limits, onChange: noop }}
      />,
    );
    expect(screen.getByLabelText('Zanurzenie jachtu')).toBeInTheDocument();
    expect(screen.getByRole('slider')).toBeInTheDocument();
    expect(screen.getByLabelText('Strefy dla jachtu')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ustawienia zaawansowane' })).toBeInTheDocument();
  });
});
