import { fmtM } from '../../format';
import './states.css';

// Stan B: pigułka z paskiem; `draft` to zanurzenie, o które pyta użytkownik.
export function RecalcPill({ draft }: { draft: number }) {
  return (
    <div role="status" className="pill pill--top">
      <span className="spinner" aria-hidden="true" />
      Przeliczam strefy dla {fmtM(draft)}…
      <span className="pill__bar" aria-hidden="true" />
    </div>
  );
}
