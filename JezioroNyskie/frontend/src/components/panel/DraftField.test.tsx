import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { meta } from '../../test/fixtures';
import { DraftField } from './DraftField';

function setup(value = 1.2) {
  const onChange = vi.fn();
  const utils = render(
    <DraftField
      value={value}
      presets={meta.draft_presets}
      presetsProvisional={meta.presets_provisional}
      limits={meta.limits}
      onChange={onChange}
    />,
  );
  const field = screen.getByLabelText('Zanurzenie jachtu');
  return { onChange, field, ...utils };
}

async function typeInto(field: HTMLElement, s: string) {
  await userEvent.clear(field);
  await userEvent.type(field, s);
}

describe('DraftField', () => {
  it.each(['1,25', '1.25', ' 1,25 '])('accepts %j on blur', async (s) => {
    const { onChange, field } = setup();
    await typeInto(field, s);
    await userEvent.tab();
    expect(onChange).toHaveBeenLastCalledWith(1.25);
  });

  it('accepts on Enter', async () => {
    const { onChange, field } = setup();
    await typeInto(field, '2,1{Enter}');
    expect(onChange).toHaveBeenLastCalledWith(2.1);
  });

  it.each(['abc', '5', '0,05', ''])('rejects %j with hint, aria-invalid and no onChange', async (s) => {
    const { onChange, field } = setup();
    await userEvent.clear(field);
    if (s) await userEvent.type(field, s);
    await userEvent.tab();
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText('Podaj wartość od 0,10 do 3,00 m')).toBeInTheDocument();
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(field.getAttribute('aria-describedby')).toBe(screen.getByText(/Podaj wartość/).id);
    expect(field).toHaveValue(s);
  });

  it('keeps typed text after invalid input, then accepts a correction', async () => {
    const { onChange, field } = setup();
    await typeInto(field, '5');
    await userEvent.tab();
    expect(field).toHaveValue('5');
    await typeInto(field, '1,5');
    await userEvent.tab();
    expect(onChange).toHaveBeenCalledWith(1.5);
    expect(field).not.toHaveAttribute('aria-invalid');
  });

  it('steps by 0.05 and clamps to limits', async () => {
    const { onChange } = setup(1.2);
    await userEvent.click(screen.getByRole('button', { name: /Zwiększ zanurzenie/ }));
    expect(onChange).toHaveBeenLastCalledWith(1.25);
    await userEvent.click(screen.getByRole('button', { name: /Zmniejsz zanurzenie/ }));
    expect(onChange).toHaveBeenLastCalledWith(1.15);
  });

  it('clamps at the upper and lower limit', async () => {
    const hi = setup(3.0);
    await userEvent.click(screen.getByRole('button', { name: /Zwiększ zanurzenie/ }));
    expect(hi.onChange).toHaveBeenLastCalledWith(3);
    hi.unmount();
    const lo = setup(0.1);
    await userEvent.click(screen.getByRole('button', { name: /Zmniejsz zanurzenie/ }));
    expect(lo.onChange).toHaveBeenLastCalledWith(0.1);
  });

  it('preset chip is pressed when value matches, Własny otherwise', () => {
    const { rerender, onChange } = setup(0.9);
    expect(screen.getByRole('button', { name: /Omega/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Własny/ })).toHaveAttribute('aria-pressed', 'false');
    rerender(<DraftField value={1.3} presets={meta.draft_presets} limits={meta.limits} onChange={onChange} />);
    expect(screen.getByRole('button', { name: /Omega/ })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: /Własny/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('matches a preset despite float noise', () => {
    setup(0.9000000001);
    expect(screen.getByRole('button', { name: /Omega/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('clicking a preset calls onChange with its draft', async () => {
    const { onChange } = setup();
    await userEvent.click(screen.getByRole('button', { name: /Sasanka 660 miecz w dole/ }));
    expect(onChange).toHaveBeenCalledWith(1.25);
  });

  it('Własny focuses the field', async () => {
    const { field } = setup();
    await userEvent.click(screen.getByRole('button', { name: /Własny/ }));
    expect(field).toHaveFocus();
  });

  it('shows the provisional note', () => {
    setup();
    expect(screen.getByText('wartości robocze')).toBeInTheDocument();
  });

  it('resyncs text when value changes externally', async () => {
    function Wrapper() {
      const [v, setV] = useState(1.2);
      return (
        <>
          <DraftField value={v} presets={meta.draft_presets} limits={meta.limits} onChange={setV} />
          <button onClick={() => setV(2)}>ext</button>
        </>
      );
    }
    render(<Wrapper />);
    const field = screen.getByLabelText('Zanurzenie jachtu');
    await typeInto(field, 'abc');
    await userEvent.tab();
    await userEvent.click(screen.getByText('ext'));
    expect(field).toHaveValue('2,00');
    expect(field).not.toHaveAttribute('aria-invalid');
  });
});
