import { fmtKm2, fmtLevel, fmtNum } from '../../format';
import type { ChartLegend, ChartPoint } from '../../vm/useMethodVm';

// Wykres ręcznie w SVG; viewBox responsywny (szerokość 100%, wysokość z proporcji).
const W = 640;
const H = 320;
const X0 = 52;
const X1 = 624;
const Y0 = 16;
const Y1 = 272;

export type AreaLevelChartProps = {
  points: ChartPoint[];
  nodes: { area: number; h: number }[];
  npp: number;
  maxPp: number;
  legend: ChartLegend[];
};

function ticks(lo: number, hi: number, count: number): number[] {
  const step = (hi - lo) / count;
  return Array.from({ length: count + 1 }, (_, i) => lo + step * i);
}

export function AreaLevelChart({ points, nodes, npp, maxPp, legend }: AreaLevelChartProps) {
  const areas = [...points.map((p) => p.area), ...nodes.map((n) => n.area)].filter(Number.isFinite);
  const levels = [...points.map((p) => p.h), ...nodes.map((n) => n.h), npp, maxPp].filter(Number.isFinite);
  if (areas.length === 0 || levels.length === 0) {
    return <p className="chart__empty">Brak danych do wykresu.</p>;
  }
  const aLo = Math.floor(Math.min(...areas));
  const aHi = Math.max(Math.ceil(Math.max(...areas)), aLo + 1);
  const hLo = Math.floor(Math.min(...levels));
  const hHi = Math.max(Math.ceil(Math.max(...levels)), hLo + 1);
  const x = (a: number) => X0 + ((a - aLo) / (aHi - aLo)) * (X1 - X0);
  const y = (h: number) => Y0 + ((hHi - h) / (hHi - hLo)) * (Y1 - Y0);
  const curve = [...nodes].sort((a, b) => a.area - b.area);

  const refLines = [
    { name: 'NPP', value: npp },
    { name: 'Max PP', value: maxPp },
  ].filter((r) => Number.isFinite(r.value));

  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="chart__svg"
        role="group"
        aria-label={`Wykres: poziom wody od ${fmtLevel(Math.min(...levels))} do ${fmtLevel(Math.max(...levels))} względem powierzchni lustra wody ${fmtKm2(Math.min(...areas))}–${fmtKm2(Math.max(...areas))}`}
      >
        {ticks(hLo, hHi, 4).map((v) => (
          <g key={`h${v}`}>
            <line x1={X0} y1={y(v)} x2={X1} y2={y(v)} stroke="var(--border)" />
            <text x={X0 - 6} y={y(v) + 4} fontSize="12" textAnchor="end" fill="var(--muted)">
              {fmtNum(v, 1)}
            </text>
          </g>
        ))}
        {ticks(aLo, aHi, 4).map((v) => (
          <text key={`a${v}`} x={x(v)} y={Y1 + 18} fontSize="12" textAnchor="middle" fill="var(--muted)">
            {fmtNum(v, 1)}
          </text>
        ))}
        <text x={X1} y={H - 6} fontSize="12" textAnchor="end" fill="var(--muted)">
          powierzchnia [km²]
        </text>
        <text x={X0} y={Y0 - 4} fontSize="12" fill="var(--muted)">
          poziom wody [m n.p.m.]
        </text>
        {refLines.map((r, i) => (
          <g key={r.name} role="img" aria-label={`${r.name} ${fmtLevel(r.value)}`}>
            <line x1={X0} y1={y(r.value)} x2={X1} y2={y(r.value)} stroke="var(--accent)" strokeDasharray={i === 0 ? '6 4' : '2 4'} strokeWidth="1.5" />
            <text x={X1} y={y(r.value) - 5} fontSize="12" textAnchor="end" fill="var(--accent)">
              {r.name}
            </text>
          </g>
        ))}
        {curve.length > 1 && (
          <polyline
            points={curve.map((n) => `${x(n.area).toFixed(1)},${y(n.h).toFixed(1)}`).join(' ')}
            fill="none"
            stroke="var(--border-strong)"
            strokeWidth="2"
          />
        )}
        {points.map((p) => (
          <circle key={p.date} cx={x(p.area)} cy={y(p.h)} r="5" fill={p.color} stroke="var(--panel)" strokeWidth="1.5">
            <title>{`${p.date}: ${fmtKm2(p.area)}, ${fmtLevel(p.h)}`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="chart__legend">
        {legend.map((l) => (
          <span key={l.code} className="chart__key">
            <span className="chart__dot" style={{ background: l.color }} aria-hidden="true" />
            {l.label}
          </span>
        ))}
        <span className="chart__key">Linia: krzywa poziom–powierzchnia z węzłów. Kółka: sceny Sentinel-2.</span>
      </figcaption>
    </figure>
  );
}
