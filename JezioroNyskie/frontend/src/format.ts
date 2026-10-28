// Polskie formatowanie liczb, dat i odmian. Jednostka stoi przy liczbie po twardej spacji (U+00A0),
// żeby nie łamała się na końcu wiersza. Wartości nieskończone dają „—”, nigdy NaN/Infinity.
const NBSP = ' ';
const DASH = '—';

const nfCache = new Map<number, Intl.NumberFormat>();
function nf(digits: number): Intl.NumberFormat {
  let f = nfCache.get(digits);
  if (!f) {
    f = new Intl.NumberFormat('pl-PL', { minimumFractionDigits: digits, maximumFractionDigits: digits });
    nfCache.set(digits, f);
  }
  return f;
}

/** Zaokrągla do 0,05 (klucz zapytań); drugie zaokrąglenie usuwa szum zmiennoprzecinkowy. */
export function round05(x: number): number {
  return Math.round((Math.round(x / 0.05) * 0.05) * 100) / 100;
}

/** Tylko opcjonalny znak, cyfry i jeden separator dziesiętny (przecinek lub kropka). */
export function parsePlNumber(s: string): number | null {
  const t = s.trim();
  if (!/^[+-]?(\d+([.,]\d*)?|[.,]\d+)$/.test(t)) return null;
  const v = Number(t.replace(',', '.'));
  return Number.isFinite(v) ? v : null;
}

export function fmtNum(x: number, digits: number): string {
  return Number.isFinite(x) ? nf(digits).format(x) : DASH;
}

const withUnit = (x: number, digits: number, unit: string) =>
  Number.isFinite(x) ? `${nf(digits).format(x)}${NBSP}${unit}` : DASH;

export const fmtLevel = (h: number) => withUnit(h, 2, 'm n.p.m.');
export const fmtM = (x: number, digits = 2) => withUnit(x, digits, 'm');
export const fmtCapacity = (v: number) => withUnit(v, 1, 'mln m³');
export const fmtKm2 = (a: number) => withUnit(a, 1, 'km²');
export const fmtPct = (p: number) => (Number.isFinite(p) ? `${nf(0).format(p)}%` : DASH);
export const levelValueText = (h: number) => withUnit(h, 2, 'metra nad poziomem morza');

/** `RRRR-MM-DD…` → `DD.MM.RRRR` (bez parsowania strefą czasową). */
export function fmtDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : DASH;
}

export function fmtTime(d: Date): string {
  if (Number.isNaN(d.getTime())) return DASH;
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function plScenes(n: number): string {
  const last = n % 10;
  const tens = n % 100;
  const word =
    n === 1 ? 'scena' : last >= 2 && last <= 4 && !(tens >= 12 && tens <= 14) ? 'sceny' : 'scen';
  return `${n} ${word}`;
}
