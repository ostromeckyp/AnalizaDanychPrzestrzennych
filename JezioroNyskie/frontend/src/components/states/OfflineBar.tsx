import { fmtTime } from '../../format';
import './states.css';

// Stan E: ciemny pasek nad stopką.
export function OfflineBar({ lastOkAt, onRetry }: { lastOkAt?: Date; onRetry: () => void }) {
  return (
    <div role="status" className="offline">
      <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" className="offline__icon">
        <path d="M2 8.5a15 15 0 0 1 20 0M5.5 12a10 10 0 0 1 13 0M9 15.5a5 5 0 0 1 6 0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <circle cx="12" cy="19" r="1.3" fill="currentColor" />
        <path d="M3 3l18 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      <span className="offline__text">
        Brak połączenia.{lastOkAt ? ` Strefy z ${fmtTime(lastOkAt)} mogą być nieaktualne.` : ''}
      </span>
      <button type="button" className="offline__btn" onClick={onRetry}>
        Ponów
      </button>
    </div>
  );
}
