import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Legend } from './Legend';

describe('Legend', () => {
  it('safe row shows draft + margin sum', () => {
    render(<Legend draft={1.2} margin={0.3} />);
    expect(screen.getByText(/zanurzenie \+ zapas \(1,50 m\)/)).toBeInTheDocument();
  });

  it('sum has no float noise', () => {
    render(<Legend draft={1.1} margin={0.4} />);
    expect(screen.getByText(/zapas \(1,50 m\)/)).toBeInTheDocument();
  });

  it('shows title, three rows and summary', () => {
    render(<Legend draft={1.2} margin={0.3} summary="Jacht 1,20 m · poziom 195,20 m n.p.m. · bezpieczne 62% akwenu" />);
    expect(screen.getByRole('heading', { name: 'Strefy dla jachtu' })).toBeInTheDocument();
    expect(screen.getByText('Bezpieczna')).toBeInTheDocument();
    expect(screen.getByText('Ryzykowna')).toBeInTheDocument();
    expect(screen.getByText('Zbyt płytka / ląd')).toBeInTheDocument();
    expect(screen.getByText(/mieści się w zapasie lub niepewności modelu/)).toBeInTheDocument();
    expect(screen.getByText(/bezpieczne 62% akwenu/)).toBeInTheDocument();
  });
});

describe('Legend compact (mobile)', () => {
  it('uses short mobile descriptions with numbers from props and no dangling separator', () => {
    const { container } = render(<Legend compact draft={1.2} margin={0.3} />);
    expect(screen.getByText(/^≥ 1,50\sm$/)).toBeInTheDocument();
    expect(screen.getByText('w zapasie / niepewności')).toBeInTheDocument();
    expect(screen.queryByText(/mieści się/)).not.toBeInTheDocument();
    // separator „: ” tylko tam, gdzie jest opis
    expect(container.querySelectorAll('.sr-only')).toHaveLength(2);
    const danger = screen.getByText('Zbyt płytka / ląd').closest('.legend__text')!;
    expect(danger.textContent).toBe('Zbyt płytka / ląd');
  });
});
