import { NavLink } from 'react-router-dom';
import './chrome.css';

const LINKS: [string, string, boolean][] = [
  ['/', 'Mapa', true],
  ['/historia', 'Historia linii brzegowych', false],
  ['/metoda', 'O metodzie', false],
];

export function AppNav() {
  return (
    <>
      <header className="brand">
        <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true">
          <rect width="34" height="34" rx="9" fill="var(--accent)" />
          <path
            d="M7 13c3-2.4 6-2.4 10 0s7 2.4 10 0M7 19c3-2.4 6-2.4 10 0s7 2.4 10 0M7 25c3-2.4 6-2.4 10 0s7 2.4 10 0"
            fill="none"
            stroke="var(--accent-text)"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </svg>
        <div className="brand__text">
          <h1>Mielizna</h1>
          <span>Jezioro Nyskie · gdzie przepłynę?</span>
        </div>
      </header>
      <nav aria-label="Widoki" className="appnav">
        {LINKS.map(([to, label, end]) => (
          <NavLink key={to} to={to} end={end} className="appnav__link">
            {label}
          </NavLink>
        ))}
      </nav>
    </>
  );
}
