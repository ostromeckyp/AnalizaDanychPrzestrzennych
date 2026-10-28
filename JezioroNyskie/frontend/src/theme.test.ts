import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  BOTTOM_RAMP,
  DAM_COLOR,
  POI_COLORS,
  SHORE_COLOR,
  UNC_DOT,
  ZONE_COLORS,
  levelColor,
} from './theme';

// CSS czytany przez fs: import ?raw bywa pustym stubem przy `css: false` w Vitest.
const tokensCss = readFileSync(resolve(__dirname, 'styles/tokens.css'), 'utf8');

// Wyciąga wartości custom properties z bloku dla danego motywu.
function tokens(theme: 'light' | 'dark'): Record<string, string> {
  const block =
    theme === 'light'
      ? tokensCss.match(/:root\s*\{([^}]*)\}/)![1]
      : tokensCss.match(/prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{([^}]*)\}/)![1];
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/--([\w-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

describe('theme.ts a tokens.css', () => {
  for (const theme of ['light', 'dark'] as const) {
    it(`kolory stref zgodne z tokenami (${theme})`, () => {
      const t = tokens(theme);
      const z = ZONE_COLORS[theme];
      expect(z.safe).toBe(t['safe']);
      expect(z.risk).toBe(t['risk']);
      expect(z.hatch).toBe(t['hatch']);
      expect(z.danger).toBe(t['danger']);
    });
  }

  for (const theme of ['light', 'dark'] as const) {
    it(`skala dna i kropki niepewności zgodne z tokenami (${theme})`, () => {
      const t = tokens(theme);
      expect(BOTTOM_RAMP[theme]).toEqual([1, 2, 3, 4, 5].map((i) => t[`bottom-${i}`]));
      expect(UNC_DOT[theme]).toBe(t['unc-dot']);
    });
  }

  it('krycie stref wynosi 0,55', () => {
    expect(ZONE_COLORS.opacity).toBe(0.55);
  });
});

describe('theme.ts: dodatki mapy', () => {
  for (const theme of ['light', 'dark'] as const) {
    it(`brzeg, zapora i znaczniki zgodne z tokenami (${theme})`, () => {
      const t = tokens(theme);
      expect(SHORE_COLOR[theme]).toBe(t['shore']);
      expect(DAM_COLOR[theme]).toBe(t['dam']);
      expect(POI_COLORS[theme].fg).toBe(t['accent']);
      expect(POI_COLORS[theme].bg).toBe(t['panel']);
    });
  }

  it('levelColor: skala 190,0 -> 195,5 z obcięciem', () => {
    expect(levelColor(190)).toBe('#9cc9e4');
    expect(levelColor(150)).toBe('#9cc9e4');
    expect(levelColor(195.5)).toBe('#143f66');
    expect(levelColor(300)).toBe('#143f66');
    expect(levelColor(192.75)).toBe('#5884a5'); // środek skali
  });
});
