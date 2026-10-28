import { fmtDate, fmtLevel, fmtNum } from '../../format';
import type { SceneRow } from './types';

// Wykres ręcznie w SVG (viewBox z makiety History.dc.html: 360 x 120, pole wykresu 34..356 x 18..90).
const X0 = 34;
const X1 = 356;
const Y0 = 18;
const Y1 = 90;

export type LevelChartProps = { scenes: SceneRow[]; npp?: number; selected?: string };

export function LevelChart({ scenes, npp, selected }: LevelChartProps) {
  if (scenes.length === 0) return null;
  const pts = [...scenes].sort((a, b) => (a.date < b.date ? -1 : 1));
  const hs = pts.map((p) => p.h);
  const hMin = Math.min(...hs);
  const hMax = Math.max(...hs);
  const first = pts[0];
  const last = pts[pts.length - 1];

  const all = npp == null ? hs : [...hs, npp];
  const lo = Math.floor(Math.min(...all));
  const hi = Math.max(Math.ceil(Math.max(...all)), lo + 1);
  const step = Math.max(1, Math.ceil((hi - lo) / 3));
  const ticks: number[] = [];
  for (let v = hi; v >= lo; v -= step) ticks.push(v);

  const y = (h: number) => Y0 + ((hi - h) / (hi - lo)) * (Y1 - Y0);
  const t0 = Date.parse(first.date);
  const span = Date.parse(last.date) - t0;
  const x = (d: string) => (span > 0 ? X0 + ((Date.parse(d) - t0) / span) * (X1 - X0) : (X0 + X1) / 2);

  const label =
    `Wykres poziomu wody w czasie: od ${fmtLevel(hMin)} do ${fmtLevel(hMax)}, ` +
    `sceny od ${fmtDate(first.date)} do ${fmtDate(last.date)}`;

  return (
    <svg viewBox="0 0 360 120" className="lvchart" role="img" aria-label={label}>
      {ticks.map((v) => (
        <g key={v}>
          <line x1={X0} y1={y(v)} x2={X1} y2={y(v)} stroke="var(--border)" />
          <text x={28} y={y(v) + 4} fontSize="11" textAnchor="end" fill="var(--muted)">
            {fmtNum(v, 0)}
          </text>
        </g>
      ))}
      {npp != null && (
        <>
          <line x1={X0} y1={y(npp)} x2={X1} y2={y(npp)} stroke="var(--accent)" strokeDasharray="4 4" />
          <text x={X1} y={y(npp) - 4} fontSize="10" textAnchor="end" fill="var(--accent)">
            NPP {fmtNum(npp, 2)}
          </text>
        </>
      )}
      <polyline
        points={pts.map((p) => `${x(p.date).toFixed(1)},${y(p.h).toFixed(1)}`).join(' ')}
        fill="none"
        stroke="var(--border-strong)"
        strokeWidth="1.5"
      />
      {pts.map((p) => (
        <circle
          key={p.date}
          cx={x(p.date)}
          cy={y(p.h)}
          r={p.date === selected ? 6.5 : 4.5}
          fill={p.color}
          stroke="var(--panel)"
          strokeWidth="1.5"
        />
      ))}
      <text x={X0} y={114} fontSize="11" fill="var(--muted)">
        {first.date.slice(0, 4)}
      </text>
      <text x={X1} y={114} fontSize="11" textAnchor="end" fill="var(--muted)">
        {last.date.slice(0, 4)}
      </text>
    </svg>
  );
}
