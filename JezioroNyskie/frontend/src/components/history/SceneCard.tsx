import { Link } from 'react-router-dom';
import type { SceneRow } from './types';

export function SceneCard({ scene }: { scene: SceneRow }) {
  return (
    <section className="scenecard" aria-label="Wybrana scena">
      <span className="scenecard__kicker">Wybrana scena</span>
      <span className="scenecard__date">{scene.dateLabel}</span>
      <dl className="scenecard__dl">
        <dt>Poziom</dt>
        <dd>{scene.level}</dd>
        <dt>Powierzchnia</dt>
        <dd>{scene.area}</dd>
        <dt>Źródło</dt>
        <dd>{scene.source}</dd>
      </dl>
      <Link to={scene.mapHref} className="scenecard__link">
        Ustaw ten poziom na mapie
      </Link>
    </section>
  );
}
