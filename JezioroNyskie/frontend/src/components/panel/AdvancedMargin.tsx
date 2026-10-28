import { useId, useState } from 'react';
import { fmtM, round05 } from '../../format';
import type { Range } from './types';
import './panel.css';

export type AdvancedMarginProps = {
  value: number;
  limits: { margin: Range };
  /** Wartość domyślna z meta (do opisu); bez niej zdanie o domyślnej jest pomijane. */
  defaultValue?: number;
  onChange: (margin: number) => void;
};

export function AdvancedMargin({ value, limits, defaultValue, onChange }: AdvancedMarginProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [lo, hi] = limits.margin;
  const step = (dir: 1 | -1) => onChange(Math.min(hi, Math.max(lo, round05(value + dir * 0.05))));

  return (
    <section className="field field--adv">
      <button
        type="button"
        className="adv-toggle"
        aria-expanded={open}
        aria-controls={`${id}-body`}
        onClick={() => setOpen((o) => !o)}
      >
        Ustawienia zaawansowane
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          aria-hidden="true"
          style={{ transform: open ? 'rotate(180deg)' : undefined }}
        >
          <path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div id={`${id}-body`} className="field">
          <div className="field__row">
            <span id={`${id}-label`}>Zapas bezpieczeństwa</span>
            <div className="margin-stepper" role="group" aria-labelledby={`${id}-label`}>
              <button type="button" className="btn-square btn-square--sm" aria-label="Zmniejsz zapas" onClick={() => step(-1)}>
                −
              </button>
              <span className="margin-stepper__val">{fmtM(value)}</span>
              <button type="button" className="btn-square btn-square--sm" aria-label="Zwiększ zapas" onClick={() => step(1)}>
                +
              </button>
            </div>
          </div>
          <span className="hint">
            Doliczany do zanurzenia przy wyznaczaniu strefy bezpiecznej.
            {defaultValue !== undefined ? ` Domyślnie ${fmtM(defaultValue)}.` : ''}
          </span>
        </div>
      )}
    </section>
  );
}
