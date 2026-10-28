import type { MethodTile } from '../../vm/useMethodVm';

export function AccuracyTiles({ tiles }: { tiles: MethodTile[] }) {
  return (
    <div className="tiles">
      {tiles.map((t) => (
        <div key={t.label} role="group" aria-label={t.label} className="tile">
          <span className="tile__label">{t.label}</span>
          <strong className="tile__value">{t.value}</strong>
          <span className="tile__sub">{t.sub}</span>
        </div>
      ))}
    </div>
  );
}
