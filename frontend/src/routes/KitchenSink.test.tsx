import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import { KitchenSink } from './KitchenSink';

describe('KitchenSink', () => {
  it('présente les quatre signaux de la charte', () => {
    render(
      <MemoryRouter>
        <KitchenSink />
      </MemoryRouter>,
    );

    for (const name of ['Signal', 'Effort', 'Charge', 'Récup']) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }
  });

  it('expose les trois surfaces et leurs valeurs', () => {
    render(
      <MemoryRouter>
        <KitchenSink />
      </MemoryRouter>,
    );

    expect(screen.getByText('#0B0F16')).toBeInTheDocument();
    expect(screen.getByText('#131A24')).toBeInTheDocument();
    expect(screen.getByText('#18212D')).toBeInTheDocument();
  });
});
