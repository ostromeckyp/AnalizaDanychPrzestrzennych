import type { SceneRow, YearFilter } from './types';

export type SceneListProps = {
  years: number[];
  year: YearFilter;
  counter: string;
  rows: SceneRow[];
  selected?: string;
  overlay: string[];
  onYear: (y: YearFilter) => void;
  onSelect: (date: string) => void;
  onToggle: (date: string) => void;
  onReset: () => void;
};

export function SceneList(p: SceneListProps) {
  const chips: [string, YearFilter][] = [['Wszystkie', 'all'], ...p.years.map((y): [string, YearFilter] => [String(y), y])];
  return (
    <>
      <div role="group" aria-label="Filtr roku" className="hchips">
        {chips.map(([label, v]) => (
          <button key={label} type="button" className="hchip" aria-pressed={p.year === v} onClick={() => p.onYear(v)}>
            {label}
          </button>
        ))}
      </div>
      <div className="hcount">
        <span>{p.counter}</span>
        <span>Nałóż na mapę</span>
      </div>
      {p.rows.length === 0 ? (
        <div className="hempty">
          <strong>Brak scen dla tego filtra</strong>
          <span>
            {p.year === 'all' ? 'Brak scen.' : `W ${p.year} r. żadna scena nie przeszła filtra zachmurzenia.`} Wybierz inny rok.
          </span>
          <button type="button" className="btn-outline" onClick={p.onReset}>
            Pokaż wszystkie sceny
          </button>
        </div>
      ) : (
        <ul className="hlist">
          {p.rows.map((r) => {
            const sel = r.date === p.selected;
            return (
              <li key={r.date} className={sel ? 'hrow hrow--sel' : 'hrow'}>
                <button type="button" className="hrow__main" aria-pressed={sel} onClick={() => p.onSelect(r.date)}>
                  <span
                    className={r.dashed ? 'hrow__dot hrow__dot--dashed' : 'hrow__dot'}
                    style={{ background: r.color }}
                    aria-hidden="true"
                  />
                  <span className="hrow__date">{r.dateLabel}</span>
                  <span>{r.level}</span>
                  <span className="hrow__area">{r.area}</span>
                </button>
                <label className="hrow__check">
                  <input
                    type="checkbox"
                    checked={p.overlay.includes(r.date)}
                    onChange={() => p.onToggle(r.date)}
                    aria-label={`Nałóż linię brzegową z ${r.dateLabel}`}
                  />
                </label>
                {r.overlayStatus === 'error' && (
                  <span role="alert" className="hrow__err">
                    Nie udało się pobrać linii
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
