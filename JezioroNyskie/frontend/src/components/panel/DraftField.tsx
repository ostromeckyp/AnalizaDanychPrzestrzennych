import { useId, useRef } from 'react';
import { fmtM, fmtNum, round05 } from '../../format';
import type { Preset, Range } from './types';
import { useDecimalField } from './useDecimalField';
import './panel.css';

export type DraftFieldProps = {
  value: number;
  presets: Preset[];
  presetsProvisional?: boolean;
  limits: { draft: Range };
  onChange: (draft: number) => void;
};

const STEP = 0.05;

export function DraftField({ value, presets, presetsProvisional, limits, onChange }: DraftFieldProps) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [lo, hi] = limits.draft;
  const field = useDecimalField({
    value,
    digits: 2,
    isValid: (n) => n >= lo && n <= hi,
    onCommit: onChange,
  });

  const step = (dir: 1 | -1) => {
    const next = Math.min(hi, Math.max(lo, round05(value + dir * STEP)));
    field.reset(next);
    onChange(next);
  };
  const pick = (d: number) => {
    field.reset(d);
    onChange(d);
  };
  const matches = presets.some((p) => round05(p.draft) === round05(value));
  const range = `${fmtNum(lo, 2)}–${fmtNum(hi, 2)}`;

  return (
    <section className="field">
      <label htmlFor={`${id}-input`} className="field__label">
        Zanurzenie jachtu
      </label>
      <div className="stepper">
        <button type="button" className="btn-square" aria-label="Zmniejsz zanurzenie o 0,05 m" onClick={() => step(-1)}>
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path d="M3 9h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
        <div className="stepper__box">
          <input
            ref={inputRef}
            id={`${id}-input`}
            type="text"
            inputMode="decimal"
            className="stepper__input"
            value={field.text}
            aria-invalid={field.invalid ? 'true' : undefined}
            aria-describedby={`${id}-hint`}
            onChange={(e) => field.change(e.target.value)}
            onBlur={field.commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') field.commit();
            }}
          />
          <span className="unit">m</span>
        </div>
        <button type="button" className="btn-square" aria-label="Zwiększ zanurzenie o 0,05 m" onClick={() => step(1)}>
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path d="M3 9h12M9 3v12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      <div role="group" aria-label="Typowe jachty" className="chips">
        {presets.map((p) => (
          <button
            key={p.label}
            type="button"
            className="chip"
            aria-pressed={round05(p.draft) === round05(value)}
            onClick={() => pick(p.draft)}
          >
            <span>{p.label}</span>
            <span className="chip__val">{fmtM(p.draft)}</span>
          </button>
        ))}
        <button type="button" className="chip" aria-pressed={!matches} onClick={() => inputRef.current?.focus()}>
          <span>Własny</span>
          {!matches && <span className="chip__val">{fmtM(value)}</span>}
        </button>
      </div>
      <span id={`${id}-hint`} className={field.invalid ? 'hint hint--error' : 'hint'}>
        {field.invalid ? `Podaj wartość od ${fmtNum(lo, 2)} do ${fmtNum(hi, 2)} m` : `Zakres ${range} m · krok 0,05 m`}
      </span>
      {presetsProvisional && <span className="hint">wartości robocze</span>}
    </section>
  );
}
