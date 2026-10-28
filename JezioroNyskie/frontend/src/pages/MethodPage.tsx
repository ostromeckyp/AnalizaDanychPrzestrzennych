import { AppNav } from '../components/chrome/AppNav';
import { Footer } from '../components/chrome/Footer';
import { AccuracyTiles } from '../components/method/AccuracyTiles';
import { AreaLevelChart } from '../components/method/AreaLevelChart';
import { SourcesTable } from '../components/method/SourcesTable';
import { MobileHeader } from '../components/mobile/MobileHeader';
import { useMethodVm } from '../vm/useMethodVm';
import { useViewport } from '../vm/useViewport';
import './methodPage.css';

export function MethodPage() {
  const vm = useMethodVm();
  const mobile = useViewport() === 'mobile';

  const body =
    vm.status === 'loading' ? (
      <p role="status" className="mmsg">Ładuję dane o metodzie…</p>
    ) : vm.status === 'error' ? (
      <div role="alert" className="mmsg">
        <strong>Nie udało się pobrać danych modelu</strong>
        <span>Serwer nie odpowiedział.</span>
        <button type="button" className="btn-primary" onClick={vm.retry}>
          Spróbuj ponownie
        </button>
      </div>
    ) : (
      <>
        <section aria-labelledby="m-intro">
          <h2 id="m-intro">Jak powstaje mapa głębokości</h2>
          <p className="method__lead">{vm.intro}</p>
        </section>
        <section aria-labelledby="m-steps">
          <h2 id="m-steps">Pięć kroków</h2>
          <ol className="steps">
            {vm.steps.map((s) => (
              <li key={s.n} className="step">
                <span className="step__n" aria-hidden="true">{s.n}</span>
                <h3>{s.title}</h3>
                <p>{s.text}</p>
              </li>
            ))}
          </ol>
        </section>
        {vm.chart && (
          <section aria-labelledby="m-chart">
            <h2 id="m-chart">Poziom a powierzchnia lustra wody</h2>
            <p className="method__note">
              Każdy punkt to jedna scena satelitarna: poziom wody przypisany scenie i powierzchnia z maski wody. Gładka
              zależność potwierdza, że maski są spójne; punkty odstające to zwykle chmury lub zakwit glonów.
            </p>
            <AreaLevelChart {...vm.chart} />
          </section>
        )}
        <section aria-labelledby="m-acc">
          <h2 id="m-acc">Dokładność modelu</h2>
          <AccuracyTiles tiles={vm.tiles} />
        </section>
        <section aria-labelledby="m-src">
          <h2 id="m-src">Źródła danych</h2>
          <SourcesTable rows={vm.sources} />
        </section>
        <aside className="method__warn" aria-label="Zastrzeżenie">
          <strong>Projekt naukowy. Nie służy do nawigacji.</strong> Dno modelowane z obrazów satelitarnych z
          niepewnością. Na wodzie kieruj się oznakowaniem, komunikatami administratora zbiornika i własną oceną.
        </aside>
        <p className="method__credit">{vm.credit}</p>
      </>
    );

  return (
    <div className={mobile ? 'method method--mobile' : 'method'}>
      {mobile ? <MobileHeader /> : <div className="method__nav"><AppNav /></div>}
      <main className="method__main" aria-label="O metodzie">{body}</main>
      <Footer />
    </div>
  );
}
