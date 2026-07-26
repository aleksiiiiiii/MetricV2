import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
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
    { date: '2026-07-22', weekday: 3, minutes: 32.67, rest: false },
    { date: '2026-07-23', weekday: 4, minutes: 0, rest: true },
    { date: '2026-07-24', weekday: 5, minutes: 0, rest: true },
    { date: '2026-07-25', weekday: 6, minutes: 0, rest: true },
    { date: '2026-07-26', weekday: 7, minutes: 0, rest: true },
  ],
  weeks: [],
  muscles: [
    { muscle_group: 'pectoraux', volume_kg: 1920, sets: 3 },
    { muscle_group: 'jambes', volume_kg: 2500, sets: 5 },
  ],
  neglected: [
    { muscle_group: 'dos', days_since: null, last_date: null },
    { muscle_group: 'jambes', days_since: 20, last_date: '2026-07-06' },
    { muscle_group: 'pectoraux', days_since: 2, last_date: '2026-07-24' },
  ],
  history: [
    {
      kind: 'workout',
      id: 0,
      token: 'jeton-seance',
      date: '2026-07-21',
      label: 'musculation',
      duration_min: 75,
      distance_km: null,
      pace_min_km: null,
      rpe: 8,
      source: 'manual',
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
      source: 'manual',
    },
  ],
  total: 2,
};

const PROGRESS = [
  {
    exercise_id: 'e1',
    name: 'Développé couché',
    muscle_group: 'pectoraux',
    last_weight_kg: 90,
    last_date: '2026-07-21',
    delta_kg: 5,
    max_series: [85, 90],
    dates: ['2026-07-14', '2026-07-21'],
    best_weight_kg: 90,
    best_one_rep_max_kg: 114,
  },
];

const WORKOUT_DETAIL = {
  id: 0,
  token: 'jeton-seance',
  workout_id: 'w1',
  date: '2026-07-21',
  type: 'musculation',
  duration_min: 75,
  calories: null,
  rpe: 8,
  note: null,
  source: 'manual',
  exercises: [],
  volume_kg: 0,
};

const CATALOGUE = [
  {
    id: 0,
    token: 'jeton-ex',
    exercise_id: 'e1',
    name: 'Développé couché',
    muscle_group: 'pectoraux',
    last_weight_kg: 90,
    last_reps: 8,
    last_sets: 3,
    last_date: '2026-07-21',
  },
];

function stub(custom?: (url: string, init?: RequestInit) => Response | undefined) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    const override = custom?.(url, init);
    if (override) return Promise.resolve(override);

    if (url.includes('/activity/progress')) return Promise.resolve(json(200, PROGRESS));
    if (url.includes('/activity/exercises')) return Promise.resolve(json(200, CATALOGUE));
    if (url.includes('/activity/types'))
      return Promise.resolve(json(200, ['musculation', 'vélo', 'yoga']));
    if (url.includes('/activity/muscle-groups'))
      return Promise.resolve(json(200, ['pectoraux', 'dos', 'jambes']));
    if (url.includes('/duplicate')) return Promise.resolve(json(201, WORKOUT_DETAIL));
    if (/\/activity\/workouts\/\d+$/.test(url)) return Promise.resolve(json(200, WORKOUT_DETAIL));
    if (url.endsWith('/api/activity')) return Promise.resolve(json(200, OVERVIEW));
    return Promise.resolve(json(200, {}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderActivity() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Toaster>
          <Activity />
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
  it('affiche les totaux de la semaine calculés par le serveur', async () => {
    stub();
    renderActivity();

    expect(await screen.findByText(/semaine du 20\/07/)).toBeInTheDocument();
    expect(screen.getByText('2 h 32')).toBeInTheDocument();
    expect(screen.getByText(/allure 5:18/)).toBeInTheDocument();
  });

  it('trace un jour de repos autrement quun jour à zéro', async () => {
    // `ACT-10` : un jour de repos est un choix, pas un trou de données.
    stub();
    renderActivity();

    expect(await screen.findAllByText('repos')).toHaveLength(4);
  });

  it('distingue « jamais travaillé » de « il y a longtemps »', async () => {
    // `ACT-16` : une valeur inventée fausserait la génération IA de planning.
    stub();
    renderActivity();

    expect(await screen.findByText(/dos · jamais/)).toBeInTheDocument();
    expect(screen.getByText(/jambes · 20 j/)).toBeInTheDocument();
  });

  it('fusionne courses et séances dans un historique unique', async () => {
    stub();
    renderActivity();

    expect(await screen.findByText('musculation')).toBeInTheDocument();
    expect(screen.getByText('Course')).toBeInTheDocument();
    expect(screen.getByText('8,4 km')).toBeInTheDocument();
    expect(screen.getByText('5:16')).toBeInTheDocument();
  });

  it('envoie la durée en texte pour que le serveur la normalise', async () => {
    // `ACT-01` : un second analyseur côté client finirait par diverger.
    stub();
    renderActivity();

    await userEvent.type(await screen.findByLabelText('Distance'), '8,40');
    await userEvent.type(screen.getByLabelText('Durée'), '44:12');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la course' }));

    await waitFor(() => {
      const post = calls.find((call) => call.init?.method === 'POST');
      const body = JSON.parse(post?.init?.body as string) as Record<string, unknown>;
      expect(body.distance_km).toBe('8,40');
      expect(body.duration_min).toBe('44:12');
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

    await userEvent.type(await screen.findByLabelText('Distance'), '8,4');
    await userEvent.type(screen.getByLabelText('Durée'), "n'importe quoi");
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la course' }));

    expect(await screen.findByText(/n'est pas une durée/)).toBeInTheDocument();
  });

  it('rappelle la dernière performance à la sélection d’un exercice', async () => {
    // `ACT-08` : choisir sa charge sans consulter l'historique.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Ouvrir la séance du 21/ }));
    await userEvent.selectOptions(await screen.findByLabelText('Exercice'), 'e1');

    expect(await screen.findByText(/dernière fois : 90 kg · 3×8/)).toBeInTheDocument();
  });

  it('renvoie le jeton de la ligne pour supprimer une activité', async () => {
    stub();
    renderActivity();

    await userEvent.click(
      await screen.findByRole('button', { name: /Supprimer l'activité du 20/ }),
    );

    await waitFor(() => {
      const remove = calls.find((call) => call.init?.method === 'DELETE');
      expect(remove?.url).toContain('/api/activity/runs/0');
      expect((remove?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-course');
    });
  });

  it('duplique une séance vers aujourd’hui', async () => {
    // `ACT-17` : une répétition de routine devient une action au lieu d'une dizaine.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Dupliquer la séance du 21/ }));

    await waitFor(() => {
      const post = calls.find((call) => call.url.includes('/duplicate'));
      expect(post).toBeDefined();
      expect(JSON.parse(post?.init?.body as string)).toHaveProperty('date');
    });
  });

  it('ne propose la duplication que pour les séances', async () => {
    // Dupliquer une course n'aurait pas de sens : la distance et le temps sont vécus.
    stub();
    renderActivity();

    await screen.findByText('Course');

    expect(screen.queryByRole('button', { name: /Dupliquer la séance du 20/ })).toBeNull();
  });

  it('affiche la progression des charges avec son écart', async () => {
    stub();
    renderActivity();

    expect(await screen.findByText(/90 kg \(\+5\)/)).toBeInTheDocument();
  });

  it('reste lisible quand rien n’a été enregistré', async () => {
    stub((url) =>
      url.endsWith('/api/activity')
        ? json(200, {
            ...OVERVIEW,
            week: {
              week_start: MONDAY,
              minutes: 0,
              sessions: 0,
              distance_km: 0,
              pace_min_km: null,
            },
            muscles: [],
            history: [],
            total: 0,
          })
        : undefined,
    );
    renderActivity();

    expect(await screen.findByText('Aucune activité')).toBeInTheDocument();
    expect(screen.getByText('aucun exercice consigné cette semaine')).toBeInTheDocument();
    expect(screen.getByText('aucune course')).toBeInTheDocument();
  });
});
