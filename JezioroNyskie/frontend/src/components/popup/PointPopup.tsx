import type { PopupModel } from './types';
import './popup.css';

export type PointPopupProps = {
  model?: PopupModel;
  /** Bez modelu: trwa pobieranie albo się nie udało. */
  state?: 'loading' | 'error';
  onClose: () => void;
};

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button type="button" className="popup__close" aria-label="Zamknij" onClick={onClose}>
      <span aria-hidden="true">✕</span>
    </button>
  );
}

export function PointPopup({ model, state, onClose }: PointPopupProps) {
  if (!model) {
    return (
      <div role="dialog" aria-label="Informacje o punkcie" className="popup">
        <div className="popup__head">
          {state === 'error' ? (
            <p role="alert" className="popup__msg">
              Nie udało się pobrać danych punktu.
            </p>
          ) : (
            <p role="status" className="popup__msg">
              Sprawdzam punkt…
            </p>
          )}
          <CloseButton onClose={onClose} />
        </div>
      </div>
    );
  }
  const { zone } = model;
  return (
    <div role="dialog" aria-label="Informacje o punkcie" className="popup">
      <div className="popup__body">
        <div className="popup__head">
          <span className="popup__title">{model.title}</span>
          <CloseButton onClose={onClose} />
        </div>
        <div className={model.variant === 'D' ? 'popup__value popup__value--small' : 'popup__value'}>{model.value}</div>
        {model.note && <span className={model.variant === 'D' ? 'popup__note popup__note--d' : 'popup__note'}>{model.note}</span>}
        {zone && (
          <div className="popup__zone">
            <span className={`swatch-z swatch-z--${zone.key}`} aria-hidden="true" />
            <span>
              <strong>{zone.name}</strong>
              {zone.label ? ` ${zone.label}` : ''}
            </span>
          </div>
        )}
        {model.noZone && <div className="popup__zone popup__zone--none">{model.noZone}</div>}
      </div>
      {model.rows.length > 0 && (
        <dl className="popup__rows">
          {model.rows.map((r) => (
            <div key={r.term} className="popup__row">
              <dt>{r.term}</dt>
              <dd>{r.desc}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
