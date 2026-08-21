/**
 * Les jauges disent-elles leur valeur ?
 *
 * Ce fichier existe à cause d'un défaut que **rien ne voyait**. `Progress` et `Bars`
 * posaient leur largeur avec `percent()`, qui rend « 56 % » — l'espace avant le signe est
 * la typographie française, et c'est ce qu'il faut dans une phrase. Posé en `style.width`,
 * c'est une valeur invalide que le navigateur jette sans rien dire : la barre retombait
 * sur sa largeur par défaut, **pleine**. Toutes les jauges de l'application se peignaient
 * donc à 100 %, y compris une semaine à zéro.
 *
 * Aucun test ne le voyait parce qu'ils regardaient tous le **texte** : « 2 / 3 » était
 * juste, le libellé était juste, le ton était juste. Il manquait un attribut, et personne
 * ne mesurait la barre. C'est le genre de défaut que `CLAUDE.md` annonce — sorti en
 * regardant la page, pas de la batterie — et celui-ci ne ressortira plus.
 */

import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Bars, Progress } from './index';

/** La barre remplie d'une jauge — celle dont la largeur porte la valeur. */
function fill(container: HTMLElement, position = 0): HTMLElement {
  const fills = container.querySelectorAll<HTMLElement>('[class*="fill"]');
  const found = fills[position];
  if (found === undefined) throw new Error('aucune barre trouvée');
  return found;
}

describe('Progress', () => {
  it('pose une largeur CSS valide, et non un pourcentage à lire', () => {
    const { container } = render(<Progress done={1400} total={2500} />);

    expect(fill(container).style.width).toBe('56%');
  });

  it('ne remplit rien à zéro', () => {
    // Une jauge pleine pour une valeur nulle est une valeur inventée à l'écran, et la
    // pire espèce : elle se lit comme un objectif atteint.
    const { container } = render(<Progress done={0} total={2500} />);

    expect(fill(container).style.width).toBe('0%');
  });

  it('ne déborde pas au-delà de la cible', () => {
    const { container } = render(<Progress done={3000} total={2500} />);

    expect(fill(container).style.width).toBe('100%');
  });

  it('ne divise pas par une cible nulle', () => {
    const { container } = render(<Progress done={0} total={0} />);

    expect(fill(container).style.width).toBe('0%');
  });
});

describe('Bars', () => {
  it('donne à chaque barre la largeur de sa part', () => {
    const { container } = render(
      <Bars
        rows={[
          { label: 'Course', ratio: 0.39, value: '46' },
          { label: 'Musculation', ratio: 0.51, value: '60' },
          { label: 'Repos', ratio: 0, value: '—' },
        ]}
      />,
    );

    expect(fill(container, 0).style.width).toBe('39%');
    expect(fill(container, 1).style.width).toBe('51%');
    // Une semaine sans une minute d'entraînement n'a pas de barre pleine : elle n'a pas
    // de barre du tout.
    expect(fill(container, 2).style.width).toBe('0%');
  });
});
