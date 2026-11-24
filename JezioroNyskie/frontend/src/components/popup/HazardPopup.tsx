import { useEffect, useRef } from 'react';
import type { HazardPopupModel } from './types';
import './popup.css';

export type HazardPopupProps = { model: HazardPopupModel; onClose: () => void };

export function HazardPopup({ model, onClose }: HazardPopupProps) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => ref.current?.focus({ preventScroll: true }), []);
  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="Przeszkoda z locji"
      tabIndex={-1}
      className="popup"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose();
      }}
    >
      <div className="popup__body">
        <div className="popup__head">
          <span className="popup__title popup__title--hazard">{model.title}</span>
          <button type="button" className="popup__close" aria-label="Zamknij" onClick={onClose}>
            <span aria-hidden="true">✕</span>
          </button>
        </div>
        <div className="popup__value popup__value--small">{model.level}</div>
        {model.relation && (
          <div className={`popup__zone popup__hazard-rel popup__hazard-rel--${model.relation.kind}`}>
            <strong>{model.relation.text}</strong>
          </div>
        )}
        <p className="popup__text">{model.description}</p>
        {model.note && <p className="popup__note">{model.note}</p>}
      </div>
      <p className="popup__caveat">
        {model.sourceUrl ? (
          <a href={model.sourceUrl} target="_blank" rel="noopener noreferrer">
            {model.sourceLabel}
          </a>
        ) : (
          model.sourceLabel
        )}
      </p>
      <p className="popup__caveat">{model.disclaimer}</p>
    </div>
  );
}
