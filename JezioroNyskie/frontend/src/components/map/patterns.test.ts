import { describe, expect, it } from 'vitest';
import { makeHatch, makeLetter } from './patterns';

const px = (img: { width: number; data: Uint8ClampedArray }, x: number, y: number) =>
  Array.from(img.data.slice((y * img.width + x) * 4, (y * img.width + x) * 4 + 4));

describe('makeHatch', () => {
  it('16×16 RGBA, kreska 45° w kolorze hatch, tło w kolorze risk', () => {
    const light = makeHatch('light');
    expect([light.width, light.height, light.data.length]).toEqual([16, 16, 1024]);
    expect(px(light, 0, 0)).toEqual([0x8a, 0x5a, 0x00, 255]);
    expect(px(light, 4, 0)).toEqual([0xf2, 0xb1, 0x34, 255]);
    expect(px(light, 8, 0)).toEqual([0x8a, 0x5a, 0x00, 255]);
  });
  it('ciemny motyw ma inną kreskę', () => {
    expect(px(makeHatch('dark'), 0, 0)).toEqual([0x6b, 0x43, 0x00, 255]);
  });
});

describe('makeLetter', () => {
  it('rysuje literę kolorem, reszta przezroczysta', () => {
    const p = makeLetter('P', '#ff0000');
    expect(p.data.length).toBe(p.width * p.height * 4);
    expect(px(p, 0, 0)[3]).toBe(255); // lewy górny róg słupka litery P
    expect(px(p, p.width - 1, p.height - 1)[3]).toBe(0);
  });
});
