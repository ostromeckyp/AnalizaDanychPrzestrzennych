import { useEffect, useState } from 'react';

/** Zwraca `value` dopiero po `ms` bez zmian; pierwsza wartość jest dostępna od razu. */
export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}
