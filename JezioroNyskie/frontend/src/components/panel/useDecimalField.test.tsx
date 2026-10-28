import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useDecimalField } from './useDecimalField';

describe('useDecimalField', () => {
  it('NaN jako value nie zapętla renderowania', () => {
    const { result } = renderHook(() => useDecimalField({ value: NaN, digits: 1, isValid: () => true, onCommit: () => {} }));
    expect(result.current.invalid).toBe(false);
  });
});
