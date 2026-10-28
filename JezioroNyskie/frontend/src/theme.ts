// Jedno źródło dla MapLibre: kolory mapy dla obu motywów (brief §16.3, makiety).
// MapLibre nie czyta zmiennych CSS, więc wartości są tu jawnie; ten sam zestaw jest
// w src/styles/tokens.css dla UI, a theme.test.ts pilnuje zgodności stref i skali dna.
// Pośrednie stopnie skali dna (b2–b4) pochodzą z makiet docs/design/*.dc.html.

export type ThemeName = 'light' | 'dark';

type ZonePalette = { safe: string; risk: string; hatch: string; danger: string };

export const ZONE_COLORS: Record<ThemeName, ZonePalette> & { opacity: number } = {
  light: { safe: '#2ba6a0', risk: '#f2b134', hatch: '#8a5a00', danger: '#8e1b4f' },
  dark: { safe: '#34b8b0', risk: '#f2b134', hatch: '#6b4300', danger: '#d0508a' },
  opacity: 0.55,
};

export const BOTTOM_RAMP: Record<ThemeName, readonly [string, string, string, string, string]> = {
  light: ['#c4dde9', '#98c3d9', '#6aa4c4', '#3f80aa', '#215c86'],
  dark: ['#2a4c5e', '#24546e', '#1e5f82', '#1a6a97', '#1675ab'],
};

export const UNC_DOT: Record<ThemeName, string> = {
  light: '#0e2433',
  dark: '#e6eef3',
};

// Brzeg, zapora i znaczniki POI (tokeny --shore, --dam, --accent, --panel).
export const SHORE_COLOR: Record<ThemeName, string> = { light: '#5f889c', dark: '#5f889c' };
export const DAM_COLOR: Record<ThemeName, string> = { light: '#3a4a55', dark: '#3a4a55' };
export const POI_COLORS: Record<ThemeName, { fg: string; bg: string }> = {
  light: { fg: '#1c5d8c', bg: '#ffffff' },
  dark: { fg: '#6fb3e0', bg: '#12191f' },
};

// Skala linii brzegowych wg poziomu wody (m n.p.m.): jasny błękit -> granat, z obcięciem.
export const LEVEL_SCALE = { h0: 190, c0: '#9cc9e4', h1: 195.5, c1: '#143f66' } as const;

export function levelColor(h: number): string {
  const { h0, c0, h1, c1 } = LEVEL_SCALE;
  const t = Math.min(1, Math.max(0, (h - h0) / (h1 - h0)));
  const ch = (hex: string, i: number) => parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
  return (
    '#' +
    [0, 1, 2]
      .map((i) => Math.round(ch(c0, i) + (ch(c1, i) - ch(c0, i)) * t).toString(16).padStart(2, '0'))
      .join('')
  );
}
