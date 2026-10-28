// Lokalne typy widoku historii: komponenty nie importują src/api (nawet typów).
export type SceneRow = {
  date: string;
  dateLabel: string;
  /** Poziom jako liczba (wykres, link) oraz sformatowany tekst. */
  h: number;
  level: string;
  area: string;
  /** „Sentinel-2 · zachm. 1,3%” lub samo „Sentinel-2”, gdy brak zachmurzenia. */
  source: string;
  color: string;
  dashed: boolean;
  /** Link do mapy z tym poziomem: `/?h=194.2`. */
  mapHref: string;
  /** Stan pobierania linii nałożonej na mapę. */
  overlayStatus?: 'loading' | 'error';
};

export type YearFilter = number | 'all';
