import type { Meta } from '../api/client';
import { fmtDate, fmtM, fmtNum, fmtPct, plScenes } from '../format';
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

export type MethodValidation = {
  intro: string;
  checks: { name: string; comparedWith: string; result: string }[];
  bands: { label: string; range: string; dominant: string; note: string }[];
  bandsNote: string;
  lidarNote: string;
};

// Akapit „Dno głębokiej części i kalibracja”: liczby z /api/meta (pasmo < 192,9 m budżetu i pokrycie kalibracji).
export type MethodDeepBottom = { title: string; paragraphs: string[] };

export interface MethodVm {
  status: 'loading' | 'error' | 'ready';
  retry(): void;
  intro: string;
  steps: MethodStep[];
  chart?: MethodChart;
  tiles: MethodTile[];
  validation?: MethodValidation;
  deepBottom?: MethodDeepBottom;
  sources: MethodSource[];
  credit: string;
}

// Warianty ustalania poziomu (brief §6.3): kod -> opis i token koloru (CSS custom property).
const METHODS: Record<string, { label: string; color: string }> = {
  A: { label: 'kalibracja NMT (LiDAR)', color: 'var(--danger)' },
  R: { label: 'znany pomiar wodowskazowy', color: 'var(--risk)' },
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
    license: 'źródło: Wody Polskie / RZGW Wrocław (archiwum komunikatów z Wayback Machine)',
  },
  {
    name: 'Mapa i locja KŻ Nysa (Wiktor Wróblewski)',
    use: 'tabela pojemność ↔ rzędna (wariant B); obrys żwirowni i porównanie dna; współrzędne i rzędne przeszkód z podpisów zdjęć w locji (https://kz.nysa.pl/jezioro-nyskie/locja/)',
    license:
      'bezpłatna, niekomercyjna; dane mogą zawierać błędy; źródło: Wiktor Wróblewski, KŻ Nysa, aktualizacja 23.05.2023',
  },
  {
    // Warstwa pochodna mapy KŻ: warunki „UWAGA” (data/reference/KZ_ZRODLO_I_WARUNKI.md) przy każdym produkcie pochodnym (R10).
    name: 'Dno wg mapy KŻ (warstwa na mapie)',
    use: 'rzędne dna tam, gdzie jezioro nigdy nie odsłoniło dna („zawsze woda”): punkty rzędnych i poziomica 192,5 m mapy KŻ Nysa',
    license:
      'warunki „UWAGA” mapy KŻ: dane pozyskane sposobem amatorskim, mogą zawierać błędy; tylko do celów niekomercyjnych; całość ryzyka korzystania ponosi użytkownik; dno poniżej 192,5 m orientacyjne; źródło: Wiktor Wróblewski, KŻ Nysa, 23.05.2023',
  },
  {
    name: 'OpenStreetMap',
    use: 'podkład mapy, przystanie i slipy',
    license: 'ODbL 1.0 · © OpenStreetMap contributors',
  },
  {
    name: 'GUGiK',
    use: 'ortofotomapa; NMT i chmury punktów LiDAR terenu wokół zbiornika (wariant A, ocena dna)',
    license: 'otwarte dane PZGiK, z atrybucją',
  },
];

const PERIOD_LABELS: Record<string, string> = {
  all: 'cały okres',
  pre_flood: 'przed powodzią',
  post_flood: 'po powodzi',
};

// Obciążenie ze znakiem (+ dla dodatniego), polski przecinek i jednostka z fmtM.
const signedM = (x: number) => `${x > 0 ? '+' : ''}${fmtM(x)}`;

// Zakres błędu pasma: „1,04–1,34 m” (jedna jednostka na końcu); brak zakresu → „brak danych”.
const fmtRange = (r: number[] | null | undefined) =>
  r && r.length === 2 ? `${fmtNum(r[0], 2)}–${fmtNum(r[1], 2)}\u00a0m` : 'brak danych';

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
  const nR = byMethod.R ?? 0;
  const nA = byMethod.A ?? 0;
  // Brak dat: pomijamy opis okresu zamiast pokazywać „—–—”.
  const period =
    meta.first_scene_date && meta.last_scene_date
      ? `${fmtDate(meta.first_scene_date)}–${fmtDate(meta.last_scene_date)}`
      : '';

  const steps: MethodStep[] = [
    {
      n: '01',
      title: 'Satelita',
      text: `Sceny Copernicus Sentinel-2 (10 m) z niskim zachmurzeniem, z wielu lat i pór roku. W modelu: ${plScenes(meta.n_scenes)}${period ? ` z okresu ${period}` : ''}.`,
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
        `Granica maski to linia brzegowa. Poziom wody w dniu sceny przypisujemy jej z komunikatów RZGW (${plScenes(nB)}) ` +
        `oraz z krzywej powierzchnia–poziom dopasowanej do scen ze znanym poziomem (${plScenes(nC)}).` +
        (nR > 0 ? ` Pomiar wodowskazowy (wariant R): ${plScenes(nR)}.` : '') +
        (nA > 0 ? ` Kalibracja poziomu według NMT z LiDAR (wariant A): ${plScenes(nA)}.` : ''),
    },
    {
      n: '04',
      title: 'Model dna',
      text:
        'Dla każdego piksela wyznaczamy przedziały zalania: z jakich poziomów wody był pod wodą, a z jakich nad nią. ' +
        'Z nich wynika wysokość dna razem z niepewnością.' +
        ` Okres modelu: ${PERIOD_LABELS[meta.model_period] ?? meta.model_period}. ${meta.model_period_reason}`,
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
      sub: period ? `okres ${period}` : 'okres niedostępny',
    },
    {
      label: 'Zakres poziomów',
      value: `${fmtNum(meta.h_min_obs, 2)}–${fmtNum(meta.h_max_obs, 2)}`,
      sub: 'm n.p.m.; poza nim model ekstrapoluje',
    },
    Number.isFinite(num(acc.bottom_rmse_nmt))
      ? {
          label: 'RMSE dna',
          value: fmtM(num(acc.bottom_rmse_nmt)),
          // Bez przypisywania obciążenia układowi wysokości: hipoteza RZGW↔EVRF2007 ma przeciwny znak (raport §5.2).
          sub:
            'vs NMT LiDAR, bloki walidacyjne' +
            (Number.isFinite(num(acc.bottom_bias_nmt))
              ? `; obciążenie ${signedM(num(acc.bottom_bias_nmt))} na odsłoniętym brzegu (przyczyna nieustalona)`
              : '') +
            (Number.isFinite(num(acc.bottom_in_bounds_nmt))
              ? ` · przedział [z_min, z_max] zawiera teren w ${fmtPct(num(acc.bottom_in_bounds_nmt) * 100, 0)} pikseli — to nie jest przedział ufności`
              : ''),
        }
      : {
          label: 'RMSE dna',
          value: 'w przygotowaniu (porównanie z NMT LiDAR)',
          sub: 'błąd wysokości dna względem pomiarów kontrolnych',
        },
    Number.isFinite(num(acc.kz_rmse)) && Number.isFinite(num(acc.kz_bias))
      ? {
          label: 'Zgodność z mapą KŻ',
          value: `RMSE ${fmtM(num(acc.kz_rmse))}`,
          sub: `obciążenie ${signedM(num(acc.kz_bias))} · mapa KŻ to nie pomiar: model sprzed powodzi, rzędne od 192,5 m, bez żwirowni, komórka modelu 10 m pod punktem`,
        }
      : {
          label: 'Zgodność z mapą KŻ',
          value: 'w przygotowaniu (porównanie z mapą KŻ)',
          sub: 'mapa KŻ to nie pomiar: porównanie tylko w warunkach, w których mapa jest wiarygodna',
        },
  ];

  // Kafelek hold-out tylko, gdy API podało MAE (brak holdout.json → null).
  if (typeof acc.holdout_mae === 'number') {
    const n = acc.holdout_n_scenes;
    tiles.push({
      label: 'Hold-out roczny (MAE)',
      value: fmtM(acc.holdout_mae),
      sub: `model bez danego roku vs linie wody tego roku${typeof n === 'number' ? `, ${plScenes(n)}` : ''}`,
    });
  }

  const val = meta.validation;
  const validation: MethodValidation | undefined = val
    ? {
        intro:
          'Bez pomiarów w terenie zrobiliśmy pięć kontroli; trzy z nich używają danych niezależnych od satelity (LiDAR, mapa KŻ, tabela pojemności).',
        checks: val.checks.map((c) => ({ name: c.name, comparedWith: c.compared_with, result: c.result })),
        bands: val.bands.map((b) => ({
          label: b.band,
          // pasmo głębokie: bez zakresu modelu, ale z błędem interpolacji mapy KŻ (nie modelu), gdy jest
          range: b.range_m || !b.kz_loo ? fmtRange(b.range_m) : '—',
          dominant: b.dominant ?? (!b.range_m && b.kz_loo ? `błąd interpolacji KŻ: MAE ${fmtM(b.kz_loo.mae)}` : '—'),
          note: b.range_m ? '' : b.note,
        })),
        bandsNote: val.bands.some((b) => !b.range_m && b.kz_loo)
          ? 'Główne źródło = kontrola z największym błędem w paśmie. Wyjątek: w paśmie < 192,9 m model nie ma liczby, a komórka podaje błąd interpolacji mapy KŻ (mapa sprawdzona sama ze sobą), nie błąd modelu.'
          : 'Główne źródło = kontrola z największym błędem w paśmie.',
        lidarNote: val.lidar_note,
      }
    : undefined;

  const deepBottom = deepBottomOf(meta);

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
    validation,
    deepBottom,
    chart: { points, nodes, npp: meta.npp, maxPp: meta.max_pp, legend },
  };
}

/** Akapity o dnie z mapy KŻ i o kalibracji przedziałów; liczby tylko z meta (bez nich zdanie bez liczby). */
function deepBottomOf(meta: Meta): MethodDeepBottom {
  const loo = meta.validation?.bands.find((b) => b.kz_loo)?.kz_loo;
  const kz =
    'Tam, gdzie jezioro nigdy nie odsłoniło dna (strefa „zawsze woda”), satelita wie tylko, że dno leży niżej niż ' +
    'najniższy zaobserwowany poziom wody. W tej strefie dno bierzemy z amatorskiej mapy KŻ Nysa (2023): z punktów ' +
    'rzędnych i poziomicy 192,5 m, bez poziomicy 195,0 m, bo bez niej sprzeczności z obrazami satelitarnymi jest mniej więcej o połowę mniej. ' +
    (loo
      ? `Błąd interpolacji mapy KŻ (każdy punkt odłożony i odtworzony z pozostałych, n = ${fmtNum(loo.n, 0)}): MAE ${fmtM(loo.mae)}. ` +
        'To błąd mapy sprawdzonej samą sobą, a nie całkowity błąd dna: nie obejmuje błędu pomiaru ani układu wysokości mapy. '
      : 'Błąd tej mapy liczymy, sprawdzając ją samą ze sobą; to nie jest całkowity błąd dna. ') +
    'Gdzie mapa przeczy satelicie, pokazujemy tylko satelitę. Na mapie ten obszar pokazuje warstwa „Dno wg mapy KŻ”.';
  const acc = meta.accuracy;
  const before = acc.holdout_in_bounds;
  const after = acc.calibration_coverage;
  const cal =
    'Przedziały dna z satelity poszerzyliśmy na podstawie rocznego hold-outu' +
    (typeof after === 'number'
      ? `: obejmują teraz dno w ok. ${fmtPct(after * 100, 0)} sprawdzonych przypadków` +
        (typeof before === 'number' ? ` (przed poszerzeniem ${fmtPct(before * 100, 0)})` : '') +
        '; ten wynik wynika z konstrukcji, bo poszerzenie dopasowaliśmy na tych samych resztach hold-outu, na których je sprawdzamy'
      : '') +
    '. Poszerzenie zmierzyliśmy na pikselach z obiema granicami dna, a stosujemy też tam, gdzie znana jest tylko jedna ' +
    '(np. „zawsze woda”) — to ekstrapolacja. Skutek: więcej stref ryzykownych przy typowych poziomach wody.';
  return { title: 'Dno głębokiej części i kalibracja przedziałów', paragraphs: [kz, cal] };
}
