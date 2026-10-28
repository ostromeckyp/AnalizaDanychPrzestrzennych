import { useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, type Marinas, type Meta, type Zones } from '../api/client';
import type { ParameterPanelProps } from '../components/panel/ParameterPanel';
import type { LayerKey, LevelMode } from '../components/panel/types';
import { round05 } from '../format';
import { useCapacityVm } from './useCapacityVm';
import { useCurrentLevelVm } from './useCurrentLevelVm';
import { useMarinasVm } from './useMarinasVm';
import { useMetaVm } from './useMetaVm';
import { usePointVm, type PointVm } from './usePointVm';
import { useThemeVm } from './useThemeVm';
import { useZonesVm, type ZonesStatus } from './useZonesVm';

type Basemap = 'osm' | 'orto';
const DEFAULT_VISIBLE: Record<LayerKey, boolean> = {
  zones: true,
  bottom: false,
  uncertainty: false,
  shorelines: false,
  marinas: true,
};

export interface MapPageVm {
  theme: 'light' | 'dark';
  /** Meta jeszcze się nie wczytała albo padła. */
  meta: { status: 'loading' | 'error' | 'ready'; retry(): void; data?: Meta };
  /** Gotowe propsy panelu (dopiero po wczytaniu meta). */
  panel?: ParameterPanelProps;
  legend?: { draft: number; margin: number; summary?: string };
  map: {
    zones?: Zones;
    marinas?: Marinas;
    bottomLayer?: { url: string; coordinates: [number, number][] };
    uncertaintyLayer?: { url: string; coordinates: [number, number][] };
    visible: Record<LayerKey, boolean>;
    basemap: Basemap;
    pin?: { lon: number; lat: number };
  };
  zonesState: {
    status: ZonesStatus;
    lastOkAt?: Date;
    lastOk?: { draft: number; h: number };
    isRetrying: boolean;
    retry(): void;
  };
  /** Zanurzenie wpisane przez użytkownika (także jeszcze nieprzeliczone). */
  draft: number;
  point: PointVm;
  onMapClick(lon: number, lat: number): void;
  closePopup(): void;
}

/** `?h=` w notacji z kropką; śmieci ignorujemy. */
function parseUrlH(raw: string | null): number | undefined {
  if (raw === null || !/^\s*[+-]?\d+(\.\d+)?\s*$/.test(raw)) return undefined;
  const v = parseFloat(raw);
  return Number.isFinite(v) ? v : undefined;
}

const clampH = (h: number, min: number, max: number) => Math.min(max, Math.max(min, round05(h)));

export function useMapPageVm(): MapPageVm {
  const theme = useThemeVm();
  const [search] = useSearchParams();
  const metaVm = useMetaVm();
  const { meta, slider } = metaVm;
  const level = useCurrentLevelVm();
  const { marinas } = useMarinasVm();

  const [hUser, setHUser] = useState<number>();
  const [draftUser, setDraftUser] = useState<number>();
  const [marginUser, setMarginUser] = useState<number>();
  const [mode, setMode] = useState<LevelMode>('level');
  const [capacityValue, setCapacityValue] = useState<number>();
  const [userVisible, setUserVisible] = useState(DEFAULT_VISIBLE);
  const [basemap, setBasemap] = useState<Basemap>('osm');
  const [pin, setPin] = useState<{ lon: number; lat: number }>();

  // Poziom początkowy ustalamy raz: ?h= > bieżący poziom > domyślny z meta. Czekamy na bieżący poziom
  // tylko do czasu, aż jego zapytanie się rozstrzygnie (sukces lub błąd).
  const initialH = useRef<number>();
  if (initialH.current === undefined && meta && slider && level.status !== 'loading') {
    const raw = parseUrlH(search.get('h')) ?? level.level?.h ?? meta.defaults.h;
    initialH.current = clampH(raw, slider.min, slider.max);
  }
  const h = hUser ?? initialH.current ?? NaN;
  const draft = draftUser ?? meta?.defaults.draft ?? NaN;
  const margin = marginUser ?? meta?.defaults.margin ?? NaN;
  const params = { h, draft, margin };

  const zonesVm = useZonesVm(params);
  const capacity = useCapacityVm(mode, mode === 'level' ? h : (capacityValue ?? NaN));
  const point = usePointVm(pin, params);

  // Tryb pojemności: wynik przeliczenia ustawia poziom.
  const hFromCapacity = capacity.hFromCapacity;
  const lastApplied = useRef<number>();
  if (mode === 'capacity' && slider && hFromCapacity !== undefined && lastApplied.current !== hFromCapacity) {
    lastApplied.current = hFromCapacity;
    setHUser(clampH(hFromCapacity, slider.min, slider.max));
  }

  // Ostrzeżenie z API wymusza warstwę niepewności, ale nie przestawia wyboru użytkownika.
  const forceUnc = zonesVm.warnings.length > 0;
  const visible = { ...userVisible, uncertainty: userVisible.uncertainty || forceUnc };

  const layer = (l: { url: string; coordinates: [number, number][] } | undefined) =>
    l ? { url: api.layerUrl(l.url, theme), coordinates: l.coordinates } : undefined;

  const panel: ParameterPanelProps | undefined =
    meta && slider && Number.isFinite(h)
      ? {
          draft: {
            value: draft,
            presets: metaVm.presets ?? [],
            presetsProvisional: meta.presets_provisional,
            limits: { draft: meta.limits.draft },
            onChange: setDraftUser,
          },
          level: {
            mode,
            h,
            slider,
            level: { capacityAtLevel: capacity.capacityAtLevel, aboveNpp: capacity.aboveNpp },
            capacity: { value: capacityValue ?? 0, hFromCapacity, inTable: capacity.inTable },
            currentLevel: level.level && { label: level.level.label, note: level.level.note },
            warnings: zonesVm.warnings,
            onModeChange: (m) => {
              if (m === 'capacity' && capacityValue === undefined && capacity.capacityAtLevel !== undefined) {
                setCapacityValue(Math.round(capacity.capacityAtLevel * 10) / 10);
              }
              setMode(m);
            },
            onLevelChange: (x) => setHUser(clampH(x, slider.min, slider.max)),
            onCapacityChange: setCapacityValue,
          },
          layers: {
            visible,
            basemap: basemap === 'osm' ? 'map' : 'ortho',
            variant: 'list',
            onToggle: (k) => setUserVisible((v) => ({ ...v, [k]: !visible[k] })),
            onBasemap: (b) => setBasemap(b === 'map' ? 'osm' : 'orto'),
          },
          margin: {
            value: margin,
            limits: { margin: meta.limits.margin },
            defaultValue: meta.defaults.margin,
            onChange: setMarginUser,
          },
        }
      : undefined;

  const lastParams = zonesVm.lastOkParams;
  return {
    theme,
    meta: { status: metaVm.status, retry: metaVm.retry, data: meta },
    panel,
    legend: Number.isFinite(draft) ? { draft, margin, summary: zonesVm.summary } : undefined,
    map: {
      zones: zonesVm.zones,
      marinas,
      bottomLayer: layer(meta?.layers.bottom),
      uncertaintyLayer: layer(meta?.layers.uncertainty),
      visible,
      basemap,
      pin,
    },
    zonesState: {
      status: zonesVm.status,
      lastOkAt: zonesVm.lastOkAt,
      lastOk: lastParams && { draft: lastParams.draft, h: lastParams.h },
      isRetrying: zonesVm.isRetrying,
      retry: zonesVm.retry,
    },
    draft,
    point,
    onMapClick: (lon, lat) => setPin({ lon, lat }),
    closePopup: () => setPin(undefined),
  };
}
