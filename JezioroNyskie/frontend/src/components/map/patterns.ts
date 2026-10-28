import { POI_COLORS, ZONE_COLORS, type ThemeName } from '../../theme';

export type PixelImage = { width: number; height: number; data: Uint8ClampedArray };

const rgb = (hex: string): [number, number, number] => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16),
];

// Kreskowanie strefy ryzyka budowane wprost na pikselach (bez canvas: działa też w jsdom).
// Okres 8 px dzieli 16, więc wzór zszywa się bez szwów.
export function makeHatch(theme: ThemeName): PixelImage {
  const size = 16;
  const { risk, hatch } = ZONE_COLORS[theme];
  const [bg, fg] = [rgb(risk), rgb(hatch)];
  const data = new Uint8ClampedArray(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const c = (x + y) % 8 < 2 ? fg : bg;
      data.set([c[0], c[1], c[2], 255], (y * size + x) * 4);
    }
  }
  return { width: size, height: size, data };
}

// Bitmapy 5×7 liter znaczników: P = przystań, S = slip.
const GLYPHS: Record<'P' | 'S', string[]> = {
  P: ['1111.', '1...1', '1...1', '1111.', '1....', '1....', '1....'],
  S: ['.1111', '1....', '1....', '.111.', '....1', '....1', '1111.'],
};

export function makeLetter(letter: 'P' | 'S', color: string): PixelImage {
  const scale = 2;
  const rows = GLYPHS[letter];
  const width = 5 * scale;
  const height = 7 * scale;
  const [r, g, b] = rgb(color);
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (rows[Math.floor(y / scale)][Math.floor(x / scale)] === '1') data.set([r, g, b, 255], (y * width + x) * 4);
    }
  }
  return { width, height, data };
}

export const poiLetters = (theme: ThemeName) => ({
  P: makeLetter('P', POI_COLORS[theme].fg),
  S: makeLetter('S', POI_COLORS[theme].fg),
});
