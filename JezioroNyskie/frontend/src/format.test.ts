import { describe, expect, it } from 'vitest';
import {
  fmtCapacity, fmtDate, fmtKm2, fmtLevel, fmtM, fmtNum, fmtPct, fmtTime,
  levelValueText, parsePlNumber, plScenes, round05,
} from './format';

const NB = ' ';

describe('parsePlNumber', () => {
  it.each([
    ['1,2', 1.2], ['1.2', 1.2], [' 1,25 ', 1.25], ['5', 5], ['-0,5', -0.5], ['+2', 2], ['.5', 0.5],
    ['abc', null], ['', null], ['   ', null], ['1,2,3', null], ['1.2.3', null], ['1,2.3', null],
    ['1e3', null], ['Infinity', null], ['NaN', null], ['0x10', null], ['1 2', null], ['--1', null],
  ])('parsePlNumber(%j)', (s, v) => expect(parsePlNumber(s as string)).toBe(v));
});

describe('round05', () => {
  it('zaokrągla do 0,05 z 2 miejscami', () => {
    expect(round05(195.2300001)).toBe(195.25);
    expect(round05(1.224)).toBe(1.2);
    expect(round05(0.3)).toBe(0.3);
    expect(round05(194.2)).toBe(194.2);
  });
});

describe('formatery', () => {
  it('liczby z jednostkami i twardą spacją', () => {
    expect(fmtLevel(195.2)).toBe(`195,20${NB}m n.p.m.`);
    expect(fmtM(1.2)).toBe(`1,20${NB}m`);
    expect(fmtM(1.234, 1)).toBe(`1,2${NB}m`);
    expect(fmtCapacity(45.62)).toBe(`45,6${NB}mln m³`);
    expect(fmtKm2(12.94)).toBe(`12,9${NB}km²`);
    expect(fmtPct(62)).toBe('62%');
    expect(fmtPct(81.62, 1)).toBe('81,6%');
    expect(levelValueText(195.2)).toBe(`195,20${NB}metra nad poziomem morza`);
  });
  it('fmtNum: przecinek dziesiętny, grupowanie od 5 cyfr', () => {
    expect(fmtNum(1234.5, 1)).toBe('1234,5');
    expect(fmtNum(12345.6, 1)).toBe(`12${NB}345,6`);
    expect(fmtNum(3, 2)).toBe('3,00');
  });
  it('wartości nieskończone to półpauza, nigdy NaN/Infinity', () => {
    for (const f of [fmtNum(NaN, 1), fmtLevel(Infinity), fmtM(-Infinity), fmtCapacity(NaN), fmtKm2(NaN), fmtPct(NaN), levelValueText(NaN)]) {
      expect(f).toBe('—');
    }
  });
  it('daty i godziny', () => {
    expect(fmtDate('2026-10-26')).toBe('26.10.2026');
    expect(fmtDate('2026-10-26T08:00:00Z')).toBe('26.10.2026');
    expect(fmtDate('śmieć')).toBe('—');
    expect(fmtTime(new Date(2026, 9, 26, 10, 42))).toBe('10:42');
    expect(fmtTime(new Date(2026, 9, 26, 7, 5))).toBe('07:05');
  });
  it('plScenes', () => {
    expect([1, 2, 3, 4, 5, 11, 12, 14, 21, 22, 25, 0].map(plScenes)).toEqual([
      '1 scena', '2 sceny', '3 sceny', '4 sceny', '5 scen', '11 scen', '12 scen', '14 scen',
      '21 scen', '22 sceny', '25 scen', '0 scen',
    ]);
  });
});
