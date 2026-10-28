// Lokalne typy propsów: komponenty nie importują src/api (nawet typów).
export type LngLat = [number, number];
export type Bbox = [number, number, number, number];
export type ImageLayerData = { url: string; coordinates: LngLat[] };
// Dowolny GeoJSON (FeatureCollection lub Feature) przekazany do źródła MapLibre.
export type GeoJsonData = { type: string };
export type Visible = {
  zones: boolean;
  bottom: boolean;
  uncertainty: boolean;
  shorelines: boolean;
  marinas: boolean;
  gravel: boolean;
};
