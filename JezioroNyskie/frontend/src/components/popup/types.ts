// Model widoku popupu punktu. Budowany w vm/usePointVm, komponent tylko go wyświetla.
export type PopupVariant = 'A' | 'B' | 'C' | 'D';
export type ZoneKey = 'safe' | 'risk' | 'danger';

export type PopupModel = {
  variant: PopupVariant;
  /** Nagłówek nad wartością: „Głębokość w tym miejscu” / „W tym miejscu”. */
  title: string;
  value: string;
  /** Zdanie pod wartością (szary tekst). */
  note?: string;
  /** Strefa z odpowiedzi API; brak dla wariantu D. */
  zone?: { key: ZoneKey; name: string; label: string };
  /** Ramka „Bez oceny strefy” (wariant D). */
  noZone?: string;
  /** Krótkie zastrzeżenie pod faktami (np. że zakres głębokości nie jest przedziałem ufności). */
  caveat?: string;
  /** `warning`: wiersz ostrzeżenia, rysowany poza listą jako `role="note"`. */
  rows: { term: string; desc: string; warning?: boolean }[];
};

/** Model popupu przeszkody z locji; budowany w vm/useHazardsVm, komponent tylko go wyświetla. */
export type HazardPopupModel = {
  title: string;
  /** „Rzędna wierzchołek: 193,7 m n.p.m.” */
  level: string;
  /** Położenie względem bieżącego lustra wody; brak, gdy poziom jeszcze nieznany. */
  relation?: { kind: 'under' | 'over' | 'at'; text: string };
  description: string;
  /** Uwaga z podpisu zdjęcia (mały, wyciszony tekst); brak, gdy pusta. */
  note?: string;
  sourceLabel: string;
  /** Tylko adres http(s); inny schemat daje brak linku. */
  sourceUrl?: string;
  disclaimer: string;
};
