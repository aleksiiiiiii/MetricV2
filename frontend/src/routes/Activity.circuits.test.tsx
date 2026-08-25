/**
 * Les séances Cadence — `/activite/seances`.
 *
 * Ce que ces tests protègent tient en trois phrases :
 *
 * * **L'écran ne fabrique ni lien ni durée.** Il rend ce que le serveur lui donne, et le
 *   test le vérifie en servant une adresse qu'aucun calcul client ne saurait produire.
 * * **Le `~` d'une durée estimée** est ce qui distingue une mesure d'un ordre de grandeur.
 * * **La durée consignée est celle du champ**, pré-remplie par l'estimation et corrigée —
 *   c'est tout le sens de la décision D4.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import { createQueryClient } from '@/lib/query';

import { Circuits } from './activity/Circuits';
import { CircuitsSection } from './activity/Circuits.section';

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

const BASE = 'https://cadence.exemple.fr';

const HAUT = {
  id: 0,
  token: 'jeton-haut',
  circuit_id: 'c1',
  name: 'Haut du corps',
  rounds: 4,
  round_rest_s: 60,
  created: '2026-08-24',
  note: null,
  exercises: [
    {
      position: 1,
      name: 'Push-Ups Classic',
      muscle_group: 'pectoraux',
      duration_s: null,
      reps: 15,
      rest_s: 20,
    },
    { position: 2, name: 'Plank', muscle_group: 'abdos', duration_s: 45, reps: null, rest_s: 15 },
  ],
  url: `${BASE}?w=Haut+du+corps~4~60~Push-Ups+Classic:15x:20~Plank:45s:15`,
  estimated_duration_min: 11.3,
  exact: false,
};

const GAINAGE = {
  ...HAUT,
  id: 1,
  token: 'jeton-gainage',
  circuit_id: 'c2',
  name: 'Gainage',
  rounds: 2,
  exercises: [
    { position: 1, name: 'Plank', muscle_group: 'abdos', duration_s: 60, reps: null, rest_s: 30 },
  ],
  url: `${BASE}?w=Gainage~2~60~Plank:60s:30`,
  estimated_duration_min: 4,
  exact: true,
};

/** Ce que le serveur propose à la saisie : Cadence d'abord, le catalogue ensuite. */
const SUGGESTIONS = [
  { name: 'Push-Ups Classic', illustrated: true, muscle_group: null },
  { name: 'Push-Ups Wide Grip', illustrated: true, muscle_group: null },
  { name: 'Pike Push-ups', illustrated: true, muscle_group: null },
  { name: 'Plank', illustrated: true, muscle_group: 'abdos' },
  { name: 'Développé couché', illustrated: false, muscle_group: 'pectoraux' },
];

function stub(body: unknown = { circuits: [HAUT, GAINAGE], linkable: true }) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    if (url.includes('/muscle-groups')) {
      return Promise.resolve(json(200, ['pectoraux', 'abdos', 'jambes']));
    }
    if (url.includes('/circuits/exercises')) {
      return Promise.resolve(json(200, SUGGESTIONS));
    }
    if (url.includes('/circuits')) {
      if (init?.method === 'POST') return Promise.resolve(json(201, HAUT));
      if (init?.method === 'DELETE') return Promise.resolve(json(204, undefined));
      return Promise.resolve(json(200, body));
    }
    return Promise.resolve(json(200, {}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderCircuits() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={['/activite/seances']}>
        <Toaster>
          <Routes>
            <Route path="/activite/seances" element={<Circuits />} />
          </Routes>
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function posted(fragment: string) {
  return calls.find((call) => call.init?.method === 'POST' && call.url.includes(fragment));
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('séances Cadence', () => {
  it('pose le lien du serveur dans un vrai href, sans le reconstruire', async () => {
    stub();
    renderCircuits();

    const open = await screen.findByRole('link', {
      name: 'Ouvrir Haut du corps dans Cadence',
    });
    expect(open).toHaveAttribute('href', HAUT.url);
    // `rel` protège la page ouverte de celle qui l'ouvre, même entre deux applications
    // écrites par la même personne.
    expect(open).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('préfixe d’un tilde la durée d’une séance en répétitions', async () => {
    // Personne ne sait combien de temps prend une série. Afficher « 11 min » serait une
    // valeur inventée, et Cadence lui-même préfixe ces totaux.
    stub();
    renderCircuits();

    expect(await screen.findByText('~11 min')).toBeInTheDocument();
    expect(screen.getByText('4 min')).toBeInTheDocument();
  });

  it('consigne la durée du champ, pré-remplie par l’estimation', async () => {
    // **D4** : l'estimation est une proposition. Elle part telle quelle si on n'y touche
    // pas, et corrigée si on la corrige.
    stub();
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Déclarer Gainage faite' }));

    const field = screen.getByLabelText(/Durée réelle/);
    expect(field).toHaveValue('4');

    await userEvent.clear(field);
    await userEvent.type(field, '7');
    await userEvent.click(screen.getByRole('button', { name: 'Consigner au journal' }));

    await waitFor(() => {
      const call = posted('/circuits/1/done');
      expect(JSON.parse(call?.init?.body as string)).toEqual({ duration_min: 7 });
    });
  });

  it('n’envoie rien tant que la durée est vide', async () => {
    stub();
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Déclarer Gainage faite' }));
    await userEvent.clear(screen.getByLabelText(/Durée réelle/));

    expect(screen.getByRole('button', { name: 'Consigner au journal' })).toBeDisabled();
  });

  it('demande deux appuis pour supprimer', async () => {
    // Le projet n'a aucune annulation. Une addition se défait, une destruction s'arme.
    stub();
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Supprimer Gainage' }));
    expect(calls.some((call) => call.init?.method === 'DELETE')).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: 'Supprimer Gainage — confirmer' }));
    await waitFor(() => {
      expect(calls.some((call) => call.init?.method === 'DELETE')).toBe(true);
    });
  });

  it('envoie le groupe musculaire choisi, jamais deviné', async () => {
    stub({ circuits: [], linkable: true });
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Créer une séance' }));
    await userEvent.type(screen.getByLabelText('Nom de la séance'), 'Abdos');
    await userEvent.type(screen.getByLabelText('Exercice 1'), 'Plank');
    await userEvent.click(screen.getByRole('button', { name: 'jambes' }));
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la séance' }));

    await waitFor(() => {
      const body = JSON.parse(posted('/circuits')?.init?.body as string) as {
        exercises: { muscle_group: string; duration_s?: number; reps?: number }[];
      };
      // Le sélecteur écrit `duration_s` **ou** `reps` — jamais les deux, jamais `-1`.
      expect(body.exercises).toEqual([
        { name: 'Plank', muscle_group: 'jambes', duration_s: 30, rest_s: 10 },
      ]);
    });
  });

  it('écrit reps et non des secondes quand on choisit les répétitions', async () => {
    // La faute la plus fréquente du format : quinze répétitions devenues quinze secondes.
    // Le sélecteur est ce qui l'empêche, et il doit vraiment changer le champ envoyé.
    stub({ circuits: [], linkable: true });
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Créer une séance' }));
    await userEvent.type(screen.getByLabelText('Nom de la séance'), 'Pompes');
    await userEvent.type(screen.getByLabelText('Exercice 1'), 'Push-Ups Classic');
    await userEvent.click(screen.getByRole('button', { name: 'Répétitions' }));
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la séance' }));

    await waitFor(() => {
      const body = JSON.parse(posted('/circuits')?.init?.body as string) as {
        exercises: { duration_s?: number; reps?: number }[];
      };
      expect(body.exercises).toEqual([
        { name: 'Push-Ups Classic', muscle_group: 'abdos', reps: 30, rest_s: 10 },
      ]);
    });
  });

  it('dit que l’adresse manque au lieu de laisser les boutons disparaître', async () => {
    // Deux états vides différents : « aucune séance » et « aucune adresse ». Découvrir le
    // second ligne par ligne serait une énigme.
    stub({ circuits: [{ ...HAUT, url: null }], linkable: false });
    renderCircuits();

    expect(await screen.findByText('Adresse de Cadence non renseignée')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Ouvrir/ })).not.toBeInTheDocument();
  });

  it('dit ce que coûte le prochain geste quand il n’y a aucune séance', async () => {
    stub({ circuits: [], linkable: true });
    renderCircuits();

    expect(await screen.findByText('Aucune séance')).toBeInTheDocument();
    expect(screen.queryByText(/0 min/)).not.toBeInTheDocument();
  });

  it('affiche le message du serveur quand la liste est illisible', async () => {
    // Un refus **définitif** : `storage_unavailable` est réessayé deux fois par le client
    // de requêtes, et le test mesurerait alors une temporisation plutôt qu'un écran. Le
    // message affiché vient du serveur dans les deux cas — c'est ça qu'on vérifie.
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = input as string;
        if (url.includes('/muscle-groups')) return Promise.resolve(json(200, []));
        return Promise.resolve(
          json(404, { code: 'not_found', message: 'Ces séances n’existent pas.' }),
        );
      }),
    );
    renderCircuits();

    expect(await screen.findByText('Ces séances n’existent pas.')).toBeInTheDocument();
  });

  it('ouvre la correction sur la séance importée, groupes à choisir', async () => {
    // Un lien Cadence ne porte aucun groupe musculaire : le dire tout de suite vaut mieux
    // que de laisser « autre » se découvrir dans les statistiques trois semaines plus tard.
    stub({ circuits: [], linkable: true });
    renderCircuits();

    await userEvent.type(await screen.findByLabelText('Adresse de la séance'), HAUT.url);
    await userEvent.click(screen.getByRole('button', { name: 'Relire ce lien' }));

    await waitFor(() => {
      expect(posted('/circuits/import')).toBeDefined();
    });
    expect(await screen.findByText('Corriger « Haut du corps »')).toBeInTheDocument();
  });

  it('réduit la liste des exercices à chaque frappe', async () => {
    stub({ circuits: [], linkable: true });
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Créer une séance' }));
    const field = screen.getByLabelText('Exercice 1');
    await userEvent.type(field, 'push');

    const options = screen.getAllByRole('option');
    expect(options.map((node) => node.textContent)).toEqual([
      expect.stringContaining('Push-Ups Classic'),
      expect.stringContaining('Push-Ups Wide Grip'),
      expect.stringContaining('Pike Push-ups'),
    ]);
  });

  it('trouve sans les accents ni la ponctuation', async () => {
    // On tape rarement ses accents entre deux séries, et « pushups » se tape plus vite
    // que « Push-Ups ».
    stub({ circuits: [], linkable: true });
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Créer une séance' }));
    await userEvent.type(screen.getByLabelText('Exercice 1'), 'developpe');

    expect(screen.getAllByRole('option')).toHaveLength(1);
    expect(screen.getByRole('option')).toHaveTextContent('Développé couché');
  });

  it('écrit le premier résultat quand on appuie sur Tab', async () => {
    stub({ circuits: [], linkable: true });
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Créer une séance' }));
    const field = screen.getByLabelText('Exercice 1');
    await userEvent.type(field, 'pik');
    await userEvent.tab();

    expect(field).toHaveValue('Pike Push-ups');
  });

  it('dit lesquels affichent une illustration', async () => {
    // Le seul service que le nom exact rend. Le dire à l'endroit où on choisit vaut mieux
    // que de le découvrir en plein round.
    stub({ circuits: [], linkable: true });
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Créer une séance' }));
    await userEvent.type(screen.getByLabelText('Exercice 1'), 'develop');

    expect(screen.getByRole('option')).not.toHaveTextContent('illustration');
  });

  it('pré-remplit le groupe musculaire quand l’exercice est au catalogue', async () => {
    stub({ circuits: [], linkable: true });
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Créer une séance' }));
    await userEvent.type(screen.getByLabelText('Nom de la séance'), 'Gainage');
    await userEvent.type(screen.getByLabelText('Exercice 1'), 'plank');
    await userEvent.click(screen.getByRole('option', { name: /Plank/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la séance' }));

    await waitFor(() => {
      const body = JSON.parse(posted('/circuits')?.init?.body as string) as {
        exercises: { name: string; muscle_group: string }[];
      };
      expect(body.exercises).toMatchObject([{ name: 'Plank', muscle_group: 'abdos' }]);
    });
  });

  it('laisse écrire un nom qui n’est dans aucune liste', async () => {
    // Ces suggestions ne sont pas des valeurs autorisées : n'importe quel intitulé fait
    // tourner une séance, il perd seulement son illustration.
    stub({ circuits: [], linkable: true });
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Créer une séance' }));
    await userEvent.type(screen.getByLabelText('Nom de la séance'), 'Perso');
    await userEvent.type(screen.getByLabelText('Exercice 1'), 'Montées de genoux');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la séance' }));

    await waitFor(() => {
      const body = JSON.parse(posted('/circuits')?.init?.body as string) as {
        exercises: { name: string }[];
      };
      expect(body.exercises).toMatchObject([{ name: 'Montées de genoux' }]);
    });
  });

  it('reprend la nature de chaque exercice à la correction', async () => {
    // Rouvrir une séance et enregistrer sans y toucher ne doit pas transformer quinze
    // répétitions en quinze secondes.
    stub();
    renderCircuits();

    await userEvent.click(await screen.findByRole('button', { name: 'Corriger Haut du corps' }));
    const first = screen.getByLabelText('Exercice 1').closest('div')?.parentElement;

    expect(within(first as HTMLElement).getByLabelText('Répétitions')).toHaveValue('15');
  });
});

// ── La mise en avant sur `/activite` ──────────────────

describe('séances Cadence en tête de l’écran Activité', () => {
  it('les montre avant le journal, avec le lien pour les ouvrir', async () => {
    // Ce qu'on **fait** passe devant ce qu'on lit : une séance Cadence démarre d'un appui,
    // là où consigner une série suppose d'avoir déjà commencé.
    stub();
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={['/activite']}>
          <Toaster>
            <Routes>
              <Route path="/activite" element={<CircuitsSection />} />
            </Routes>
          </Toaster>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByRole('link', { name: 'Ouvrir Haut du corps dans Cadence' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Déclarer Gainage faite' })).toBeInTheDocument();
  });

  it('n’y porte ni correction ni suppression — elles vivent sur la page', async () => {
    // Une section qui porterait le formulaire entier ramènerait le défaut que la page a
    // précisément corrigé.
    stub();
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={['/activite']}>
          <Toaster>
            <Routes>
              <Route path="/activite" element={<CircuitsSection />} />
            </Routes>
          </Toaster>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByRole('link', { name: 'Ouvrir Haut du corps dans Cadence' });
    expect(screen.queryByRole('button', { name: /Corriger/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Supprimer/ })).not.toBeInTheDocument();
  });

  it('dit ce que coûte le prochain geste quand il n’y a aucune séance', async () => {
    stub({ circuits: [], linkable: true });
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={['/activite']}>
          <Toaster>
            <Routes>
              <Route path="/activite" element={<CircuitsSection />} />
            </Routes>
          </Toaster>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Aucune séance')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Créer une séance' })).toBeInTheDocument();
  });
});
