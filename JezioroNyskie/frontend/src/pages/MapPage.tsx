import { AppNav } from '../components/chrome/AppNav';
import { Footer } from '../components/chrome/Footer';
import { Legend } from '../components/legend/Legend';
import { MapView } from '../components/map/MapView';
import { ParameterPanel } from '../components/panel/ParameterPanel';
import { PointPopup } from '../components/popup/PointPopup';
import { ErrorOverlay } from '../components/states/ErrorOverlay';
import { LoadingSkeleton } from '../components/states/LoadingSkeleton';
import { OfflineBar } from '../components/states/OfflineBar';
import { RecalcPill } from '../components/states/RecalcPill';
import { useMapPageVm } from '../vm/useMapPageVm';
import './mapPage.css';

// Układ desktop (§16.2): mapa pod spodem, nad nią pływający panel, legenda, popup i stany.
export function MapPage() {
  const vm = useMapPageVm();
  const { meta, map, zonesState: z, point } = vm;

  const metaFailed = meta.status === 'error';
  const loading = !metaFailed && (meta.status === 'loading' || (z.status === 'first-load' && !map.zones));
  const failed = metaFailed || z.status === 'error';

  return (
    <main className="mappage" aria-label="Mapa">
      <div className={failed ? 'mappage__map mappage__map--dim' : 'mappage__map'}>
        {meta.data && (
          <MapView
            theme={vm.theme}
            bbox={meta.data.bbox_wgs84}
            zones={map.zones}
            bottomLayer={map.bottomLayer}
            uncertaintyLayer={map.uncertaintyLayer}
            marinas={map.marinas}
            visible={map.visible}
            basemap={map.basemap}
            npp={meta.data.npp}
            pin={map.pin}
            pinOverlay={
              map.pin && (
                <PointPopup model={point.popup} state={point.status === 'error' ? 'error' : 'loading'} onClose={vm.closePopup} />
              )
            }
            onMapClick={vm.onMapClick}
          />
        )}
      </div>

      <div className="mappage__panel">
        <AppNav />
        <div className="mappage__scroll">{vm.panel && <ParameterPanel {...vm.panel} />}</div>
      </div>

      {vm.legend && (
        <div className="mappage__legend">
          <Legend {...vm.legend} />
        </div>
      )}

      {!map.pin && !loading && !failed && <p className="mappage__hint">Kliknij w wodę, aby sprawdzić głębokość</p>}

      {loading && <LoadingSkeleton />}
      {!loading && z.status === 'recalculating' && <RecalcPill draft={vm.draft} />}
      {failed && (
        <ErrorOverlay
          lastOk={z.lastOk}
          retrying={metaFailed ? false : z.isRetrying}
          onRetry={metaFailed ? meta.retry : z.retry}
        />
      )}
      {z.status === 'offline' && <OfflineBar lastOkAt={z.lastOkAt} onRetry={z.retry} />}
      <Footer />
    </main>
  );
}
