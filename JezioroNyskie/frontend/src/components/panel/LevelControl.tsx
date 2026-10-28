import { useId } from 'react';
import { fmtCapacity, fmtLevel, fmtNum, levelValueText } from '../../format';
import type { LevelMode, SliderProps } from './types';
import { useDecimalField } from './useDecimalField';
import './panel.css';

export type LevelControlProps = {
  /** „mobile”: krótkie teksty z Mobile.dc.html (przycisk pojemności zamiast przełącznika, krótkie ostrzeżenie). */
  variant?: 'desktop' | 'mobile';
  mode: LevelMode;
  h: number;
  slider: SliderProps;
  /** Pojemność i gotowy tekst „… powyżej NPP” dla bieżącej rzędnej (useCapacityVm). */
  level: { capacityAtLevel?: number; aboveNpp?: string };
  /** Tryb „Pojemność”: wpisana wartość i jej przeliczenie na rzędną. */
  capacity: { value: number; hFromCapacity?: number; inTable?: boolean };
  currentLevel?: { label: string; note?: string };
  /** Kody ostrzeżeń z API; nieznane są ignorowane. */
  warnings: string[];
  onModeChange: (m: LevelMode) => void;
  onLevelChange: (h: number) => void;
  onCapacityChange: (v: number) => void;
};

export function LevelControl(p: LevelControlProps) {
  const id = useId();
  const { slider: s } = p;
  const mobile = p.variant === 'mobile';
  const pct = (x: number) => `${((x - s.min) / (s.max - s.min)) * 100}%`;
  const cap = useDecimalField({
    value: p.capacity.value,
    digits: 1,
    isValid: (n) => n > 0,
    onCommit: p.onCapacityChange,
  });
  const capInvalid = cap.invalid;

  const alerts: React.ReactNode[] = [];
  const obs = `${fmtNum(s.obsMin, 2)}–${fmtNum(s.obsMax, 2)}`;
  for (const code of p.warnings) {
    if (code === 'h_out_of_range') {
      alerts.push(
        <Alert key={code}>
          {mobile ? (
            <>
              <strong>Poza zakresem obserwacji.</strong> Model dna jest ekstrapolowany, wynik mniej pewny.
            </>
          ) : (
            <>
              <strong>Poziom poza zakresem obserwacji</strong> ({obs} m n.p.m.). Model dna jest tu ekstrapolowany, wynik
              jest mniej pewny.
            </>
          )}
        </Alert>,
      );
    } else if (code === 'below_observed_bottom') {
      alerts.push(
        <Alert key={code}>
          Dna poniżej {fmtNum(s.obsMin, 2)} m n.p.m. nie obserwowano — przy tym poziomie i zanurzeniu nie ma strefy
          bezpiecznej.
        </Alert>,
      );
    }
  }

  const extra = [
    p.level.capacityAtLevel !== undefined ? `≈ ${fmtCapacity(p.level.capacityAtLevel)}` : null,
    p.level.aboveNpp ?? null,
  ].filter(Boolean);

  return (
    <section className="field">
      <div className="field__row">
        <span id={`${id}-label`} className="field__label">
          Poziom wody
        </span>
        {mobile ? (
          <button
            type="button"
            className="link-btn"
            onClick={() => p.onModeChange(p.mode === 'level' ? 'capacity' : 'level')}
          >
            {p.mode === 'level' ? 'Podaj pojemność (mln m³)' : 'Wróć do rzędnej'}
          </button>
        ) : (
          <div role="group" aria-label="Sposób podania poziomu" className="segmented">
            <button type="button" aria-pressed={p.mode === 'level'} onClick={() => p.onModeChange('level')}>
              Rzędna
            </button>
            <button type="button" aria-pressed={p.mode === 'capacity'} onClick={() => p.onModeChange('capacity')}>
              Pojemność
            </button>
          </div>
        )}
      </div>

      {p.mode === 'level' ? (
        <div className="bigvalue">
          <span className="bigvalue__num">{fmtLevel(p.h)}</span>
          {extra.length > 0 && <span className="hint">{extra.join(' · ')}</span>}
        </div>
      ) : (
        <div className="field">
          <label htmlFor={`${id}-cap`} className="hint">
            {mobile ? 'Podaj pojemność (mln m³)' : 'Pojemność z komunikatu RZGW [mln m³]'}
          </label>
          <div className="stepper__box">
            <input
              id={`${id}-cap`}
              type="text"
              inputMode="decimal"
              className="stepper__input stepper__input--md"
              value={cap.text}
              aria-invalid={capInvalid ? 'true' : undefined}
              aria-describedby={`${id}-cap-hint`}
              onChange={(e) => cap.change(e.target.value)}
              onBlur={cap.commit}
              onKeyDown={(e) => {
                if (e.key === 'Enter') cap.commit();
              }}
            />
            <span className="unit">mln m³</span>
          </div>
          <span id={`${id}-cap-hint`} className={capInvalid ? 'hint hint--error' : 'hint'}>
            {capInvalid ? (
              'Podaj dodatnią liczbę, np. 45,6'
            ) : p.capacity.inTable === false ? (
              'poza tabelą pojemności'
            ) : p.capacity.hFromCapacity !== undefined ? (
              <>
                → poziom <strong>{fmtLevel(p.capacity.hFromCapacity)}</strong>
              </>
            ) : null}
          </span>
        </div>
      )}

      <div className="slider">
        <div className="slider__marks slider__marks--top" aria-hidden="true">
          <span className="mark-label" style={{ left: pct(s.maxPp) }}>
            Max PP
          </span>
        </div>
        <div className="slider__track" aria-hidden="true">
          <div
            className="slider__obs"
            style={{ left: pct(s.obsMin), width: `${((s.obsMax - s.obsMin) / (s.max - s.min)) * 100}%` }}
          />
          {[s.obsMin, s.npp, s.maxPp].map((x) => (
            <span key={x} className="slider__tick" style={{ left: pct(x) }} />
          ))}
        </div>
        <input
          type="range"
          min={s.min}
          max={s.max}
          step={s.step}
          value={p.h}
          aria-labelledby={`${id}-label`}
          aria-valuetext={levelValueText(p.h)}
          onChange={(e) => p.onLevelChange(Number(e.target.value))}
        />
        <div className="slider__marks slider__marks--bottom" aria-hidden="true">
          <span className="mark-label" style={{ left: pct(s.obsMin) }}>
            min. obs.
            <br />
            {fmtNum(s.obsMin, 2)}
          </span>
          <span className="mark-label" style={{ left: pct(s.npp) }}>
            NPP
            <br />
            {fmtNum(s.npp, 2)}
          </span>
        </div>
      </div>

      {p.currentLevel && (
        <span className="hint">
          {p.currentLevel.label}
          {p.currentLevel.note ? ` · ${p.currentLevel.note}` : ''}
        </span>
      )}
      {alerts}
    </section>
  );
}

function Alert({ children }: { children: React.ReactNode }) {
  return (
    <div role="alert" className="alert">
      <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true" className="alert__icon">
        <path d="M10 2.5 18.5 17h-17Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        <path d="M10 8v4M10 14.5v.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      <span>{children}</span>
    </div>
  );
}
