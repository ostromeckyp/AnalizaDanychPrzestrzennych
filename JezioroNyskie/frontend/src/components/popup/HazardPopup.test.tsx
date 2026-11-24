import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { HazardPopup } from './HazardPopup';
import type { HazardPopupModel } from './types';

const model: HazardPopupModel = {
  title: 'Miedniki – żelbetowa rafa',
  level: 'Rzędna wierzchołek: 193,7 m n.p.m.',
  relation: { kind: 'under', text: 'Przy poziomie 194,20 m n.p.m.: pod wodą 1,55 m' },
  description: 'Betonowa rafa tuż pod lustrem.',
  note: 'Rzędna z podpisu zdjęcia.',
  sourceLabel: 'Źródło: Locja KŻ Nysa',
  sourceUrl: 'https://kz.nysa.pl/jezioro-nyskie/locja/',
  disclaimer: 'Położenie orientacyjne, nie znak nawigacyjny.',
};

describe('HazardPopup', () => {
  it('shows name, level, relation, description, note, source link and disclaimer', () => {
    render(<HazardPopup model={model} onClose={vi.fn()} />);
    const dlg = screen.getByRole('dialog', { name: 'Przeszkoda z locji' });
    expect(dlg).toHaveTextContent('Miedniki – żelbetowa rafa');
    expect(dlg).toHaveTextContent('Rzędna wierzchołek: 193,7 m n.p.m.');
    expect(dlg).toHaveTextContent('Przy poziomie 194,20 m n.p.m.: pod wodą 1,55 m');
    expect(dlg).toHaveTextContent('Betonowa rafa tuż pod lustrem.');
    expect(dlg).toHaveTextContent('Rzędna z podpisu zdjęcia.');
    const link = screen.getByRole('link', { name: 'Źródło: Locja KŻ Nysa' });
    expect(link).toHaveAttribute('href', 'https://kz.nysa.pl/jezioro-nyskie/locja/');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(screen.getByText('Położenie orientacyjne, nie znak nawigacyjny.')).toBeInTheDocument();
  });

  it('omits the note and the relation when absent', () => {
    render(<HazardPopup model={{ ...model, note: undefined, relation: undefined }} onClose={vi.fn()} />);
    expect(screen.queryByText('Rzędna z podpisu zdjęcia.')).not.toBeInTheDocument();
    expect(screen.queryByText(/pod wodą|nad wodą/)).not.toBeInTheDocument();
  });

  it('renders no link without a safe url', () => {
    render(<HazardPopup model={{ ...model, sourceUrl: undefined }} onClose={vi.fn()} />);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('Źródło: Locja KŻ Nysa')).toBeInTheDocument();
  });

  it('close button and Escape call onClose', async () => {
    const onClose = vi.fn();
    render(<HazardPopup model={model} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: 'Zamknij' }));
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
