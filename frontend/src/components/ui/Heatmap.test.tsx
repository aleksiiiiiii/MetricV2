import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Heatmap, type HeatDay } from './Heatmap';

function day(date: string, state: HeatDay['state'], level = 0, value = 0): HeatDay {
  return { date, value, state, level };
}

const WEEK: HeatDay[] = [
  day('2026-07-20', 'done', 3, 6),
  day('2026-07-21', 'off'),
  day('2026-07-22', 'missed'),
  day('2026-07-23', 'off'),
  day('2026-07-24', 'neutralised'),
  day('2026-07-25', 'bonus', 2, 3),
  day('2026-07-26', 'void'),
];

describe('Heatmap', () => {
  it('rend une cellule par jour, y compris les jours sans donnée', () => {
    // `HEAT-24` : le serveur renvoie la grille complète, le client n'a aucun trou à
    // combler.
    render(<Heatmap days={WEEK} label="Test" />);

    expect(screen.getAllByRole('button')).toHaveLength(WEEK.length);
  });

  it('distingue visuellement « rien attendu » de « manqué »', () => {
    // Le point central de `HEAT-05` : une grille majoritairement grise n'est pas un
    // échec. Si les deux états partageaient une classe, la piste non quotidienne
    // deviendrait illisible.
    render(<Heatmap days={WEEK} label="Test" />);

    const off = screen.getByRole('button', { name: /21 juillet/ });
    const missed = screen.getByRole('button', { name: /22 juillet/ });

    expect(off.className).not.toBe(missed.className);
  });

  it('annonce chaque état en toutes lettres pour les lecteurs d’écran', () => {
    render(<Heatmap days={WEEK} label="Test" />);

    expect(screen.getAllByRole('button', { name: /rien attendu/ })).toHaveLength(2);
    expect(screen.getByRole('button', { name: /22 juillet.*manqué/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /24 juillet.*neutralisé/ })).toBeInTheDocument();
  });

  it('rend inerte un jour hors plage', () => {
    // Avant la création de la piste (`HEAT-07`) il n'y a rien à explorer.
    render(<Heatmap days={WEEK} label="Test" />);

    expect(screen.getByRole('button', { name: /26 juillet/ })).toBeDisabled();
  });

  it('affiche les statuts hebdomadaires quand la piste est per_week', () => {
    // `HEAT-11` : c'est la semaine qui porte le statut, jamais le jour.
    render(
      <Heatmap
        days={WEEK}
        label="Test"
        weeks={[{ start: '2026-07-20', status: 'partial', done: 1, expected: 2 }]}
      />,
    );

    expect(screen.getByRole('list', { name: /hebdomadaire/i })).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });

  it('nomme les quatre états dans sa légende', () => {
    render(<Heatmap days={WEEK} label="Test" />);

    expect(screen.getByText('rien attendu')).toBeInTheDocument();
    expect(screen.getByText('manqué')).toBeInTheDocument();
    expect(screen.getByText('validé')).toBeInTheDocument();
  });
});
