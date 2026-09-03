/**
 * Les charges des exercices de tabata — `/activite/charges`.
 *
 * Ce que ces tests protègent :
 *
 * * **Rien n'est inventé sur un exercice jamais renseigné.** Un tiret, pas un zéro — la
 *   confusion coûterait une charge fausse dans le lien d'une séance.
 * * **Trois états, décidés par le serveur.** L'écran groupe sur l'étiquette qu'il reçoit.
 * * **La première charge est une addition, la suivante une modification sous garde.** Le
 *   couple `id`/`token` à `null` est ce qui distingue les deux, et se tromper de verbe
 *   écrirait une seconde ligne pour le même exercice.
 * * **Un appui confirme.** Le pas-à-pas n'écrit pas ; sans quoi monter de 10 à 16 kg
 *   poserait six points sur la courbe.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import { createQueryClient } from '@/lib/query';

import { Loads } from './activity/Loads';

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

const ROWING = {
  id: 0,
  token: 'jeton-rowing',
  name: 'Rowing',
  state: 'weighted',
  weight_kg: 12,
  updated: '2026-08-30',
  circuits: 2,
  days_since_change: 24,
  sessions_since: 3,
};

const FENTES = {
  id: null,
  token: null,
  name: 'Fentes',
  state: 'unset',
  weight_kg: null,
  updated: null,
  circuits: 1,
  // Jamais chiffrée : rien au journal, donc rien à dater. `null` et non `0`.
  days_since_change: null,
  sessions_since: null,
};

const GAINAGE = {
  id: 1,
  token: 'jeton-gainage',
  name: 'Gainage',
  state: 'bodyweight',
  weight_kg: null,
  updated: '2026-08-12',
  circuits: 3,
  days_since_change: 0,
  sessions_since: 0,
};

/** Trente jours dont deux allumés — la ligne de points fait toujours sa longueur. */
const SESSIONS = Array.from({ length: 30 }, (_, index) => ({
  date: `2026-08-${String(index + 1).padStart(2, '0')}`,
  count: index === 4 || index === 19 ? 1 : 0,
}));

function stub(loads: unknown[] = [FENTES, ROWING, GAINAGE], detail?: unknown) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    if (url.includes('/loads/detail')) {
      return Promise.resolve(
        json(
          200,
          detail ?? {
            name: 'Rowing',
            state: 'weighted',
            weight_kg: 12,
            history: [
              { date: '2026-07-02', weight_kg: 10 },
              { date: '2026-08-11', weight_kg: 12 },
            ],
            sessions: SESSIONS,
            circuits: ['Haut du corps', 'Full body'],
            demo_url: 'https://ct.exemple.fr/exercise-db/gifs/0025-AbCdEf.gif?key=274',
          },
        ),
      );
    }
    if (url.includes('/loads')) {
      if (init?.method === 'POST')
        return Promise.resolve(json(201, { ...FENTES, id: 3, state: 'weighted', weight_kg: 20 }));
      if (init?.method === 'PATCH') return Promise.resolve(json(200, { ...ROWING, weight_kg: 16 }));
      return Promise.resolve(json(200, { loads, step_kg: 1 }));
    }
    return Promise.resolve(json(200, {}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderLoads() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={['/activite/charges']}>
        <Toaster>
          <Routes>
            <Route path="/activite/charges" element={<Loads />} />
          </Routes>
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function sent(method: string) {
  return calls.find((call) => call.init?.method === method);
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('charges des exercices de tabata', () => {
  it('n’affiche aucune valeur sur un exercice jamais renseigné', async () => {
    // Un zéro passerait pour une mesure, et partirait dans le lien de la séance.
    stub();
    renderLoads();

    expect(await screen.findByText('Fentes')).toBeInTheDocument();

    // Le champ porte un tiret et rien d'autre. Un `0` y passerait pour une mesure, et
    // partirait tel quel dans le 4ᵉ champ du lien de la séance.
    const champs = screen.getAllByLabelText('Charge');
    expect(champs[0]).toHaveValue('');
    expect(champs[0]).toHaveAttribute('placeholder', '—');
  });

  it('dit depuis quand une charge n’a pas bougé, et ce qu’elle a tenu', async () => {
    // **Un constat, jamais un conseil** (`R10`). L'écran met en français deux chiffres que
    // le serveur a calculés ; il n'en dérive aucun et ne conclut rien.
    stub();
    renderLoads();

    expect(
      await screen.findByText('changée il y a 24 jours · 3 séances depuis'),
    ).toBeInTheDocument();
  });

  it('n’invente aucun compteur sur un exercice jamais chiffré', async () => {
    // `null` n'est pas `0` : « changée il y a 0 jour » sur une carte jamais renseignée
    // serait une mesure inventée, exactement ce que l'invariant interdit.
    stub();
    renderLoads();

    await screen.findByText('Fentes');
    const fentes = screen.getByText('Fentes').closest('div');

    expect(fentes?.textContent).not.toMatch(/changée/);
    expect(fentes?.textContent).not.toMatch(/depuis/);
  });

  it('sépare les trois états sur l’étiquette du serveur', async () => {
    // « pas encore renseigné » n'est pas « poids du corps », et l'écran ne le déduit pas
    // d'un `weight_kg` à `null` : les deux le portent.
    stub();
    renderLoads();

    expect(await screen.findByText('À renseigner')).toBeInTheDocument();
    expect(screen.getByText('Chargés')).toBeInTheDocument();
    expect(screen.getByText('Poids du corps')).toBeInTheDocument();

    // La valeur vit dans le champ, à droite, et à un seul endroit : la pastille qui la
    // répétait a disparu avec la disposition en deux colonnes.
    expect(screen.getAllByLabelText('Charge')[1]).toHaveValue('12');
  });

  it('crée sans jeton la première charge, et corrige avec', async () => {
    stub();
    renderLoads();

    // Fentes n'a pas de ligne : `id` et `token` sont à `null`, c'est un POST.
    const steppers = await screen.findAllByLabelText('Charge');
    await userEvent.type(steppers[0] as HTMLElement, '20');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer' }));

    await waitFor(() => {
      expect(sent('POST')).toBeDefined();
    });
    expect(sent('POST')?.init?.headers).not.toHaveProperty('If-Match');
  });

  it('renvoie le jeton lu sur la ligne en If-Match', async () => {
    stub();
    renderLoads();

    const steppers = await screen.findAllByLabelText('Charge');
    await userEvent.clear(steppers[1] as HTMLElement);
    await userEvent.type(steppers[1] as HTMLElement, '16');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer' }));

    await waitFor(() => {
      expect(sent('PATCH')).toBeDefined();
    });
    expect(sent('PATCH')?.init?.headers).toMatchObject({ 'If-Match': 'jeton-rowing' });
  });

  it('n’écrit rien tant qu’on n’a pas confirmé', async () => {
    // Le pas-à-pas ajuste une valeur locale. Sans cette règle, monter de 10 à 16 kg
    // poserait six lignes dans le journal et six points sur la courbe.
    stub();
    renderLoads();

    const steppers = await screen.findAllByLabelText('Charge');
    await userEvent.type(steppers[0] as HTMLElement, '20');

    expect(sent('POST')).toBeUndefined();
    expect(sent('PATCH')).toBeUndefined();
  });

  it('n’offre aucun bouton tant que rien n’a bougé', async () => {
    // Un bouton désactivé en permanence occupe la place et n'apprend rien. Celui-ci
    // apparaît au premier appui sur `+` : sa présence *est* le signal qu'un geste reste.
    stub();
    renderLoads();

    await screen.findByText('Rowing');

    expect(screen.queryByRole('button', { name: 'Enregistrer' })).not.toBeInTheDocument();

    await userEvent.click(
      screen.getAllByRole('button', { name: 'Charge : augmenter' })[1] as HTMLElement,
    );

    expect(screen.getByRole('button', { name: 'Enregistrer' })).toBeInTheDocument();
  });

  it('propose le poids du corps, et pas sur ceux qui y sont déjà', async () => {
    // Une icône, pas un bouton en toutes lettres — mais le libellé reste dit : un bouton
    // sans nom accessible n'existe pas pour qui n'y voit rien, et huit icônes identiques
    // dans une liste ont besoin de dire **lequel** elles règlent.
    stub();
    renderLoads();

    await screen.findByText('Rowing');

    expect(screen.getAllByRole('button', { name: /au poids du corps/ })).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Rowing : au poids du corps' })).toBeInTheDocument();
  });

  it('filtre les trois sections d’un seul champ', async () => {
    // Chercher « rowing » sans savoir s'il est chargé ou au poids du corps est exactement
    // la raison d'avoir ce champ : il porte sur la page, pas sur une section.
    stub();
    renderLoads();

    await userEvent.type(await screen.findByLabelText('Rechercher un exercice'), 'gain');

    expect(screen.getByText('Gainage')).toBeInTheDocument();
    expect(screen.queryByText('Rowing')).not.toBeInTheDocument();
    expect(screen.queryByText('Fentes')).not.toBeInTheDocument();
  });

  it('dit qu’une recherche ne trouve rien, sans prétendre qu’il n’y a rien', async () => {
    // « aucun résultat » et « aucune séance » ne proposent pas le même geste suivant.
    stub();
    renderLoads();

    await userEvent.type(await screen.findByLabelText('Rechercher un exercice'), 'zzz');

    expect(screen.getByText('Aucun exercice ne correspond')).toBeInTheDocument();
    expect(screen.queryByText('Aucune séance tabata')).not.toBeInTheDocument();
  });

  it('rend un pas-à-pas à un exercice au poids du corps, sans rien écrire', async () => {
    // Le bouton n'écrit pas : il rend le contrôle. Sans cette étape, l'appui poserait une
    // charge que personne n'a choisie — et rien ne défait une écriture dans ce projet.
    stub();
    renderLoads();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gainage : remettre une charge' }),
    );

    expect(sent('PATCH')).toBeUndefined();

    // Gainage a rejoint les cartes : il porte maintenant son propre champ de charge.
    expect(screen.getAllByLabelText('Charge')).toHaveLength(3);

    await userEvent.type(screen.getAllByLabelText('Charge')[2] as HTMLElement, '8');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer' }));

    await waitFor(() => {
      expect(sent('PATCH')).toBeDefined();
    });
    const envoye = sent('PATCH')?.init?.body;
    expect(typeof envoye).toBe('string');
    expect(JSON.parse(envoye as string)).toMatchObject({ name: 'Gainage', weight_kg: 8 });
  });

  it('dit qu’il faut une séance avant une charge', async () => {
    // L'état vide n'est pas « aucune charge » : sans circuit, il n'y a aucun exercice à
    // charger, et le geste qui coûte le moins est de créer la séance.
    stub([]);
    renderLoads();

    expect(await screen.findByText('Aucune séance tabata')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Créer une séance' })).toHaveAttribute(
      'href',
      '/activite/seances',
    );
  });

  it('ouvre le détail avec sa courbe et ses trente points', async () => {
    stub();
    renderLoads();

    await userEvent.click(await screen.findByRole('button', { name: 'Rowing' }));

    const row = await screen.findByRole('img', { name: /30 derniers jours/ });
    expect(row).toBeInTheDocument();
    expect(row.children).toHaveLength(30);
  });

  it('montre la démonstration servie par l’instance Cadence', async () => {
    // Le nom du catalogue est anglais : l'image dit de quel mouvement on parle, ce que
    // « Rowing » ne dit pas à tout le monde.
    stub([ROWING]);
    renderLoads();

    await userEvent.click(await screen.findByRole('button', { name: 'Rowing' }));

    const demo = await screen.findByRole('img', { name: 'Démonstration de Rowing' });
    expect(demo).toHaveAttribute(
      'src',
      'https://ct.exemple.fr/exercise-db/gifs/0025-AbCdEf.gif?key=274',
    );
  });

  it('n’écrit rien à la place quand il n’y a pas de démonstration', async () => {
    // Trois raisons possibles — pas d'adresse réglée, instance éteinte, nom sans
    // correspondance — et aucune n'appelle un geste. Un encart « indisponible » ferait
    // passer pour une panne l'état normal d'un exercice écrit à la main.
    stub([ROWING], {
      name: 'Rowing',
      state: 'weighted',
      weight_kg: 12,
      history: [],
      sessions: SESSIONS,
      circuits: ['Haut du corps'],
      demo_url: null,
    });
    renderLoads();

    await userEvent.click(await screen.findByRole('button', { name: 'Rowing' }));
    await screen.findByText('12 kg');

    expect(screen.queryByRole('img', { name: /Démonstration/ })).toBeNull();
    expect(screen.queryByText(/démonstration/i)).toBeNull();
  });

  it('ne peint pas deux fois la même graduation sur une charge inchangée', async () => {
    // Vu dans la console de l'application : « Encountered two children with the same key,
    // `8` ». Les deux bornes du domaine sont le même nombre dès que la charge n'a pas
    // bougé — le cas le plus courant de cette page — et la courbe se collait alors au bord
    // inférieur du cadre, où elle se lit comme une chute vers zéro.
    stub([ROWING], {
      name: 'Rowing',
      state: 'weighted',
      weight_kg: 8,
      history: [
        { date: '2026-07-02', weight_kg: 8 },
        { date: '2026-08-11', weight_kg: 8 },
      ],
      sessions: SESSIONS,
      circuits: ['Haut du corps'],
      demo_url: null,
    });
    renderLoads();

    await userEvent.click(await screen.findByRole('button', { name: 'Rowing' }));
    const chart = await screen.findByRole('img', { name: /Charge/ });

    expect(within(chart).getAllByText('8 kg')).toHaveLength(1);
  });

  it('ne trace pas de courbe sur un seul point', async () => {
    // Une ligne d'un seul point n'est pas une évolution, et la dessiner laisserait croire
    // à une tendance.
    stub([ROWING], {
      name: 'Rowing',
      state: 'weighted',
      weight_kg: 12,
      history: [{ date: '2026-08-11', weight_kg: 12 }],
      sessions: SESSIONS,
      circuits: ['Haut du corps'],
    });
    renderLoads();

    await userEvent.click(await screen.findByRole('button', { name: 'Rowing' }));

    expect(await screen.findByText(/La courbe demande un second point/)).toBeInTheDocument();
  });
});
