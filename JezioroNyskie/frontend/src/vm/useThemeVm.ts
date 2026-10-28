import { useEffect, useState } from 'react';

const QUERY = '(prefers-color-scheme: dark)';

// Motyw z systemu; reaguje na zmianę w trakcie pracy.
export function useThemeVm(): 'light' | 'dark' {
  const [dark, setDark] = useState(() => window.matchMedia?.(QUERY).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(QUERY);
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return dark ? 'dark' : 'light';
}
