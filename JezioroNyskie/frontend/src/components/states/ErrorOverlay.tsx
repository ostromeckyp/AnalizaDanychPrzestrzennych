import { fmtLevel, fmtM } from '../../format';
import './states.css';

export type ErrorOverlayProps = {
  lastOk?: { draft: number; h: number };
  retrying: boolean;
  onRetry: () => void;
};

// Stan D: mapa przygaszona (robi to strona), komunikat z ostatnimi poprawnymi parametrami.
export function ErrorOverlay({ lastOk, retrying, onRetry }: ErrorOverlayProps) {
  return (
    <div className="overlay">
      <div role="alert" className="overlay__card">
        <strong>Nie udało się przeliczyć stref</strong>
        <span className="overlay__text">
          Serwer nie odpowiedział.
          {lastOk && ` Widzisz wynik dla poprzednich parametrów (${fmtM(lastOk.draft)} · ${fmtLevel(lastOk.h)}).`}
        </span>
        <button type="button" className="btn-primary" disabled={retrying} aria-busy={retrying} onClick={onRetry}>
          {retrying ? 'Ponawiam…' : 'Spróbuj ponownie'}
        </button>
      </div>
    </div>
  );
}
