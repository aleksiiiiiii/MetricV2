import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import { createQueryClient } from '@/lib/query';

import { Body } from './Body';

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

const WEIGHT_VIEW = {
  stats: {
    latest_kg: 68.4,
    latest_date: '2026-07-20',
    change_kg: -2.1,
    to_target_kg: -1.6,
    target_kg: 70,
    min_kg: 68.4,
    max_kg: 70.0,
    amplitude_kg: 1.6,
    count: 2,
  },
  series: [
    { date: '2026-07-18', weight_kg: 70.0, trend_kg: 70.0 },
    { date: '2026-07-20', weight_kg: 68.4, trend_kg: 69.2 },
  ],
  entries: [
    {
      id: 1,
      token: 'jeton-b',
      date: '2026-07-20',
      weight_kg: 68.4,
      note: 'à jeun',
      source: 'manual',
    },
    { id: 0, token: 'jeton-a', date: '2026-07-18', weight_kg: 70.0, note: null, source: 'apple' },
  ],
  total: 2,
};

const MEASUREMENT_VIEW = {
  indicators: [
    {
      field: 'waist_cm',
      label: 'Taille',
      latest: 82,
      latest_date: '2026-07-20',
      delta: -1,
      direction: 'down',
      unit: 'cm',
    },
    {
      field: 'arm_cm',
      label: 'Bras',
      latest: null,
      latest_date: null,
      delta: null,
      direction: null,
      unit: 'cm',
    },
  ],
  entries: [],
  total: 0,
};

function stubApi(overrides: Partial<Record<string, Response>> = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    for (const [fragment, response] of Object.entries(overrides)) {
      if (url.includes(fragment) && response) return Promise.resolve(response);
    }
    if (url.includes('/body/measurements')) return Promise.resolve(json(200, MEASUREMENT_VIEW));
    if (url.includes('/body/weight')) return Promise.resolve(json(200, WEIGHT_VIEW));
    return Promise.resolve(json(200, {}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderBody() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Toaster>
          <Body />
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('écran Corps', () => {
  it('affiche les indicateurs calculés par le serveur', async () => {
    stubApi();
    renderBody();

    // Attendre un texte qui ne peut exister qu'une fois les données arrivées : un
    // libellé statique s'affiche avant la requête et ne prouverait rien.
    expect(await screen.findByText(/objectif 70 kg/)).toBeInTheDocument();
    expect(screen.getAllByText(/68,4/).length).toBeGreaterThan(0);
    expect(screen.getByText('−2,1')).toBeInTheDocument(); // variation sur 8 pesées
    expect(screen.getByText('−1,6')).toBeInTheDocument(); // écart à l'objectif
  });

  it("n'affiche aucune valeur inventée quand l'historique est vide", async () => {
    stubApi({
      '/body/weight': json(200, {
        stats: {
          latest_kg: null,
          latest_date: null,
          change_kg: null,
          to_target_kg: null,
          target_kg: 70,
          min_kg: null,
          max_kg: null,
          amplitude_kg: null,
          count: 0,
        },
        series: [],
        entries: [],
        total: 0,
      }),
    });
    renderBody();

    expect(await screen.findByText('Aucune pesée')).toBeInTheDocument();
    expect(screen.getByText('Pas encore de courbe')).toBeInTheDocument();
  });

  it("distingue une valeur importée d'une saisie manuelle", async () => {
    stubApi();
    renderBody();

    expect(await screen.findByText('apple')).toBeInTheDocument();
  });

  it('trace la tendance sans la recalculer', async () => {
    // `HEAT-30` en esprit : la courbe de tendance vient du serveur.
    stubApi();
    renderBody();

    expect(await screen.findByRole('img', { name: /Poids/ })).toBeInTheDocument();
    expect(screen.getByText('Tendance 7 j')).toBeInTheDocument();
  });

  it('enregistre une pesée puis rafraîchit la vue', async () => {
    stubApi();
    renderBody();

    await userEvent.type(await screen.findByLabelText('Poids (kg)'), '67,9');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la pesée' }));

    await waitFor(() => {
      const post = calls.find((call) => call.init?.method === 'POST');
      expect(post).toBeDefined();
      expect(JSON.parse(post?.init?.body as string)).toMatchObject({ weight_kg: 67.9 });
    });
  });

  it('accepte la virgule décimale', async () => {
    // C'est ce qu'on tape naturellement en français.
    stubApi();
    renderBody();

    await userEvent.type(await screen.findByLabelText('Poids (kg)'), '68,25');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la pesée' }));

    await waitFor(() => {
      const post = calls.find((call) => call.init?.method === 'POST');
      expect(JSON.parse(post?.init?.body as string)).toMatchObject({ weight_kg: 68.25 });
    });
  });

  it('affiche le message du serveur sur une saisie refusée', async () => {
    stubApi({
      '/body/weight': json(200, WEIGHT_VIEW),
    });
    const fetchMock = stubApi();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = input as string;
      calls.push({ url, init });
      if (init?.method === 'POST') {
        return Promise.resolve(
          json(422, {
            code: 'validation_error',
            message: 'Les données envoyées sont invalides.',
            fields: [{ field: 'body.weight_kg', message: 'Doit être inférieur ou égal à 500' }],
          }),
        );
      }
      if (url.includes('/body/measurements')) return Promise.resolve(json(200, MEASUREMENT_VIEW));
      return Promise.resolve(json(200, WEIGHT_VIEW));
    });
    renderBody();

    await userEvent.type(await screen.findByLabelText('Poids (kg)'), '900');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la pesée' }));

    const alerts = await screen.findAllByRole('alert');
    expect(alerts.map((node) => node.textContent).join(' ')).toContain('invalides');
    // Le détail par champ permet de surligner le bon champ du formulaire (`API-06`).
    expect(await screen.findByText('Doit être inférieur ou égal à 500')).toBeInTheDocument();
  });

  it('renvoie le jeton de la ligne en If-Match pour supprimer', async () => {
    // Le cœur de `STO-05` vu du client : on supprime la ligne telle qu'on l'a lue.
    stubApi();
    renderBody();

    await userEvent.click(await screen.findByRole('button', { name: /Supprimer la pesée du 20/ }));

    await waitFor(() => {
      const remove = calls.find((call) => call.init?.method === 'DELETE');
      expect(remove?.url).toContain('/api/body/weight/1');
      expect((remove?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-b');
    });
  });

  it('bascule en correction avec les valeurs de la ligne visée', async () => {
    stubApi();
    renderBody();

    await userEvent.click(await screen.findByRole('button', { name: /Corriger la pesée du 20/ }));

    expect(screen.getByRole('heading', { name: 'Corriger la pesée' })).toBeInTheDocument();
    expect(screen.getByLabelText('Poids (kg)')).toHaveValue('68.4');
    expect(screen.getByLabelText('Note')).toHaveValue('à jeun');
  });

  it('corrige en renvoyant le jeton lu', async () => {
    stubApi();
    renderBody();

    await userEvent.click(await screen.findByRole('button', { name: /Corriger la pesée du 20/ }));
    const field = screen.getByLabelText('Poids (kg)');
    await userEvent.clear(field);
    await userEvent.type(field, '68,9');
    await userEvent.click(screen.getByRole('button', { name: 'Corriger la pesée' }));

    await waitFor(() => {
      const patch = calls.find((call) => call.init?.method === 'PATCH');
      expect(patch?.url).toContain('/api/body/weight/1');
      expect((patch?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-b');
      expect(JSON.parse(patch?.init?.body as string)).toMatchObject({ weight_kg: 68.9 });
    });
  });

  it('affiche les indicateurs de mensurations, mesure vide comprise', async () => {
    stubApi();
    renderBody();

    const label = await screen.findByText('Taille');
    const panel = label.closest('div')?.parentElement;
    expect(panel).not.toBeNull();
    // Les formateurs suppriment les zéros inutiles : « 82 » et non « 82,0 ».
    expect(within(panel as HTMLElement).getByText(/82/)).toBeInTheDocument();
    expect(within(panel as HTMLElement).getByText('−1 cm')).toBeInTheDocument();
    // Une mesure jamais prise s'annonce vide plutôt que zéro.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it("n'envoie que les mesures réellement renseignées", async () => {
    stubApi();
    renderBody();

    await userEvent.type(await screen.findByLabelText('Taille (cm)'), '81,5');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer les mensurations' }));

    await waitFor(() => {
      const post = calls.find(
        (call) => call.init?.method === 'POST' && call.url.includes('measurements'),
      );
      const body = JSON.parse(post?.init?.body as string) as Record<string, unknown>;
      expect(body).toMatchObject({ waist_cm: 81.5 });
      expect(body).not.toHaveProperty('arm_cm');
    });
  });
});
