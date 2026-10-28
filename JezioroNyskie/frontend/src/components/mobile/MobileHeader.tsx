import { Link } from 'react-router-dom';
import './mobile.css';

// Nagłówek mobilny (Mobile.dc.html): logo, nazwa, ikony Historia / O metodzie.
export function MobileHeader() {
  return (
    <header className="mheader">
      <svg width="30" height="30" viewBox="0 0 34 34" aria-hidden="true">
        <rect width="34" height="34" rx="9" fill="var(--accent)" />
        <path
          d="M7 13c3-2.4 6-2.4 10 0s7 2.4 10 0M7 19c3-2.4 6-2.4 10 0s7 2.4 10 0M7 25c3-2.4 6-2.4 10 0s7 2.4 10 0"
          fill="none"
          stroke="var(--accent-text)"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
      <div className="mheader__text">
        <h1>Mielizna</h1>
        <span>Jezioro Nyskie</span>
      </div>
      <Link to="/historia" className="mheader__link" aria-label="Historia linii brzegowych">
        <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
          <circle cx="11" cy="11" r="8" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path d="M11 6.5V11l3 2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      </Link>
      <Link to="/metoda" className="mheader__link" aria-label="O metodzie">
        <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
          <circle cx="11" cy="11" r="8" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path d="M11 10v5M11 7v.4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </Link>
    </header>
  );
}
