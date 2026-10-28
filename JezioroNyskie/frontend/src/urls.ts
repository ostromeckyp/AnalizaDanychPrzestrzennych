// Czysty helper wspólny dla klienta API i widoku mapy (widok nie importuje src/api).
export const withTheme = (url: string, theme: 'light' | 'dark') =>
  `${url}${url.includes('?') ? '&' : '?'}theme=${theme}`;
