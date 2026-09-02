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

  it('affiche la couleur réellement peinte, pas une valeur recopiée', () => {
    /**
     * **La liste recopiée mentait.** Elle annonçait `#C39B6E` pour une charte qui portait
     * `#E2A659`, et personne ne l'a vu : l'aplat à côté, lui, était juste. Une page dont
     * le rôle est d'être le test visuel du projet ne peut pas décrire une couleur
     * autrement que le reste de l'application la peint.
     *
     * Le test le vérifie en posant des valeurs que rien n'a codées en dur : si la page se
     * remet à recopier une constante, elles n'apparaîtront pas.
     */
    document.documentElement.style.setProperty('--bg', '#010203');
    document.documentElement.style.setProperty('--signal', '#0A0B0C');

    renderGallery();

    expect(screen.getByText('#010203')).toBeInTheDocument();
    expect(screen.getByText(/#0A0B0C/)).toBeInTheDocument();

    document.documentElement.style.removeProperty('--bg');
    document.documentElement.style.removeProperty('--signal');
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
