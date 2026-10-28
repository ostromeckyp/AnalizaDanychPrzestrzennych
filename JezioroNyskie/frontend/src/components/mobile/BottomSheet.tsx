import { useId, useState } from 'react';
import { fmtLevel, fmtM, round05 } from '../../format';
import { Legend, type LegendProps } from '../legend/Legend';
import { ParameterPanel, type ParameterPanelProps } from '../panel/ParameterPanel';
import './mobile.css';

export type BottomSheetProps = {
  /** Bez danych (ładowanie) arkusz pokazuje tylko pasek disclaimera. */
  panel?: ParameterPanelProps;
  legend?: LegendProps;
};

const STEP = 0.05;

// Arkusz: zwinięty 290 px (stepper, skrót poziomu, mini-legenda), rozwinięty do 760 px (pełny panel).
export function BottomSheet({ panel, legend }: BottomSheetProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const expanded = open && !!panel;
  const state = !panel ? 'sheet--empty' : expanded ? 'sheet--expanded' : 'sheet--collapsed';

  return (
    <section aria-label="Parametry i legenda" className={`sheet ${state}`}>
      {panel && (
        <>
          <button
            type="button"
            className="sheet__handle"
            aria-expanded={expanded}
            aria-controls={`${id}-body`}
            aria-label={expanded ? 'Zwiń panel' : 'Rozwiń panel parametrów'}
            onClick={() => setOpen((o) => !o)}
          >
            <span className="sheet__grip" />
          </button>
          <div id={`${id}-body`} className="sheet__body">
            {expanded ? (
              <Expanded panel={panel} legend={legend} onCollapse={() => setOpen(false)} />
            ) : (
              <Collapsed panel={panel} legend={legend} onExpand={() => setOpen(true)} />
            )}
          </div>
          {!expanded && <span className="sheet__attr">© OSM · Sentinel-2 · GUGiK</span>}
        </>
      )}
      <footer className="sheet__disclaimer">
        <strong>Projekt naukowy. Nie służy do nawigacji.</strong> Dno modelowane z obrazów satelitarnych z niepewnością.
      </footer>
    </section>
  );
}

function Collapsed({ panel, legend, onExpand }: { panel: ParameterPanelProps; legend?: LegendProps; onExpand: () => void }) {
  const { value, limits, onChange } = panel.draft;
  const [lo, hi] = limits.draft;
  const step = (dir: 1 | -1) => onChange(Math.min(hi, Math.max(lo, round05(value + dir * STEP))));
  return (
    <div className="sheet__summary">
      <div className="sheet__grid">
        <div className="sheet__cell">
          <span className="sheet__cap">Zanurzenie</span>
          <div className="sheet__stepper">
            <button type="button" className="sheet__step" aria-label="Zmniejsz zanurzenie" onClick={() => step(-1)}>
              −
            </button>
            <span className="sheet__num">{fmtM(value)}</span>
            <button type="button" className="sheet__step" aria-label="Zwiększ zanurzenie" onClick={() => step(1)}>
              +
            </button>
          </div>
        </div>
        <button
          type="button"
          className="sheet__level"
          aria-label={`Poziom wody ${fmtLevel(panel.level.h)}, zmień`}
          onClick={onExpand}
        >
          <span className="sheet__cap">Poziom wody</span>
          <span className="sheet__num">{fmtLevel(panel.level.h)}</span>
        </button>
      </div>
      {legend && <Legend {...legend} compact namesOnly />}
    </div>
  );
}

function Expanded({ panel, legend, onCollapse }: { panel: ParameterPanelProps; legend?: LegendProps; onCollapse: () => void }) {
  return (
    <div className="sheet__full">
      <div className="sheet__head">
        <h2>Parametry</h2>
        <button type="button" className="sheet__close" onClick={onCollapse}>
          Pokaż mapę
        </button>
      </div>
      <ParameterPanel
        {...panel}
        level={{ ...panel.level, variant: 'mobile' }}
        layers={{ ...panel.layers, variant: 'chips' }}
      />
      {legend && <Legend {...legend} compact />}
    </div>
  );
}
