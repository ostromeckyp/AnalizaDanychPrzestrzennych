import { fmtDate, fmtNum, fmtPct } from '../format';
import { useMetaVm } from './useMetaVm';

export type MethodTile = { label: string; value: string; sub: string };
export type MethodStep = { n: string; title: string; text: string };
export type MethodSource = { name: string; use: string; license: string };
export type ChartPoint = { date: string; area: number; h: number; method: string; color: string };
export type ChartLegend = { code: string; label: string; color: string };
export type MethodChart = {
  points: ChartPoint[];
  nodes: { area: number; h: number }[];
  npp: number;
  maxPp: number;
  legend: ChartLegend[];
};

export interface MethodVm {
  status: 'loading' | 'error' | 'ready';
  retry(): void;
  intro: string;
  steps: MethodStep[];
  chart?: MethodChart;
  tiles: MethodTile[];
  sources: MethodSource[];
  credit: string;
}

// Warianty ustalania poziomu (brief §6.3): kod -> opis i token koloru (CSS custom property).
const METHODS: Record<string, { label: string; color: string }> = {
  A: { label: 'kalibracja NMT (LiDAR)', color: 'var(--danger)' },
  B: { label: 'komunikat RZGW', color: 'var(--accent)' },
  C: { label: 'krzywa powierzchnia–poziom', color: 'var(--safe)' },
  D: { label: 'mapa KŻ Nysa', color: 'var(--bottom-5)' },
};
const UNKNOWN_COLOR = 'var(--muted)';

const SOURCES: MethodSource[] = [
  {
    name: 'Copernicus Sentinel-2',
    use: 'obrazy wielospektralne 10 m',
    license: 'wolny i otwarty dostęp Copernicus, z atrybucją',
  },
  {
    name: 'Wody Polskie (RZGW)',
    use: 'komunikaty o pojemności zbiornika Nysa, przeliczane na poziom wody w dniu sceny',
    license: 'dane publiczne Wód Polskich, z podaniem źródła',
  },
  {
    name: 'Mapa Klubu Żeglarskiego Nysa (Wiktor Wróblewski)',
    use: 'mapa głębokości do porównania z modelem',
    license: 'użycie niekomercyjne, za zgodą autora',
  },
  {
    name: 'OpenStreetMap',
    use: 'podkład mapy, przystanie i slipy',
    license: 'ODbL 1.0 · © OpenStreetMap contributors',
  },
  {
    name: 'GUGiK',
    use: 'ortofotomapa, NMT terenu wokół zbiornika',
    license: 'otwarte dane PZGiK, z atrybucją',
  },
];

const num = (x: number | null | undefined) => (typeof x === 'number' ? x : NaN);

export function useMethodVm(): MethodVm {
  const { status, meta, retry } = useMetaVm();
  const base = {
    status,
    retry,
    intro:
      'Jezioro Nyskie to zbiornik retencyjny: jego poziom zmienia się o kilka metrów w ciągu roku. Każde obniżenie wody odsłania kolejny pas dna. Z wielu zdjęć satelitarnych przy różnych poziomach odtwarzamy kształt dna, a z niego to, gdzie zmieści się Twój kil.',
    sources: SOURCES,
    credit: 'Projekt na przedmiot Analiza Danych Przestrzennych, Politechnika Opolska · Paweł Ostromecki',
  };
  if (!meta) return { ...base, steps: [], tiles: [] };

  const byMethod = meta.n_scenes_by_method;
  const nB = byMethod.B ?? 0;
  const nC = byMethod.C ?? 0;
  const [from, to] = meta.period_dates;

  const steps: MethodStep[] = [
    {
      n: '01',
      title: 'Satelita',
      text: `Sceny Copernicus Sentinel-2 (10 m) z niskim zachmurzeniem, z wielu lat i pór roku. W modelu: ${fmtNum(meta.n_scenes, 0)} scen z okresu ${fmtDate(from)}–${fmtDate(to)}.`,
    },
    {
      n: '02',
      title: 'Woda / ląd',
      text: 'Indeks wodny (np. MNDWI) z progiem daje maskę wody dla każdej sceny.',
    },
    {
      n: '03',
      title: 'Linie brzegowe',
      text:
        `Granica maski to linia brzegowa. Poziom wody w dniu sceny przypisujemy jej z komunikatów RZGW (${fmtNum(nB, 0)} scen) ` +
        `oraz z krzywej powierzchnia–poziom dopasowanej do scen ze znanym poziomem (${fmtNum(nC, 0)} scen). ` +
        'Kalibracja poziomu według NMT z LiDAR jest w przygotowaniu.',
    },
    {
      n: '04',
      title: 'Model dna',
      text:
        'Dla każdego piksela wyznaczamy przedziały zalania: z jakich poziomów wody był pod wodą, a z jakich nad nią. ' +
        'Z nich wynika wysokość dna razem z niepewnością.',
    },
    {
      n: '05',
      title: 'Strefy',
      text: 'Głębokość = poziom − dno. Porównana z zanurzeniem i zapasem daje trzy strefy.',
    },
  ];

  const acc = meta.accuracy;
  const pct = (x: number | null) => fmtPct(num(x) * 100, 1);
  const tiles: MethodTile[] = [
    {
      label: 'Zgodność maski wody (OA)',
      value: pct(acc.rf_oa),
      sub: `ogólna trafność klasyfikatora wody na ${fmtNum(num(acc.n_labels), 0)} etykietach`,
    },
    {
      label: 'Zrównoważona trafność (BA)',
      value: pct(acc.rf_ba),
      sub: `sam próg Otsu: ${pct(acc.otsu_ba)}`,
    },
    {
      label: 'Liczba scen',
      value: fmtNum(meta.n_scenes, 0),
      sub: `okres ${fmtDate(from)}–${fmtDate(to)}`,
    },
    {
      label: 'Zakres poziomów',
      value: `${fmtNum(meta.h_min_obs, 2)}–${fmtNum(meta.h_max_obs, 2)}`,
      sub: 'm n.p.m.; poza nim model ekstrapoluje',
    },
    {
      label: 'RMSE dna',
      value: 'w przygotowaniu (porównanie z NMT LiDAR — plan 4)',
      sub: 'błąd wysokości dna względem pomiarów kontrolnych',
    },
  ];

  const al = meta.area_level;
  const points: ChartPoint[] = [];
  for (const p of al.points) {
    if (p.h_t == null || p.area_otsu_km2 == null) continue;
    const code = p.h_method ?? '?';
    points.push({
      date: p.date,
      area: p.area_otsu_km2,
      h: p.h_t,
      method: code,
      color: METHODS[code]?.color ?? UNKNOWN_COLOR,
    });
  }
  const nodes: { area: number; h: number }[] = [];
  al.nodes_area_km2.forEach((a, i) => {
    const h = al.nodes_h[i];
    if (a != null && h != null) nodes.push({ area: a, h });
  });
  nodes.sort((a, b) => a.area - b.area);
  const codes = [...new Set(points.map((p) => p.method))].sort();
  const legend = codes.map((code) => ({
    code,
    label: METHODS[code]?.label ?? code,
    color: METHODS[code]?.color ?? UNKNOWN_COLOR,
  }));

  return {
    ...base,
    steps,
    tiles,
    chart: { points, nodes, npp: meta.npp, maxPp: meta.max_pp, legend },
  };
}
