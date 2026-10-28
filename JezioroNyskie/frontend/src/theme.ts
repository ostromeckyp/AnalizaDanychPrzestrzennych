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
