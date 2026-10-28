import './chrome.css';

export function Footer() {
  return (
    <footer className="footer">
      <span className="footer__disclaimer">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M8 7v4.2M8 4.6v.4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
        <span>
          <strong>Projekt naukowy. Nie służy do nawigacji.</strong> Dno modelowane z obrazów satelitarnych z niepewnością.
        </span>
      </span>
      <span className="footer__attr">© OpenStreetMap contributors · Copernicus Sentinel-2 · GUGiK</span>
    </footer>
  );
}
