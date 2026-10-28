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
  /** `warning`: wiersz ostrzeżenia, rysowany poza listą jako `role="note"`. */
  rows: { term: string; desc: string; warning?: boolean }[];
};
