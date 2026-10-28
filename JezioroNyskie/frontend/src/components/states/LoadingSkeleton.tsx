import './states.css';

// Stan A: szkielet mapy i legendy do czasu pierwszej odpowiedzi.
export function LoadingSkeleton() {
  return (
    <div className="skeleton">
      <div className="skeleton__lake" aria-hidden="true" />
      <div className="skeleton__legend" aria-hidden="true">
        <span style={{ width: '70%' }} />
        <span style={{ width: '90%' }} />
        <span style={{ width: '55%' }} />
      </div>
      <div role="status" className="pill pill--center">
        <span className="spinner" aria-hidden="true" />
        Wczytuję model dna i strefy…
      </div>
    </div>
  );
}
