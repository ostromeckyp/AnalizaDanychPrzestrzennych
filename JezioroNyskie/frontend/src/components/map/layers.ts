import type { LayerSpecification, StyleSpecification } from 'maplibre-gl';
import { LEVEL_SCALE, POI_COLORS, UNC_DOT, ZONE_COLORS, type ThemeName } from '../../theme';

// Stałe nazwy źródeł i warstw (kontrakt z testami i resztą UI).
export const IDS = {
  osm: 'basemap-osm',
  orto: 'basemap-orto',
  bottom: 'bottom',
  uncertainty: 'uncertainty',
  zones: 'zones',
  zonesSafe: 'zones-safe',
  zonesRisk: 'zones-risk',
  zonesDanger: 'zones-danger',
  shorelines: 'shorelines',
  shorelinesDashed: 'shorelines-dashed',
  marinas: 'marinas',
  marinasLetters: 'marinas-letters',
  gravel: 'gravel',
  pin: 'pin',
} as const;

export const HATCH_IMAGE = 'risk-hatch';
export const POI_IMAGE = { marina: 'poi-P', slipway: 'poi-S' } as const;

const ORTO_TILES =
  'https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution' +
  '?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&CRS=EPSG:3857&BBOX={bbox-epsg-3857}' +
  '&WIDTH=256&HEIGHT=256&FORMAT=image/jpeg&LAYERS=Raster&STYLES=';

export function baseStyle(basemap: 'osm' | 'orto'): StyleSpecification {
  const vis = (b: 'osm' | 'orto') => ({ visibility: basemap === b ? 'visible' : 'none' }) as const;
  return {
    version: 8,
    sources: {
      [IDS.osm]: {
        type: 'raster',
        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
        tileSize: 256,
        maxzoom: 19,
      },
      [IDS.orto]: { type: 'raster', tiles: [ORTO_TILES], tileSize: 256 },
    },
    layers: [
      { id: IDS.osm, type: 'raster', source: IDS.osm, layout: vis('osm') },
      { id: IDS.orto, type: 'raster', source: IDS.orto, layout: vis('orto') },
    ],
  };
}

export const zoneLayers = (theme: ThemeName): LayerSpecification[] => {
  const c = ZONE_COLORS[theme];
  const fill = (id: string, zone: string, paint: Record<string, unknown>): LayerSpecification =>
    ({
      id,
      type: 'fill',
      source: IDS.zones,
      filter: ['==', ['get', 'zone'], zone],
      paint: { 'fill-opacity': ZONE_COLORS.opacity, ...paint },
    }) as LayerSpecification;
  return [
    fill(IDS.zonesSafe, 'safe', { 'fill-color': c.safe }),
    fill(IDS.zonesRisk, 'risk', { 'fill-pattern': HATCH_IMAGE }),
    fill(IDS.zonesDanger, 'danger', { 'fill-color': c.danger }),
  ];
};

// Dasharray nie jest sterowalne danymi, więc dwie warstwy z filtrami (poniżej / od NPP).
export const shorelineLayers = (npp: number | undefined): LayerSpecification[] => {
  const color = ['interpolate', ['linear'], ['get', 'h_t'], LEVEL_SCALE.h0, LEVEL_SCALE.c0, LEVEL_SCALE.h1, LEVEL_SCALE.c1];
  const line = (id: string, dashed: boolean): LayerSpecification =>
    ({
      id,
      type: 'line',
      source: IDS.shorelines,
      filter: shorelineFilter(npp, dashed),
      paint: { 'line-color': color, 'line-width': 2, ...(dashed ? { 'line-dasharray': [2, 2] } : {}) },
    }) as LayerSpecification;
  return [line(IDS.shorelines, false), line(IDS.shorelinesDashed, true)];
};

export const shorelineFilter = (npp: number | undefined, dashed: boolean) =>
  npp === undefined
    ? !dashed // literał logiczny to poprawny filtr-wyrażenie (['==', 1, 0] MapLibre czyta jako filtr legacy i odrzuca)
    : [dashed ? '<' : '>=', ['get', 'h_t'], npp];

// Obrys żwirowni: przerywana linia w kolorze „danger" (MapLibre nie czyta zmiennych CSS, więc kolor z theme.ts).
export const gravelLayer = (theme: ThemeName): LayerSpecification => ({
  id: IDS.gravel,
  type: 'line',
  source: IDS.gravel,
  paint: { 'line-color': ZONE_COLORS[theme].danger, 'line-width': 2.5, 'line-dasharray': [3, 2] },
});

export const marinaLayers = (theme: ThemeName): LayerSpecification[] => [
  {
    id: IDS.marinas,
    type: 'circle',
    source: IDS.marinas,
    paint: {
      'circle-radius': 12,
      'circle-color': POI_COLORS[theme].bg,
      'circle-stroke-color': POI_COLORS[theme].fg,
      'circle-stroke-width': 2.5,
    },
  },
  {
    id: IDS.marinasLetters,
    type: 'symbol',
    source: IDS.marinas,
    layout: {
      'icon-image': ['match', ['get', 'kind'], 'slipway', POI_IMAGE.slipway, POI_IMAGE.marina],
      'icon-allow-overlap': true,
    },
  },
];

export const pinLayer = (theme: ThemeName): LayerSpecification => ({
  id: IDS.pin,
  type: 'circle',
  source: IDS.pin,
  paint: pinPaint(theme),
});

export function pinPaint(theme: ThemeName) {
  const other: ThemeName = theme === 'light' ? 'dark' : 'light';
  return {
    'circle-radius': 7,
    'circle-color': UNC_DOT[theme],
    'circle-stroke-color': UNC_DOT[other], // halo kontrastowe względem punktu
    'circle-stroke-width': 3,
  };
}
