import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import { tokenStore } from '@/lib/api';
import { createQueryClient } from '@/lib/query';

import { Nutrition } from './Nutrition';

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

const VIEW = {
  date: '2026-07-27',
  totals: {
    protein_g: 75,
    protein_target_g: 150,
    protein_ratio: 0.5,
    added_sugar_g: 15,
    added_sugar_max_g: 30,
    over_sugar: false,
    calories: 1120,
    calories_known: 2,
    meals: 2,
  },
  meals: [
    {
      id: 1,
      token: 'jeton-b',
      datetime: '2026-07-27T12:30:00+02:00',
      meal_type: 'déjeuner',
      comment: 'poulet riz',
      photo: '2026/07/27/20260727-123000-deadbeef.jpg',
      protein_g: 40,
      added_sugar_g: 10,
      calories: 600,
      source: 'manual',
    },
    {
      id: 0,
      token: 'jeton-a',
      datetime: '2026-07-27T08:10:00+02:00',
      meal_type: 'petit-déjeuner',
      comment: 'skyr',
      photo: null,
      protein_g: 35,
      added_sugar_g: 5,
      calories: 520,
      source: 'ai',
    },
  ],
  favorites: [
    {
      id: 0,
      token: 'jeton-fav',
      favorite_id: 'f1',
      name: 'Skyr + flocons',
      protein_g: 32,
      added_sugar_g: 12,
      calories: 380,
    },
  ],
  suggested_type: 'déjeuner',
  types: ['petit-déjeuner', 'déjeuner', 'dîner', 'collation'],
};

function stub(custom?: (url: string, init?: RequestInit) => Response | undefined) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    const override = custom?.(url, init);
    if (override) return Promise.resolve(override);

    // L'assistance décide **quels modes de saisie** la feuille propose : sans cette
    // réponse, les trois modes assistés n'existent pas et les tests mesureraient un écran
    // que personne n'a. `Nutrition.ai.test.tsx` scénarise l'autre cas.
    if (url.includes('/api/ai/status')) {
      return Promise.resolve(json(200, { enabled: true, message: 'disponible' }));
    }
    if (url.includes('/nutrition/photos/')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        blob: () => Promise.resolve(new Blob([new Uint8Array([1, 2, 3])], { type: 'image/jpeg' })),
      } as unknown as Response);
    }
    if (url.includes('/api/nutrition')) return Promise.resolve(json(200, VIEW));
    return Promise.resolve(json(200, {}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderNutrition() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Toaster>
          <Nutrition />
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * Ouvre la feuille d'ajout sur un mode donné.
 *
 * Le formulaire n'est plus déplié dans la page : la feuille demande d'abord **comment** on
 * veut noter le repas. Deux appuis, donc, avant d'atteindre les champs.
 */
async function openSheet(mode: string) {
  await userEvent.click(await screen.findByRole('button', { name: 'Ajouter un repas' }));
  await userEvent.click(await screen.findByRole('button', { name: mode }));
}

beforeEach(() => {
  calls.length = 0;
  tokenStore.write('jeton-de-session');
  // jsdom ne fournit pas les URL d'objet.
  URL.createObjectURL = vi.fn(() => 'blob:photo');
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
  tokenStore.clear();
});

describe('écran Nutrition', () => {
  it('affiche les totaux calculés par le serveur', async () => {
    stub();
    renderNutrition();

    expect(await screen.findByText(/75 g sur 150 g/)).toBeInTheDocument();
    expect(screen.getByText(/plafond 30 g/)).toBeInTheDocument();
  });

  it('nuance un total de calories partiel', async () => {
    // Un total sur deux repas renseignés sur cinq ne veut pas dire grand-chose.
    stub((url) =>
      url.includes('/api/nutrition') && !url.includes('photos')
        ? json(200, { ...VIEW, totals: { ...VIEW.totals, calories_known: 1, meals: 3 } })
        : undefined,
    );
    renderNutrition();

    expect(await screen.findByText(/sur 1 repas renseigné \/ 3/)).toBeInTheDocument();
  });

  it('signale un dépassement du plafond de sucres', async () => {
    stub((url) =>
      url.includes('/api/nutrition') && !url.includes('photos')
        ? json(200, {
            ...VIEW,
            totals: { ...VIEW.totals, added_sugar_g: 45, over_sugar: true },
          })
        : undefined,
    );
    renderNutrition();

    expect(await screen.findByText(/plafond dépassé/)).toBeInTheDocument();
  });

  it('charge les photos avec le jeton de session', async () => {
    // `NUT-08` : l'endpoint est authentifié, un `<img src>` naïf recevrait un 401.
    stub();
    renderNutrition();

    await waitFor(() => {
      const photo = calls.find((call) => call.url.includes('/nutrition/photos/'));
      expect(photo).toBeDefined();
      expect((photo?.init?.headers as Record<string, string>).Authorization).toBe(
        'Bearer jeton-de-session',
      );
    });
  });

  it('reste lisible pour un repas sans photo', async () => {
    stub();
    renderNutrition();

    expect(await screen.findByText('skyr')).toBeInTheDocument();
  });

  it("distingue une estimation IA d'une saisie manuelle", async () => {
    stub();
    renderNutrition();

    expect(await screen.findByText('ai')).toBeInTheDocument();
  });

  it('présélectionne le type suggéré par le serveur', async () => {
    // `NUT-03` : le client ne redéfinit pas la règle horaire.
    stub();
    renderNutrition();
    await openSheet('Description');

    expect(screen.getByLabelText('Type')).toHaveValue('déjeuner');
  });

  it('demande le mode avant de demander quoi que ce soit d’autre', async () => {
    // Le formulaire était déplié en permanence : on traversait la photo et la description
    // pour taper trois nombres. La feuille demande d'abord **comment** on veut noter.
    stub();
    renderNutrition();

    await userEvent.click(await screen.findByRole('button', { name: 'Ajouter un repas' }));

    for (const mode of ['Photo', 'Photo et description', 'Description', 'Valeurs à la main']) {
      expect(screen.getByRole('button', { name: mode })).toBeInTheDocument();
    }
    // Rien n'est demandé tant que le mode n'est pas choisi.
    expect(screen.queryByRole('button', { name: 'Enregistrer le repas' })).toBeNull();
  });

  it('revient au choix du mode sans rien écrire', async () => {
    // « Annuler à n'importe quelle étape » : le retour en arrière vide ce qui a été tapé
    // et ne laisse aucune trace côté serveur.
    stub();
    renderNutrition();
    await openSheet('Description');

    await userEvent.type(screen.getByLabelText('Description'), 'salade');
    await userEvent.click(screen.getByRole('button', { name: 'Changer de mode' }));

    expect(screen.getByRole('button', { name: 'Photo' })).toBeInTheDocument();
    expect(calls.filter((call) => call.init?.method === 'POST')).toHaveLength(0);
  });

  it('envoie un formulaire multipart avec la description', async () => {
    stub();
    renderNutrition();

    await openSheet('Description');
    await userEvent.type(screen.getByLabelText('Description'), 'salade');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer le repas' }));

    await waitFor(() => {
      const post = calls.find(
        (call) => call.init?.method === 'POST' && call.url === '/api/nutrition',
      );
      expect(post?.init?.body).toBeInstanceOf(FormData);
      const form = post?.init?.body as FormData;
      expect(form.get('comment')).toBe('salade');
      expect(form.get('meal_type')).toBe('déjeuner');
    });
  });

  it("n'impose pas de Content-Type sur un multipart", async () => {
    // Le navigateur y ajoute la frontière de séparation, qu'on ne peut pas deviner.
    stub();
    renderNutrition();

    await openSheet('Description');
    await userEvent.type(screen.getByLabelText('Description'), 'salade');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer le repas' }));

    await waitFor(() => {
      const post = calls.find(
        (call) => call.init?.method === 'POST' && call.url === '/api/nutrition',
      );
      expect((post?.init?.headers as Record<string, string>)['Content-Type']).toBeUndefined();
    });
  });

  it("empêche d'enregistrer un repas vide", async () => {
    // `NUT-01` : au moins une photo ou une description.
    stub();
    renderNutrition();
    await openSheet('Description');

    expect(screen.getByRole('button', { name: 'Enregistrer le repas' })).toBeDisabled();
  });

  it('enregistre les sucres d’un repas récurrent', async () => {
    // Le fichier porte la colonne depuis toujours, la carte ne la demandait pas : un
    // repas rejoué arrivait donc au journal avec un sucre à vide, et le plafond
    // quotidien comptait faux sur tout ce qui revient chaque jour.
    stub();
    renderNutrition();

    await userEvent.type(await screen.findByLabelText('Nom'), 'Skyr');
    await userEvent.type(screen.getByLabelText('Protéines'), '32');
    await userEvent.type(screen.getByLabelText('Sucres'), '12');
    await userEvent.type(screen.getByLabelText('Calories'), '480');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer comme récurrent' }));

    await waitFor(() => {
      const post = calls.find(
        (call) => call.url.includes('/favorites') && call.init?.method === 'POST',
      );
      expect(JSON.parse(post?.init?.body as string)).toMatchObject({
        name: 'Skyr',
        protein_g: 32,
        added_sugar_g: 12,
        calories: 480,
      });
    });
  });

  it('affiche les sucres d’un repas récurrent qui en porte', async () => {
    stub();
    renderNutrition();

    expect(await screen.findByText(/12 g sucres/)).toBeInTheDocument();
  });

  it('demande deux appuis pour retirer un repas récurrent', async () => {
    // Le projet n'a pas d'annulation, et le « ✕ » d'origine partait au premier appui —
    // sur une cible de 25 px de large.
    stub();
    renderNutrition();

    await userEvent.click(await screen.findByRole('button', { name: 'Retirer Skyr + flocons' }));

    expect(calls.some((call) => call.init?.method === 'DELETE')).toBe(false);

    await userEvent.click(
      screen.getByRole('button', { name: 'Retirer Skyr + flocons — confirmer' }),
    );

    await waitFor(() => {
      expect(calls.some((call) => call.init?.method === 'DELETE')).toBe(true);
    });
  });

  it('rejoue un repas récurrent en une action', async () => {
    // `NUT-10`.
    stub();
    renderNutrition();

    await userEvent.click(await screen.findByRole('button', { name: /Rejouer Skyr \+ flocons/ }));

    await waitFor(() => {
      const replay = calls.find((call) => call.url.includes('/favorites/f1/replay'));
      expect(replay?.init?.method).toBe('POST');
    });
  });

  it('renvoie le jeton de la ligne pour supprimer un repas', async () => {
    stub();
    renderNutrition();

    await userEvent.click(
      await screen.findByRole('button', { name: /Supprimer le repas de 12:30/ }),
    );

    await waitFor(() => {
      const remove = calls.find((call) => call.init?.method === 'DELETE');
      expect(remove?.url).toContain('/api/nutrition/1');
      expect((remove?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-b');
    });
  });

  it('affiche le message du serveur sur un fichier refusé', async () => {
    stub((url, init) =>
      init?.method === 'POST' && url === '/api/nutrition'
        ? json(422, {
            code: 'validation_error',
            message: "Ce fichier n'est pas une image reconnue (JPEG, PNG, WebP ou HEIC).",
          })
        : undefined,
    );
    renderNutrition();

    await openSheet('Description');
    await userEvent.type(screen.getByLabelText('Description'), 'x');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer le repas' }));

    expect(await screen.findByRole('alert')).toHaveTextContent("n'est pas une image reconnue");
  });

  it("reste lisible quand la journée n'a aucun repas", async () => {
    stub((url) =>
      url.includes('/api/nutrition') && !url.includes('photos')
        ? json(200, { ...VIEW, meals: [], totals: { ...VIEW.totals, meals: 0, calories: 0 } })
        : undefined,
    );
    renderNutrition();

    expect(await screen.findByText("Aucun repas aujourd'hui")).toBeInTheDocument();
  });
});
