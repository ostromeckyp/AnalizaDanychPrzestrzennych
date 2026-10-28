import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { meta } from '../../test/fixtures';
import { AdvancedMargin } from './AdvancedMargin';

describe('AdvancedMargin', () => {
  it('is collapsed by default and expands', async () => {
    render(<AdvancedMargin value={0.3} limits={meta.limits} defaultValue={meta.defaults.margin} onChange={vi.fn()} />);
    const toggle = screen.getByRole('button', { name: 'Ustawienia zaawansowane' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Zapas bezpieczeństwa')).not.toBeInTheDocument();
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Zapas bezpieczeństwa')).toBeInTheDocument();
    expect(screen.getByText(/Domyślnie 0,30 m\./)).toBeInTheDocument();
  });

  it('steps by 0.05 within limits', async () => {
    const onChange = vi.fn();
    const { rerender } = render(<AdvancedMargin value={0.3} limits={meta.limits} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Ustawienia zaawansowane' }));
    await userEvent.click(screen.getByRole('button', { name: 'Zwiększ zapas' }));
    expect(onChange).toHaveBeenLastCalledWith(0.35);
    await userEvent.click(screen.getByRole('button', { name: 'Zmniejsz zapas' }));
    expect(onChange).toHaveBeenLastCalledWith(0.25);
    rerender(<AdvancedMargin value={1} limits={meta.limits} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Zwiększ zapas' }));
    expect(onChange).toHaveBeenLastCalledWith(1);
    rerender(<AdvancedMargin value={0} limits={meta.limits} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Zmniejsz zapas' }));
    expect(onChange).toHaveBeenLastCalledWith(0);
  });
});
