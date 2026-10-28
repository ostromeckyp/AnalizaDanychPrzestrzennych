import { AppNav } from '../components/chrome/AppNav';
import { Footer } from '../components/chrome/Footer';
import { LevelChart } from '../components/history/LevelChart';
import { SceneCard } from '../components/history/SceneCard';
import { SceneList } from '../components/history/SceneList';
import { MapView } from '../components/map/MapView';
import { MobileHeader } from '../components/mobile/MobileHeader';
import { fmtNum } from '../format';
import { LEVEL_SCALE, levelColor } from '../theme';
import { useHistoryVm } from '../vm/useHistoryVm';
import { useThemeVm } from '../vm/useThemeVm';
import { useViewport } from '../vm/useViewport';
import './historyPage.css';

// Skala legendy z LEVEL_SCALE (jedno źródło), pośrednie stopnie przez levelColor.
const { h0, h1 } = LEVEL_SCALE;
const STOPS = [0, 1 / 3, 2 / 3, 1].map((t) => h0 + (h1 - h0) * t);
const GRADIENT = `linear-gradient(90deg, ${STOPS.map(levelColor).join(', ')})`;

function ShoreLegend() {
  return (
    <section aria-label="Legenda linii brzegowych" className="hlegend">
      <strong>Kolor linii = poziom wody</strong>
      <span aria-hidden="true" className="hlegend__bar" style={{ background: GRADIENT }} />
      <div className="hlegend__ticks">
        {STOPS.map((s, i) => (
          <span key={s}>{fmtNum(s, 1)}{i === STOPS.length - 1 ? ' m n.p.m.' : ''}</span>
        ))}
      </div>
      <span className="hlegend__note">
        Niższe poziomy rysowane dodatkowo linią przerywaną, żeby dało się je odróżnić bez koloru.
      </span>
    </section>
  );
}

export function HistoryPage() {
  const vm = useHistoryVm();
  const theme = useThemeVm();
  const mobile = useViewport() === 'mobile';

  const body =
    vm.status === 'loading' ? (
      <p role="status" className="hmsg">Ładuję sceny…</p>
    ) : vm.status === 'error' ? (
      <div role="alert" className="hmsg">
        <strong>Nie udało się pobrać listy scen</strong>
        <span>Serwer nie odpowiedział.</span>
        <button type="button" className="btn-primary" onClick={vm.retry}>
          Spróbuj ponownie
        </button>
      </div>
    ) : (
      <>
        <div className="hhead">
          <h2>Poziom wody na scenach Sentinel-2</h2>
          <LevelChart scenes={vm.allScenes} npp={vm.npp} selected={vm.selected?.date} />
        </div>
        <SceneList
          years={vm.years}
          year={vm.year}
          counter={vm.counter}
          rows={vm.scenes}
          selected={vm.selected?.date}
          overlay={vm.overlay}
          onYear={vm.setYear}
          onSelect={vm.select}
          onToggle={vm.toggleOverlay}
          onReset={() => vm.setYear('all')}
        />
        {mobile && vm.selected && <SceneCard scene={vm.selected} />}
      </>
    );

  const map = vm.bbox && (
    <MapView
      theme={theme}
      bbox={vm.bbox}
      shorelines={vm.shorelines}
      npp={vm.npp}
      visible={{ zones: false, bottom: false, uncertainty: false, shorelines: true, marinas: false, gravel: false }}
      basemap="osm"
      onMapClick={() => undefined}
    />
  );

  if (mobile) {
    return (
      <main className="history history--mobile" aria-label="Historia linii brzegowych">
        <div className="history__mapbox">
          {map}
          <MobileHeader />
        </div>
        <div className="history__scroll">{body}</div>
        <ShoreLegend />
        <Footer />
      </main>
    );
  }

  return (
    <main className="history" aria-label="Historia linii brzegowych">
      <div className="history__map">{map}</div>
      <aside aria-label="Sceny satelitarne" className="history__panel">
        <AppNav />
        <div className="history__scroll">{body}</div>
      </aside>
      {vm.status === 'ready' && vm.selected && (
        <div className="history__card">
          <SceneCard scene={vm.selected} />
        </div>
      )}
      <div className="history__legend">
        <ShoreLegend />
      </div>
      <Footer />
    </main>
  );
}
