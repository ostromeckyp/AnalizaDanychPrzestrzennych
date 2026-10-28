import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { LayersControl } from './LayersControl';

const visible = { zones: true, bottom: false, uncertainty: false, shorelines: false, marinas: true };

describe('LayersControl', () => {
  it('list variant: checkboxes with labels', async () => {
    const onToggle = vi.fn();
    render(<LayersControl visible={visible} basemap="map" variant="list" onToggle={onToggle} onBasemap={vi.fn()} />);
    expect(screen.getByLabelText('Strefy dla jachtu')).toBeChecked();
    expect(screen.getByLabelText('Model dna (mapa wysokości)')).not.toBeChecked();
    await userEvent.click(screen.getByLabelText('Niepewność modelu'));
    expect(onToggle).toHaveBeenCalledWith('uncertainty');
    expect(screen.getByLabelText('Przystanie i slipy (OSM)')).toBeChecked();
    expect(screen.getByLabelText('Historyczne linie brzegowe')).not.toBeChecked();
  });

  it('chips variant: aria-pressed buttons', async () => {
    const onToggle = vi.fn();
    render(<LayersControl visible={visible} basemap="map" variant="chips" onToggle={onToggle} onBasemap={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Strefy dla jachtu' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Model dna (mapa wysokości)' })).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(screen.getByRole('button', { name: 'Model dna (mapa wysokości)' }));
    expect(onToggle).toHaveBeenCalledWith('bottom');
  });

  it('basemap switch', async () => {
    const onBasemap = vi.fn();
    render(<LayersControl visible={visible} basemap="map" variant="list" onToggle={vi.fn()} onBasemap={onBasemap} />);
    expect(screen.getByRole('button', { name: 'Mapa' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Ortofotomapa' }));
    expect(onBasemap).toHaveBeenCalledWith('ortho');
  });
});
