import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AppNav } from './AppNav';
import { Footer } from './Footer';

describe('chrome', () => {
  it('Footer: disclaimer left, attributions right', () => {
    render(<Footer />);
    const f = screen.getByRole('contentinfo');
    expect(f).toHaveTextContent('Projekt naukowy. Nie służy do nawigacji. Dno modelowane z obrazów satelitarnych z niepewnością.');
    expect(f).toHaveTextContent('© OpenStreetMap contributors · Copernicus Sentinel-2 · GUGiK');
  });

  it('AppNav: brand and three routes with aria-current on the active one', () => {
    render(
      <MemoryRouter initialEntries={['/historia']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppNav />
      </MemoryRouter>,
    );
    expect(screen.getByText('Mielizna')).toBeInTheDocument();
    expect(screen.getByText('Jezioro Nyskie · gdzie przepłynę?')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Mapa' })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: 'O metodzie' })).toHaveAttribute('href', '/metoda');
    expect(screen.getByRole('link', { name: 'Historia linii brzegowych' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Mapa' })).not.toHaveAttribute('aria-current');
  });
});
