import { validateStyleMin } from '@maplibre/maplibre-gl-style-spec';
import { describe, expect, it } from 'vitest';
import { IDS, baseStyle, marinaLayers, pinLayer, shorelineFilter, shorelineLayers, zoneLayers } from './layers';

describe('shorelineFilter', () => {
  it('bez npp: linia ciągła pokazuje wszystko, przerywana nic (filtry-wyrażenia)', () => {
    expect(shorelineFilter(undefined, false)).toBe(true);
    expect(shorelineFilter(undefined, true)).toBe(false);
  });
  it('z npp: podział wg h_t', () => {
    expect(shorelineFilter(195.9, true)).toEqual(['<', ['get', 'h_t'], 195.9]);
    expect(shorelineFilter(195.9, false)).toEqual(['>=', ['get', 'h_t'], 195.9]);
  });
});

describe('specyfikacje warstw przechodzą walidację stylu MapLibre', () => {
  for (const npp of [undefined, 195.91]) {
    it(`npp=${npp}`, () => {
      const style = baseStyle('osm');
      style.sources[IDS.zones] = { type: 'geojson', data: { type: 'FeatureCollection', features: [] } };
      style.sources[IDS.shorelines] = style.sources[IDS.zones];
      style.sources[IDS.marinas] = style.sources[IDS.zones];
      style.sources[IDS.pin] = style.sources[IDS.zones];
      style.layers.push(
        ...zoneLayers('light'),
        ...shorelineLayers(npp),
        ...marinaLayers('dark'),
        pinLayer('light'),
      );
      expect(validateStyleMin(style).map((e) => e.message)).toEqual([]);
    });
  }
});
