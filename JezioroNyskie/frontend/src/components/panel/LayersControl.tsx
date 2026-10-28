import { useId } from 'react';
import type { Basemap, LayerKey } from './types';
import './panel.css';

export type LayersControlProps = {
  visible: Record<LayerKey, boolean>;
  basemap: Basemap;
  variant: 'list' | 'chips';
  onToggle: (name: LayerKey) => void;
  onBasemap: (b: Basemap) => void;
};

const LAYERS: [LayerKey, string][] = [
  ['zones', 'Strefy dla jachtu'],
  ['bottom', 'Model dna (mapa wysokości)'],
  ['uncertainty', 'Niepewność modelu'],
  ['shorelines', 'Historyczne linie brzegowe'],
  ['marinas', 'Przystanie i slipy (OSM)'],
];

export function LayersControl({ visible, basemap, variant, onToggle, onBasemap }: LayersControlProps) {
  const id = useId();
  return (
    <section className="field">
      <span className="field__label">Warstwy</span>
      {variant === 'list' ? (
        <div className="layers">
          {LAYERS.map(([key, label]) => (
            <label key={key} htmlFor={`${id}-${key}`} className="layers__row">
              <input type="checkbox" id={`${id}-${key}`} checked={visible[key]} onChange={() => onToggle(key)} />
              <span>{label}</span>
            </label>
          ))}
        </div>
      ) : (
        <div role="group" aria-label="Warstwy" className="chips">
          {LAYERS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              className="chip"
              aria-pressed={visible[key]}
              onClick={() => onToggle(key)}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      <div role="group" aria-label="Podkład" className="segmented segmented--full">
        <button type="button" aria-pressed={basemap === 'map'} onClick={() => onBasemap('map')}>
          Mapa
        </button>
        <button type="button" aria-pressed={basemap === 'ortho'} onClick={() => onBasemap('ortho')}>
          Ortofotomapa
        </button>
      </div>
    </section>
  );
}
