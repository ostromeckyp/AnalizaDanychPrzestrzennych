import { useState } from 'react';
import { fmtNum, parsePlNumber } from '../../format';

type Options = {
  value: number;
  digits: number;
  /** Zwraca true, gdy liczba jest dopuszczalna. */
  isValid: (n: number) => boolean;
  onCommit: (n: number) => void;
};

/**
 * Pole liczbowe z przecinkiem: walidacja przy blur/Enter, błędny tekst zostaje do poprawienia,
 * a zmiana `value` z zewnątrz synchronizuje tekst (o ile różni się od wpisanego).
 */
export function useDecimalField({ value, digits, isValid, onCommit }: Options) {
  const [text, setText] = useState(() => fmtNum(value, digits));
  const [prev, setPrev] = useState(value);
  const [invalid, setInvalid] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Synchronizacja w trakcie renderu (wzorzec „derived state”), bez efektu.
  if (!Object.is(value, prev)) {
    setPrev(value);
    if (parsePlNumber(text) !== value) setText(fmtNum(value, digits));
    setInvalid(false);
    setDirty(false);
  }

  const reset = (v: number) => {
    setText(fmtNum(v, digits));
    setInvalid(false);
    setDirty(false);
  };

  const commit = () => {
    if (!dirty) return;
    const n = parsePlNumber(text);
    if (n === null || !isValid(n)) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setDirty(false);
    onCommit(n);
  };

  return {
    text,
    invalid,
    reset,
    commit,
    change: (s: string) => {
      setText(s);
      setDirty(true);
    },
  };
}
