import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => {
  const handlers: Record<string, (e?: unknown) => void> = {};
  const sources: Record<string, unknown> = {};
  const layers = new Set<string>();
  const imageSource = { updateImage: vi.fn(), setData: vi.fn() };
  const fns = {
    addSource: vi.fn((id: string) => {
      sources[id] = imageSource;
    }),
    addLayer: vi.fn((l: { id: string }) => {
      layers.add(l.id);
    }),
    addImage: vi.fn(),
    updateImage: vi.fn(),
    setPaintProperty: vi.fn(),
    setLayoutProperty: vi.fn(),
    setFilter: vi.fn(),
    fitBounds: vi.fn(),
    addControl: vi.fn(),
    remove: vi.fn(),
    zoomIn: vi.fn(),
    zoomOut: vi.fn(),
    resetNorth: vi.fn(),
    getSource: vi.fn((id: string) => sources[id]),
    getLayer: vi.fn((id: string) => (layers.has(id) ? {} : undefined)),
    hasImage: vi.fn(() => true),
    on: vi.fn((ev: string, cb: (e?: unknown) => void) => {
      handlers[ev] = cb;
    }),
  };
  const MapCtor = vi.fn();
  const markers: { opts: { element: HTMLElement; anchor: string; offset: number[] }; lngLat?: number[]; removed: boolean }[] = [];
  return { markers, handlers, sources, layers, imageSource, fns, MapCtor };
});

vi.mock('maplibre-gl', () => {
  class FakeMap {
    constructor(opts: unknown) {
      h.MapCtor(opts);
      Object.assign(this, h.fns);
    }
  }
  class AttributionControl {
    constructor(public opts: unknown) {}
  }
  class ScaleControl {
    constructor(public opts: unknown) {}
  }
  class Marker {
    rec: (typeof h.markers)[number];
    constructor(opts: (typeof h.markers)[number]['opts']) {
      this.rec = { opts, removed: false };
      h.markers.push(this.rec);
    }
    setLngLat(l: number[]) {
      this.rec.lngLat = l;
      return this;
    }
    addTo() {
      return this;
    }
    remove() {
      this.rec.removed = true;
      return this;
    }
  }
  return { default: { Map: FakeMap, AttributionControl, ScaleControl, Marker }, Map: FakeMap, AttributionControl };
});

import { fireEvent, screen } from '@testing-library/react';
import { MapView, type MapViewProps } from './MapView';

const fc = (n: number) => ({ type: 'FeatureCollection', features: [], n });
const base: MapViewProps = {
  theme: 'light',
  bbox: [17.0, 50.4, 17.1, 50.5],
  zones: fc(1),
  bottomLayer: { url: '/api/layers/bottom.png', coordinates: [[17, 50.5], [17.1, 50.5], [17.1, 50.4], [17, 50.4]] },
  uncertaintyLayer: { url: '/api/layers/unc.png?v=1', coordinates: [[17, 50.5], [17.1, 50.5], [17.1, 50.4], [17, 50.4]] },
  visible: { zones: true, bottom: true, uncertainty: true, shorelines: true, marinas: true },
  basemap: 'osm',
  npp: 195.91,
  onMapClick: vi.fn(),
};

function mount(props: Partial<MapViewProps> = {}) {
  const r = render(<MapView {...base} {...props} />);
  act(() => h.handlers.load?.());
  return r;
}

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
  h.markers.length = 0;
  h.layers.clear();
  h.layers.add('basemap-osm').add('basemap-orto'); // z obiektu style
  for (const k of Object.keys(h.sources)) delete h.sources[k];
  for (const k of Object.keys(h.handlers)) delete h.handlers[k];
});

describe('MapView', () => {
  it('dodaje warstwy stref z krytem 0,55 i kreskowaniem dla risk', () => {
    mount();
    expect(h.fns.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'zones-risk',
        paint: expect.objectContaining({ 'fill-pattern': 'risk-hatch', 'fill-opacity': 0.55 }),
      }),
      undefined,
    );
    expect(h.fns.addImage).toHaveBeenCalledWith('risk-hatch', expect.objectContaining({ width: 16 }));
    expect(h.fns.fitBounds).toHaveBeenCalledWith([[17.0, 50.4], [17.1, 50.5]], expect.anything());
  });

  it('aktualizuje strefy przez setData, bez ponownego dodawania', () => {
    const { rerender } = mount();
    const addSourceCalls = h.fns.addSource.mock.calls.length;
    const z2 = fc(2);
    rerender(<MapView {...base} zones={z2} />);
    expect(h.imageSource.setData).toHaveBeenCalledWith(z2);
    expect(h.fns.addSource.mock.calls.length).toBe(addSourceCalls);
  });

  it('zmiana motywu: kolory, kreskowanie i url obrazów bez nowej mapy', () => {
    const { rerender } = mount();
    rerender(<MapView {...base} theme="dark" />);
    expect(h.MapCtor).toHaveBeenCalledTimes(1);
    expect(h.fns.setPaintProperty).toHaveBeenCalledWith('zones-danger', 'fill-color', '#d0508a');
    expect(h.fns.updateImage).toHaveBeenCalledWith('risk-hatch', expect.anything());
    expect(h.imageSource.updateImage).toHaveBeenCalledWith(
      expect.objectContaining({ url: expect.stringMatching(/^(?:(?!theme=).)*theme=dark$/) }),
    );
    expect(h.imageSource.updateImage).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/api/layers/unc.png?v=1&theme=dark' }),
    );
  });

  it('kliknięcie zgłasza lon/lat', () => {
    const onMapClick = vi.fn();
    mount({ onMapClick });
    h.handlers.click({ lngLat: { lng: 17.25, lat: 50.45 } });
    expect(onMapClick).toHaveBeenCalledWith(17.25, 50.45);
  });

  it('widoczność przez layout visibility', () => {
    const { rerender } = mount();
    rerender(<MapView {...base} visible={{ ...base.visible, bottom: false }} />);
    expect(h.fns.setLayoutProperty).toHaveBeenCalledWith('bottom', 'visibility', 'none');
  });

  it('npp dochodzi po load: warstwa przerywana istnieje, filtry ustawiane jako wyrażenia', () => {
    const { rerender } = mount({ npp: undefined });
    expect(h.layers.has('shorelines-dashed')).toBe(true);
    expect(h.fns.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'shorelines-dashed', filter: false }),
      undefined,
    );
    rerender(<MapView {...base} npp={195.91} />);
    expect(h.fns.setFilter).toHaveBeenCalledWith('shorelines-dashed', ['<', ['get', 'h_t'], 195.91]);
    expect(h.fns.setFilter).toHaveBeenCalledWith('shorelines', ['>=', ['get', 'h_t'], 195.91]);
  });

  it('przełącza podkład na ortofotomapę', () => {
    const { rerender } = mount();
    rerender(<MapView {...base} basemap="orto" />);
    expect(h.fns.setLayoutProperty).toHaveBeenCalledWith('basemap-orto', 'visibility', 'visible');
    expect(h.fns.setLayoutProperty).toHaveBeenCalledWith('basemap-osm', 'visibility', 'none');
  });

  it('własne przyciski 44 px wołają mapę', () => {
    mount();
    for (const [label, fn] of [['Przybliż', 'zoomIn'], ['Oddal', 'zoomOut'], ['Północ', 'resetNorth']] as const) {
      const b = screen.getByRole('button', { name: label });
      expect(b).toHaveStyle({ width: '44px', height: '44px' });
      fireEvent.click(b);
      expect(h.fns[fn]).toHaveBeenCalled();
    }
  });

  it('zamyka mapę przy odmontowaniu', () => {
    mount().unmount();
    expect(h.fns.remove).toHaveBeenCalled();
  });

  it('adds a metric scale control at bottom-left', () => {
    mount();
    const call = h.fns.addControl.mock.calls.find(([c]) => c?.constructor?.name === 'ScaleControl');
    expect(call).toBeDefined();
    expect(call![0].opts).toEqual({ unit: 'metric', maxWidth: 100 });
    expect(call![1]).toBe('bottom-left');
  });

  it('anchors pinOverlay in a marker at the pin and removes it when the pin is cleared', () => {
    const { rerender } = mount({ pin: { lon: 17.05, lat: 50.45 }, pinOverlay: <p>nakładka</p> });
    expect(h.markers).toHaveLength(1);
    expect(h.markers[0].lngLat).toEqual([17.05, 50.45]);
    expect(h.markers[0].opts.anchor).toBe('bottom');
    expect(h.markers[0].opts.element.textContent).toBe('nakładka');
    rerender(<MapView {...base} pin={undefined} pinOverlay={undefined} />);
    expect(h.markers[0].removed).toBe(true);
    expect(h.markers[0].opts.element.textContent).toBe('');
  });
});
