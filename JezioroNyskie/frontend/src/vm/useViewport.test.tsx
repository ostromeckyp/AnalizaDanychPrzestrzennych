import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useViewport } from './useViewport';

function mockMedia(matches: boolean) {
  let cb: ((e: { matches: boolean }) => void) | undefined;
  const mq = {
    matches,
    addEventListener: vi.fn((_: string, f: typeof cb) => (cb = f)),
    removeEventListener: vi.fn(),
  };
  window.matchMedia = vi.fn(() => mq) as never;
  return { mq, fire: (m: boolean) => cb?.({ matches: m }) };
}

afterEach(() => {
  // @ts-expect-error sprzątanie atrapy
  delete window.matchMedia;
});

describe('useViewport', () => {
  it('queries min-width 768px and maps it to desktop/mobile', () => {
    mockMedia(false);
    const { result } = renderHook(() => useViewport());
    expect(window.matchMedia).toHaveBeenCalledWith('(min-width: 768px)');
    expect(result.current).toBe('mobile');
  });

  it('reacts to changes and unsubscribes', () => {
    const m = mockMedia(true);
    const { result, unmount } = renderHook(() => useViewport());
    expect(result.current).toBe('desktop');
    act(() => m.fire(false));
    expect(result.current).toBe('mobile');
    unmount();
    expect(m.mq.removeEventListener).toHaveBeenCalled();
  });

  it('defaults to desktop without matchMedia', () => {
    const { result } = renderHook(() => useViewport());
    expect(result.current).toBe('desktop');
  });
});
