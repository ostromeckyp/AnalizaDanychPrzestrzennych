import { describe, expect, it } from 'vitest';

// Wszystkie źródła jako tekst (bez uruchamiania modułów).
const sources = import.meta.glob('./**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

const entries = Object.entries(sources);
const isTest = (p: string) => /\.test\.tsx?$/.test(p);

const viewFiles = () =>
  entries.filter(([p]) => /^\.\/(components|pages)\//.test(p) && !isTest(p));

const allSourceFiles = () =>
  entries.filter(
    ([p]) => !isTest(p) && !p.startsWith('./test/') && p !== './api/schema.ts',
  );

describe('architektura warstw', () => {
  it('komponenty i strony nie dotykają warstwy zapytań ani fetch', () => {
    for (const [path, src] of viewFiles()) {
      expect(src, path).not.toMatch(/@tanstack\/react-query|from ['"].*\/api\/|\bfetch\(/);
    }
  });

  it('żadne liczby z makiet nie są zaszyte', () => {
    for (const [path, src] of allSourceFiles()) {
      for (const n of ['190,40', '195,00', '195,70', '189,00', '196,50', '62%']) {
        expect(src, path).not.toContain(n);
      }
    }
  });

  it('test widzi pliki źródłowe (glob działa)', () => {
    expect(allSourceFiles().length).toBeGreaterThan(0);
  });
});
