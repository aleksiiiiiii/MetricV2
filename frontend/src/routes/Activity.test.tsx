/**
 * L'écran Activité, après la phase 5.
 *
 * Le fichier en couvrait trois — l'écran, le catalogue, les statistiques — et pesait
 * 1 324 lignes. Les deux sous-pages ont disparu avec `exercise_log.csv`, et avec elles la
 * moitié des cas : le journal série par série, la duplication d'une séance, la bande de
 * pastilles. Ce qui reste tient l'écran tel qu'il est aujourd'hui.
 *
 * **Ce que ces tests défendent en propre** : l'historique fusionné est devenu la seule
 * réponse à « qu'est-ce que j'ai fait la semaine dernière », et la suppression d'une
 * séance tabata est ce qui autorise « je l'ai fait » à écrire sans rien demander.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import { createQueryClient } from '@/lib/query';

import { Activity } from './Activity';

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

const MONDAY = '2026-07-20';

const OVERVIEW = {
  today: '2026-07-26',
  week: {
    week_start: MONDAY,
    minutes: 151.87,
    sessions: 3,
    distance_km: 14.5,
    pace_min_km: 5.3,
  },
  days: [
    { date: MONDAY, weekday: 1, minutes: 44.2, rest: false },
    { date: '2026-07-21', weekday: 2, minutes: 75, rest: false },
  ],
  weeks: [],
  neglected: [{ muscle_group: 'dos', days_since: null, last_date: null }],
  history: [
    {
      // Une séance tabata déclarée faite : `entries` porte ses **rounds**.
      kind: 'workout',
      id: 0,
      token: 'jeton-seance',
      date: '2026-07-21',
      label: 'Haut du corps',
      duration_min: 18,
      distance_km: null,
      pace_min_km: null,
      rpe: 8,
      entries: 4,
      source: 'cadence',
    },
    {
      kind: 'run',
      id: 0,
      token: 'jeton-course',
      date: MONDAY,
      label: 'Course',
      duration_min: 44.2,
      distance_km: 8.4,
      pace_min_km: 5.262,
      rpe: null,
      entries: 0,
      source: 'manual',
    },
  ],
  total: 2,
};

function stub(custom?: (url: string, init?: RequestInit) => Response | undefined) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    const override = custom?.(url, init);
    if (override) return Promise.resolve(override);

    if (url.includes('/api/ai/status'))
      return Promise.resolve(json(200, { enabled: true, message: 'disponible' }));
    if (url.includes('/activity/circuits')) return Promise.resolve(json(200, { items: [] }));
    if (url.endsWith('/api/activity')) return Promise.resolve(json(200, OVERVIEW));
    return Promise.resolve(json(200, {}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderActivity(client = createQueryClient()) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/activite']}>
        <Toaster>
          <Routes>
            <Route path="/activite" element={<Activity />} />
          </Routes>
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

describe('écran Activité', () => {
  it('fusionne courses et séances tabata dans un historique unique', async () => {
    stub();
    renderActivity();

    await screen.findByText('Haut du corps');

    // Dans la liste, et non dans la page : « Course » y est aussi le titre de la section
    // de saisie, juste au-dessus.
    const history = within(screen.getByRole('list', { name: 'Historique des activités' }));
    expect(history.getByText('Haut du corps')).toBeInTheDocument();
    expect(history.getByText('Course')).toBeInTheDocument();
    expect(history.getByText('8,4 km')).toBeInTheDocument();
    expect(history.getByText('5:16')).toBeInTheDocument();
  });

  it('compte les rounds d’une séance, et non des séries', async () => {
    // La réponse porte les rounds ; les appeler « séries » afficherait un nombre juste
    // sous un mot faux, ce que personne ne vient corriger.
    stub();
    renderActivity();

    expect(await screen.findByText('· 4 rounds')).toBeInTheDocument();
  });

  it('reste lisible quand rien n’a été enregistré', async () => {
    stub((url) =>
      url.endsWith('/api/activity') ? json(200, { ...OVERVIEW, history: [], total: 0 }) : undefined,
    );
    renderActivity();

    expect(await screen.findByText('Aucune activité')).toBeInTheDocument();
  });

  // ── Défaire une addition ────────────────────────────

  it('supprime une séance tabata par sa route, avec le jeton de la ligne', async () => {
    // Deux appuis : le premier arme, le second exécute. Sans annulation dans le projet,
    // une suppression au doigt ne doit pas partir d'un geste unique.
    stub();
    renderActivity();

    await userEvent.click(
      await screen.findByRole('button', { name: /^Supprimer la séance « Haut du corps » du 21/ }),
    );
    await userEvent.click(screen.getByRole('button', { name: /du 21.*confirmer/ }));

    await waitFor(() => {
      const remove = calls.find((call) => call.init?.method === 'DELETE');
      expect(remove?.url).toContain('/api/activity/sessions/0');
      expect((remove?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-seance');
    });
  });

  it('supprime une course par la sienne', async () => {
    stub();
    renderActivity();

    await userEvent.click(
      await screen.findByRole('button', { name: /^Supprimer la course du 20/ }),
    );
    await userEvent.click(screen.getByRole('button', { name: /du 20.*confirmer/ }));

    await waitFor(() => {
      const remove = calls.find((call) => call.init?.method === 'DELETE');
      expect(remove?.url).toContain('/api/activity/runs/0');
      expect((remove?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-course');
    });
  });

  it('n’annonce pas un nombre de séries que la réponse ne porte pas', async () => {
    stub();
    renderActivity();

    const remove = await screen.findByRole('button', {
      name: /^Supprimer la séance « Haut du corps » du 21/,
    });

    // « et ses séries » : le coût est nommé, le compte ne l'est pas — quatre est un
    // nombre de tours, pas de lignes de série.
    expect(remove).toHaveAccessibleName(/et ses séries$/);
  });

  // ── Ce qu'une séance n'offre pas ────────────────────

  it('n’offre ni ouvrir ni corriger sur une séance', async () => {
    // Il n'y a plus de journal à ouvrir, et le serveur n'a aucune route pour modifier une
    // séance : elle dit ce que Cadence a joué. Une puce qui ouvrirait une feuille vide
    // serait pire que son absence.
    stub();
    renderActivity();

    await screen.findByText('Haut du corps');

    expect(screen.queryByRole('button', { name: /Ouvrir la séance/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Corriger la séance/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Dupliquer la séance/ })).toBeNull();
  });

  it('garde le détail et la correction d’une course', async () => {
    stub();
    renderActivity();

    expect(
      await screen.findByRole('button', { name: /Voir le détail de la course du 20/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Corriger la course du 20/ })).toBeInTheDocument();
  });

  // ── Ce qui a quitté l'écran ─────────────────────────

  it('ne porte plus ni journal, ni catalogue, ni statistiques', async () => {
    stub();
    renderActivity();

    await screen.findByText('Haut du corps');

    expect(screen.queryByRole('heading', { name: 'Journal de séance' })).toBeNull();
    expect(screen.queryByRole('list', { name: 'Exercices déclarés' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Tonnage par groupe' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Catalogue' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Statistiques' })).toBeNull();
  });

  it('porte les portes vers les courses et les charges', async () => {
    stub();
    renderActivity();

    expect(await screen.findByRole('link', { name: 'Courses' })).toHaveAttribute(
      'href',
      '/activite/courses',
    );
    expect(screen.getByRole('link', { name: 'Charges' })).toHaveAttribute(
      'href',
      '/activite/charges',
    );
  });

  // ── La saisie d'une course ──────────────────────────

  it('ouvre l’assistant sans demander de quoi il s’agit', async () => {
    // L'étape « Course ou Séance ? » n'a plus qu'une réponse possible : la poser serait un
    // appui de plus pour rien.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: 'Enregistrer une course' }));

    expect(await screen.findByRole('button', { name: 'Saisir à la main' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Séance' })).toBeNull();
  });

  it('envoie la durée en texte pour que le serveur la normalise', async () => {
    // `ACT-01` : un second analyseur côté client finirait par diverger.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: 'Enregistrer une course' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Saisir à la main' }));
    await userEvent.type(await screen.findByLabelText('Temps'), '44:12');
    await userEvent.type(screen.getByLabelText('Distance (km)'), '8,40');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la course' }));

    await waitFor(() => {
      const post = calls.find((call) => call.init?.method === 'POST');
      const body = JSON.parse(post?.init?.body as string) as Record<string, unknown>;
      expect(body.distance_km).toBe('8,40');
      expect(body.duration_min).toBe('44:12');
      // L'allure n'est pas envoyée : c'est la distance qu'on a tapée, et le serveur en
      // déduira l'autre. Envoyer les deux ferait trancher sa règle à l'aveugle.
      expect(body.pace_min_km).toBeNull();
    });
  });

  it('affiche le message du serveur sur une durée inintelligible', async () => {
    stub((_url, init) =>
      init?.method === 'POST'
        ? json(422, {
            code: 'validation_error',
            message: 'Les données envoyées sont invalides.',
            fields: [
              { field: 'body.duration_min', message: "« n'importe quoi » n'est pas une durée" },
            ],
          })
        : undefined,
    );
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: 'Enregistrer une course' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Saisir à la main' }));
    await userEvent.type(await screen.findByLabelText('Temps'), "n'importe quoi");
    await userEvent.type(screen.getByLabelText('Distance (km)'), '8,4');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la course' }));

    expect(await screen.findByText(/n'est pas une durée/)).toBeInTheDocument();
  });
});
