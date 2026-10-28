import { fmtNum } from '../../format';
import './legend.css';

export type LegendProps = {
  draft: number;
  margin: number;
  /** Gotowe podsumowanie z VM (zawsze dla pokazywanych stref). */
  summary?: string;
  compact?: boolean;
};

export function Legend({ draft, margin, summary, compact }: LegendProps) {
  // Zaokrąglenie usuwa szum typu 1,4999999.
  const need = Math.round((draft + margin) * 100) / 100;
  // Tryb mobilny: krótkie opisy z Mobile.dc.html; strefa „Zbyt płytka” bez opisu, więc bez separatora dla czytników.
  const desc = compact
    ? { safe: `≥ ${fmtNum(need, 2)}\u00a0m`, risk: 'w zapasie / niepewności', danger: undefined }
    : {
        safe: `głębokość ≥ zanurzenie + zapas (${fmtNum(need, 2)} m)`,
        risk: 'mieści się w zapasie lub niepewności modelu',
        danger: 'głębokość mniejsza niż zanurzenie',
      };
  const rows = [
    ['safe', 'Bezpieczna'],
    ['risk', 'Ryzykowna'],
    ['danger', 'Zbyt płytka / ląd'],
  ] as const;
  return (
    <section aria-label="Legenda" className={compact ? 'legend legend--compact' : 'legend'}>
      <h2 className="legend__title">Strefy dla jachtu</h2>
      {rows.map(([key, name]) => (
        <div className="legend__row" key={key}>
          <span className={`swatch swatch--${key}`} aria-hidden="true" />
          <div className="legend__text">
            <span className="legend__name">{name}</span>
            {desc[key] && (
              <>
                <span className="sr-only">: </span>
                <span className="legend__desc">{desc[key]}</span>
              </>
            )}
          </div>
        </div>
      ))}
      {summary && <p className="legend__summary">{summary}</p>}
    </section>
  );
}
