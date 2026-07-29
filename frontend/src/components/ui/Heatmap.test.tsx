import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Heatmap, type HeatDay } from './Heatmap';

function day(date: string, state: HeatDay['state'], level = 0, value = 0): HeatDay {
  return { date, value, state, level, reason: null };
}

/** Un `off` dont le serveur dit *pourquoi* il l'est (`DayReason`). */
function off(date: string, reason: HeatDay['reason']): HeatDay {
  return { date, value: 0, state: 'off', level: 0, reason };
}

const WEEK: HeatDay[] = [
  day('2026-07-20', 'done', 3, 6),
  day('2026-07-21', 'off'),
  day('2026-07-22', 'missed'),
  off('2026-07-23', 'future'),
  off('2026-07-24', 'neutralised'),
  day('2026-07-25', 'bonus', 2, 3),
  off('2026-07-26', 'before_track'),
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

    expect(screen.getByRole('button', { name: /21 juillet.*rien attendu/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /22 juillet.*manqué/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /24 juillet.*neutralisé/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /23 juillet.*à venir/ })).toBeInTheDocument();
  });

  it('peint les jours à venir comme les autres « rien attendu », pas comme des trous', () => {
    // Le piège de rendu repéré au lot L10 : la plage par défaut va jusqu'au dimanche de
    // la semaine en cours. En faire des trous donnerait à chaque grille une entaille
    // hebdomadaire qui ne veut rien dire.
    render(<Heatmap days={WEEK} label="Test" />);

    const plain = screen.getByRole('button', { name: /21 juillet/ });
    const ahead = screen.getByRole('button', { name: /23 juillet/ });

    expect(ahead.className).toBe(plain.className);
  });

  it('rend inerte ce qui précède la création de la piste', () => {
    // Là, en revanche, il n'y avait rien à tenir (`HEAT-07`) : rien à explorer non plus.
    render(<Heatmap days={WEEK} label="Test" />);

    expect(screen.getByRole('button', { name: /26 juillet/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /23 juillet/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /22 juillet/ })).toBeEnabled();
  });

  it('laisse une semaine « off » sans couleur', () => {
    // Une semaine antérieure à la piste ou neutralisée n'a rien à dire, et lui donner
    // une couleur serait lui faire dire quelque chose (`HEAT-07`, `HEAT-28`).
    render(
      <Heatmap
        days={WEEK}
        label="Test"
        weeks={[
          { start: '2026-07-13', status: 'off', done: 0, expected: 2 },
          { start: '2026-07-20', status: 'missed', done: 0, expected: 2 },
        ]}
      />,
    );

    const [neutral, missed] = screen.getAllByRole('listitem');
    expect(neutral?.className).not.toBe(missed?.className);
  });

  it('repère la cellule d’aujourd’hui', () => {
    render(<Heatmap days={WEEK} label="Test" today="2026-07-22" />);

    const today = screen.getByRole('button', { name: /22 juillet/ });
    const other = screen.getByRole('button', { name: /21 juillet/ });

    expect(today.className).not.toBe(other.className);
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
