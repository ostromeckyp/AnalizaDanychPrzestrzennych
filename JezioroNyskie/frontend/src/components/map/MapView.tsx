import 'maplibre-gl/dist/maplibre-gl.css';
import './map.css';
import maplibregl, { type ImageSource, type GeoJSONSource, type Map as MlMap } from 'maplibre-gl';
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { POI_COLORS, ZONE_COLORS, type ThemeName } from '../../theme';
import { withTheme } from '../../urls';
import {
  HATCH_IMAGE,
  IDS,
  POI_IMAGE,
  baseStyle,
  gravelLayer,
  marinaLayers,
  pinLayer,
  pinPaint,
  shorelineFilter,
  shorelineLayers,
  zoneLayers,
} from './layers';
import { makeHatch, poiLetters } from './patterns';
import type { Bbox, GeoJsonData, ImageLayerData, Visible } from './types';

export interface MapViewProps {
  theme: ThemeName;
  bbox: Bbox;
  zones?: GeoJsonData;
  bottomLayer?: ImageLayerData;
  uncertaintyLayer?: ImageLayerData;
  shorelines?: GeoJsonData;
  marinas?: GeoJsonData;
  /** Obrys żwirowni; warstwa powstaje dopiero z danymi (404 = brak warstwy). */
  gravel?: GeoJsonData;
  /** Atrybucja obrysu (z API), dopisywana do kontrolki atrybucji przez źródło warstwy. */
  gravelAttribution?: string;
  visible: Visible;
  basemap: 'osm' | 'orto';
  npp?: number;
  pin?: { lon: number; lat: number };
  /** Treść zakotwiczona nad pinezką (popup); mapa nie zna jej zawartości. */
  pinOverlay?: ReactNode;
  onMapClick: (lon: number, lat: number) => void;
}

const ATTRIBUTION = '© OpenStreetMap contributors · Copernicus Sentinel-2 · GUGiK';
const EMPTY = { type: 'FeatureCollection', features: [] } as const;

const btn: CSSProperties = {
  width: 44,
  height: 44,
  background: 'var(--panel)',
  color: 'var(--text)',
  border: '1px solid var(--border-strong)',
  borderRadius: 8,
  fontSize: 20,
  cursor: 'pointer',
};

const setVis = (map: MlMap, ids: string[], on: boolean) => {
  for (const id of ids) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
};

export function MapView(props: MapViewProps) {
  const { theme, visible, basemap } = props;
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const [ready, setReady] = useState(false);
  const propsRef = useRef(props);
  propsRef.current = props;
  const appliedTheme = useRef<ThemeName>(theme);
  const imageUrls = useRef<Record<string, string>>({});

  // Jedna mapa na cały czas życia komponentu; motyw i dane zmieniamy imperatywnie.
  useEffect(() => {
    const p = propsRef.current;
    const map = new maplibregl.Map({
      container: container.current!,
      style: baseStyle(p.basemap),
      attributionControl: false,
    });
    mapRef.current = map;
    const [w, s, e, n] = p.bbox;
    // Panel (desktop) i dolny arkusz (mobile) zasłaniają mapę — kadr jeziora liczymy bez nich.
    const desktop = window.innerWidth >= 768;
    const padding = desktop ? { top: 24, right: 24, bottom: 48, left: 400 } : { top: 80, right: 16, bottom: 310, left: 16 };
    map.fitBounds([[w, s], [e, n]], { padding, animate: false });
    map.addControl(new maplibregl.AttributionControl({ compact: false, customAttribution: ATTRIBUTION }), 'bottom-right');
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric', maxWidth: 100 }), 'bottom-left');
    map.on('click', (ev: { lngLat: { lng: number; lat: number } }) =>
      propsRef.current.onMapClick(ev.lngLat.lng, ev.lngLat.lat),
    );
    map.on('load', () => {
      const t = propsRef.current.theme;
      appliedTheme.current = t;
      map.addImage(HATCH_IMAGE, makeHatch(t));
      const letters = poiLetters(t);
      map.addImage(POI_IMAGE.marina, letters.P);
      map.addImage(POI_IMAGE.slipway, letters.S);
      for (const id of [IDS.zones, IDS.shorelines, IDS.marinas, IDS.pin]) {
        map.addSource(id, { type: 'geojson', data: EMPTY as never });
      }
      for (const l of zoneLayers(t)) map.addLayer(l, undefined);
      for (const l of shorelineLayers(propsRef.current.npp)) map.addLayer(l, undefined);
      for (const l of marinaLayers(t)) map.addLayer(l, undefined);
      map.addLayer(pinLayer(t), undefined);
      setReady(true);
    });
    return () => {
      map.remove();
      mapRef.current = null;
      imageUrls.current = {};
      setReady(false);
    };
  }, []);

  // Dane GeoJSON: tylko setData.
  const setData = (id: string, data: GeoJsonData | undefined) => {
    const src = mapRef.current?.getSource(id) as GeoJSONSource | undefined;
    if (src && data) src.setData(data as never);
  };
  useEffect(() => { if (ready) setData(IDS.zones, props.zones); }, [ready, props.zones]);
  useEffect(() => { if (ready) setData(IDS.shorelines, props.shorelines); }, [ready, props.shorelines]);
  useEffect(() => { if (ready) setData(IDS.marinas, props.marinas); }, [ready, props.marinas]);
  const { pin } = props;
  useEffect(() => {
    if (!ready) return;
    setData(IDS.pin, pin ? { type: 'Feature', geometry: { type: 'Point', coordinates: [pin.lon, pin.lat] }, properties: {} } as GeoJsonData : EMPTY);
  }, [ready, pin]);

  // Popup jako marker przy pinezce; klik w popup nie może przechodzić do mapy.
  const [overlayEl, setOverlayEl] = useState<HTMLElement | null>(null);
  const hasOverlay = !!props.pinOverlay;
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !pin || !hasOverlay) return;
    const element = document.createElement('div');
    element.className = 'pin-overlay';
    for (const ev of ['click', 'dblclick', 'mousedown', 'touchstart', 'pointerdown', 'wheel'])
      element.addEventListener(ev, (e) => e.stopPropagation());
    const marker = new maplibregl.Marker({ element, anchor: 'bottom', offset: [0, -12] })
      .setLngLat([pin.lon, pin.lat])
      .addTo(map);
    setOverlayEl(element);
    return () => {
      marker.remove();
      setOverlayEl(null);
    };
  }, [ready, pin, hasOverlay]);

  // Obrys żwirowni: źródło z atrybucją powstaje przy pierwszych danych, potem tylko setData.
  const { gravel, gravelAttribution } = props;
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !gravel) return;
    const src = map.getSource(IDS.gravel) as GeoJSONSource | undefined;
    if (src) {
      src.setData(gravel as never);
      return;
    }
    map.addSource(IDS.gravel, { type: 'geojson', data: gravel as never, attribution: gravelAttribution });
    map.addLayer(gravelLayer(propsRef.current.theme), IDS.marinas);
    setVis(map, [IDS.gravel], propsRef.current.visible.gravel);
  }, [ready, gravel, gravelAttribution]);

  // Linie poniżej NPP rysujemy przerywane.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.setFilter(IDS.shorelines, shorelineFilter(props.npp, false) as never);
    map.setFilter(IDS.shorelinesDashed, shorelineFilter(props.npp, true) as never);
  }, [ready, props.npp]);

  // Warstwy rastrowe z obrazów API; url zależy od motywu (?theme=).
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    for (const [id, data] of [[IDS.bottom, props.bottomLayer], [IDS.uncertainty, props.uncertaintyLayer]] as const) {
      if (!data) continue;
      const url = withTheme(data.url, theme);
      const spec = { url, coordinates: data.coordinates };
      const src = map.getSource(id) as ImageSource | undefined;
      if (!src) {
        map.addSource(id, { type: 'image', ...spec } as never);
        map.addLayer({ id, type: 'raster', source: id, paint: { 'raster-fade-duration': 0 } }, IDS.zonesSafe);
        setVis(map, [id], propsRef.current.visible[id]);
      } else if (imageUrls.current[id] !== url) {
        src.updateImage(spec as never);
      }
      imageUrls.current[id] = url;
    }
  }, [ready, theme, props.bottomLayer, props.uncertaintyLayer]);

  // Zmiana motywu: kolory, kreskowanie, znaczniki i pin; mapa zostaje ta sama.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || appliedTheme.current === theme) return;
    appliedTheme.current = theme;
    const c = ZONE_COLORS[theme];
    map.setPaintProperty(IDS.zonesSafe, 'fill-color', c.safe);
    map.setPaintProperty(IDS.zonesDanger, 'fill-color', c.danger);
    if (map.getLayer(IDS.gravel)) map.setPaintProperty(IDS.gravel, 'line-color', c.danger);
    map.updateImage(HATCH_IMAGE, makeHatch(theme));
    const letters = poiLetters(theme);
    map.updateImage(POI_IMAGE.marina, letters.P);
    map.updateImage(POI_IMAGE.slipway, letters.S);
    map.setPaintProperty(IDS.marinas, 'circle-color', POI_COLORS[theme].bg);
    map.setPaintProperty(IDS.marinas, 'circle-stroke-color', POI_COLORS[theme].fg);
    for (const [k, v] of Object.entries(pinPaint(theme))) map.setPaintProperty(IDS.pin, k, v);
  }, [ready, theme]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    setVis(map, [IDS.zonesSafe, IDS.zonesRisk, IDS.zonesDanger], visible.zones);
    setVis(map, [IDS.bottom], visible.bottom);
    setVis(map, [IDS.uncertainty], visible.uncertainty);
    setVis(map, [IDS.shorelines, IDS.shorelinesDashed], visible.shorelines);
    setVis(map, [IDS.marinas, IDS.marinasLetters], visible.marinas);
    setVis(map, [IDS.gravel], visible.gravel);
  }, [ready, visible.zones, visible.bottom, visible.uncertainty, visible.shorelines, visible.marinas, visible.gravel, props.bottomLayer, props.uncertaintyLayer, props.gravel]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    setVis(map, [IDS.osm], basemap === 'osm');
    setVis(map, [IDS.orto], basemap === 'orto');
  }, [ready, basemap]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={container} style={{ position: 'absolute', inset: 0 }} />
      <div style={{ position: 'absolute', top: 12, right: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <button type="button" aria-label="Przybliż" style={btn} onClick={() => mapRef.current?.zoomIn()}>+</button>
        <button type="button" aria-label="Oddal" style={btn} onClick={() => mapRef.current?.zoomOut()}>−</button>
        <button type="button" aria-label="Północ" style={btn} onClick={() => mapRef.current?.resetNorth()}>N</button>
      </div>
      {overlayEl && createPortal(props.pinOverlay, overlayEl)}
    </div>
  );
}
