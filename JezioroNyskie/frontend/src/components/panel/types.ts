// Lokalne typy propsów panelu: komponenty nie importują src/api (nawet typów).
export type Range = readonly [number, number];
export type Preset = { label: string; draft: number };

export type SliderProps = {
  min: number;
  max: number;
  step: number;
  obsMin: number;
  obsMax: number;
  npp: number;
  maxPp: number;
};

export type LayerKey = 'zones' | 'bottom' | 'uncertainty' | 'shorelines' | 'marinas';
export type Basemap = 'map' | 'ortho';
export type LevelMode = 'level' | 'capacity';
