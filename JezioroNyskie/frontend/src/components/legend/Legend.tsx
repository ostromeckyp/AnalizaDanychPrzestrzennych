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
  return (
    <section aria-label="Legenda" className={compact ? 'legend legend--compact' : 'legend'}>
      <h2 className="legend__title">Strefy dla jachtu</h2>
      <div className="legend__row">
        <span className="swatch swatch--safe" aria-hidden="true" />
        <div className="legend__text">
          <span className="legend__name">Bezpieczna</span>
          <span className="sr-only">: </span>
          <span className="legend__desc">głębokość ≥ zanurzenie + zapas ({fmtNum(need, 2)} m)</span>
        </div>
      </div>
      <div className="legend__row">
        <span className="swatch swatch--risk" aria-hidden="true" />
        <div className="legend__text">
          <span className="legend__name">Ryzykowna</span>
          <span className="sr-only">: </span>
          <span className="legend__desc">mieści się w zapasie lub niepewności modelu</span>
        </div>
      </div>
      <div className="legend__row">
        <span className="swatch swatch--danger" aria-hidden="true" />
        <div className="legend__text">
          <span className="legend__name">Zbyt płytka / ląd</span>
          <span className="sr-only">: </span>
          <span className="legend__desc">głębokość mniejsza niż zanurzenie</span>
        </div>
      </div>
      {summary && <p className="legend__summary">{summary}</p>}
    </section>
  );
}
