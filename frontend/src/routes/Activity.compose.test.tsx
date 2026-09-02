import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import type { CircuitProposal } from '@/features/activity/api';
import { createQueryClient } from '@/lib/query';

import { Compose } from './activity/Compose';

/**
 * `/activite/creer` — le parcours **proposer → ajuster → enregistrer**.
 *
 * Ce que ces tests portent, et qu'aucun test d'API ne verrait : que rien ne part au
 * serveur avant l'appui, et que la marque « proposé » disparaît dès qu'on touche une
 * valeur. Corriger, c'est s'approprier — et si la marque restait, l'écran continuerait
 * d'annoncer comme une suggestion un chiffre que l'utilisateur a lui-même écrit.
 */

const PROPOSAL: CircuitProposal = {
  name: 'Bras — 30 min',
  rounds: 4,
  round_rest_s: 60,
  exercises: [
    {
      name: 'push-up',
      muscle_group: 'pectoraux',
      duration_s: null,
      reps: 12,
      rest_s: 20,
      illustrated: true,
    },
    {
      name: 'Pompes sautées maison',
      muscle_group: 'autre',
      duration_s: 40,
      reps: null,
      rest_s: 20,
      illustrated: false,
    },
  ],
  basis: ['Matériel pris en compte : dumbbell'],
  dropped: ['exercice 3 : sans nom'],
};

/** Ce que le serveur rend pour une recherche de nom — les siens, puis ceux de Cadence. */
const CATALOGUE = [
  { name: 'push-up', muscle_group: null, body_part: 'chest', equipment: 'body weight' },
  { name: 'plank', muscle_group: null, body_part: 'waist', equipment: 'body weight' },
];

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function stub(proposal: CircuitProposal = PROPOSAL) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = input as string;
      calls.push({ url, init });
      const body = url.includes('/muscle-groups')
        ? ['pectoraux', 'dos', 'abdos', 'autre']
        : url.includes('/circuits/exercises')
          ? CATALOGUE
          : url.includes('/propose')
            ? proposal
            : { id: 0 };
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
      } as Response);
    }),
  );
}

function renderCompose() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Toaster>
          <Compose />
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function writes(): Call[] {
  return calls.filter((call) => (call.init?.method ?? 'GET') !== 'GET');
}

async function propose(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Proposer une séance' }));
  await screen.findByLabelText('Nom de la séance');
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('composition assistée', () => {
  it('propose les noms exacts du catalogue plutôt qu’un champ libre', async () => {
    // C'est **l'orthographe exacte** qui décide de la démonstration affichée pendant
    // l'effort, et ni le modèle ni l'utilisateur n'ont moyen de la deviner. Le champ reste
    // libre pour autant : un nom hors liste s'enregistre, il perd seulement son image.
    const user = userEvent.setup();
    stub();
    renderCompose();

    await propose(user);
    const field = screen.getByLabelText('Exercice 1');
    await user.clear(field);
    await user.type(field, 'pl');

    const liste = await screen.findByRole('listbox', { name: /Exercice 1/ });

    expect(field).toHaveValue('pl');
    expect(liste).toHaveTextContent('plank');
    expect(calls.some((call) => call.url.includes('/circuits/exercises?q=pl'))).toBe(true);
  });

  it('n’écrit rien tant qu’on n’a pas appuyé sur Enregistrer', async () => {
    // **Le test qui porte la page.** Un circuit à dix exercices se corrige mal une fois
    // enregistré : proposer, ajuster et écrire sont trois temps séparés.
    const user = userEvent.setup();
    stub();
    renderCompose();

    await propose(user);
    await user.clear(screen.getByLabelText('Rounds'));
    await user.type(screen.getByLabelText('Rounds'), '5');

    expect(writes().map((call) => call.url)).toEqual(['/api/activity/circuits/propose']);
  });

  it('enregistre la séance ajustée, pas celle qui a été proposée', async () => {
    const user = userEvent.setup();
    stub();
    renderCompose();

    await propose(user);
    const rounds = screen.getByLabelText('Rounds');
    await user.clear(rounds);
    await user.type(rounds, '6');
    await user.click(screen.getByRole('button', { name: 'Enregistrer la séance' }));

    await waitFor(() => {
      const call = writes().find((entry) => entry.url === '/api/activity/circuits');
      expect(JSON.parse(call?.init?.body as string)).toMatchObject({
        name: 'Bras — 30 min',
        rounds: 6,
        exercises: [
          { name: 'push-up', muscle_group: 'pectoraux', reps: 12 },
          { name: 'Pompes sautées maison', muscle_group: 'autre', duration_s: 40 },
        ],
      });
    });
  });

  it('marque les valeurs comme proposées, et lève la marque dès qu’on y touche', async () => {
    // « Corriger, c'est s'approprier. » La marque est par champ : retoucher les rounds ne
    // doit pas dédouaner le repos, qui n'a été relu par personne.
    const user = userEvent.setup();
    stub();
    renderCompose();

    await propose(user);
    const rounds = screen.getByLabelText('Rounds');
    const rest = screen.getByLabelText('Repos entre rounds (s)');

    // L'attribut que `Stepper` pose lui-même : le statut se **dit** à un lecteur d'écran,
    // il n'est pas seulement dessiné en trait discontinu.
    expect(rounds).toHaveAttribute('aria-description', 'valeur proposée, à valider');
    expect(rest).toHaveAttribute('aria-description', 'valeur proposée, à valider');

    await user.clear(rounds);
    await user.type(rounds, '5');

    expect(rounds).not.toHaveAttribute('aria-description');
    expect(rest).toHaveAttribute('aria-description', 'valeur proposée, à valider');
  });

  it('dit quand un nom n’affichera aucune démonstration', async () => {
    // Un nom hors catalogue reste valide et la séance tourne — elle n'affiche simplement
    // pas d'image. Le taire promettrait une démonstration qui n'arrivera pas.
    const user = userEvent.setup();
    stub();
    renderCompose();

    await propose(user);

    expect(screen.getByText('sans démonstration')).toBeInTheDocument();
  });

  it('dit ce qui a été écarté à la relecture', async () => {
    // Le taire laisserait croire que le modèle n'a proposé que cela, et rendrait
    // incompréhensible une séance à deux exercices quand on en attendait six.
    const user = userEvent.setup();
    stub();
    renderCompose();

    await propose(user);

    expect(screen.getByText('exercice 3 : sans nom')).toBeInTheDocument();
  });

  it('montre sur quoi la proposition s’appuie', async () => {
    // Une suggestion dont on voit l'argument se discute ; une suggestion nue se croit ou
    // se rejette.
    const user = userEvent.setup();
    stub();
    renderCompose();

    await propose(user);

    expect(screen.getByText('Matériel pris en compte : dumbbell')).toBeInTheDocument();
  });

  it('n’active « Enregistrer » que si la séance est complète', async () => {
    const user = userEvent.setup();
    stub();
    renderCompose();

    await propose(user);
    expect(screen.getByRole('button', { name: 'Enregistrer la séance' })).toBeEnabled();

    await user.clear(screen.getByLabelText('Exercice 1'));

    expect(screen.getByRole('button', { name: 'Enregistrer la séance' })).toBeDisabled();
    expect(screen.getByText(/Il manque un nom/)).toBeInTheDocument();
  });
});
