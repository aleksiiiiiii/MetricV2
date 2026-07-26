import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import { Toaster } from '@/components/ui';

import { KitchenSink } from './KitchenSink';

function renderGallery() {
  return render(
    <MemoryRouter>
      <Toaster>
        <KitchenSink />
      </Toaster>
    </MemoryRouter>,
  );
}

describe('galerie de composants', () => {
  it('présente les quatre signaux de la charte', () => {
    renderGallery();

    for (const name of ['Signal', 'Effort', 'Charge', 'Récup']) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }
  });

  it('expose les trois surfaces et leurs valeurs', () => {
    renderGallery();

    expect(screen.getByText('#0B0F16')).toBeInTheDocument();
    expect(screen.getByText('#131A24')).toBeInTheDocument();
    expect(screen.getByText('#18212D')).toBeInTheDocument();
  });

  it('rend chaque composant de la bibliothèque', () => {
    renderGallery();

    // Un rendu qui échoue ferait tomber toute la page : ces sondes suffisent à le voir.
    expect(screen.getByRole('grid', { name: /assiduité/i })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Allure, Charge, Sommeil' })).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Période' })).toBeInTheDocument();
  });
});
