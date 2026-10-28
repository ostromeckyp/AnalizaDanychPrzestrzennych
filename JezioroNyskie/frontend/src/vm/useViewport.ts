import { useEffect, useState } from 'react';

const QUERY = '(min-width: 768px)';

// Układ desktop od 768 px; bez matchMedia (np. jsdom) przyjmujemy desktop.
export function useViewport(): 'desktop' | 'mobile' {
  const [desktop, setDesktop] = useState(() => window.matchMedia?.(QUERY).matches ?? true);
  useEffect(() => {
    const mq = window.matchMedia?.(QUERY);
    if (!mq) return;
    setDesktop(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setDesktop(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return desktop ? 'desktop' : 'mobile';
}
