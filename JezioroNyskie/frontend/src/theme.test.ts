import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { BOTTOM_RAMP, UNC_DOT, ZONE_COLORS } from './theme';

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
