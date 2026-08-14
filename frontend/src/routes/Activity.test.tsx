/**
 * L'écran Activité et ses deux sous-pages.
 *
 * Les trois routes sont montées ensemble et le rendu part de `/activite` : c'est la seule
 * façon d'éprouver ce que le lot a changé — que le catalogue et les statistiques soient
 * des **navigations**, avec une adresse et un retour, et non deux replis dans la page.
 * Un test qui monterait `Catalogue` seul passerait sans jamais vérifier qu'on peut y aller.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import { createQueryClient } from '@/lib/query';

import { Activity } from './Activity';
import { Catalogue } from './activity/Catalogue';
import { Stats } from './activity/Stats';

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
      duration_min: 78,
      distance_km: null,
      pace_min_km: null,
      rpe: 8,
      entries: 2,
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
      entries: 0,
      source: 'manual',
    },
    {
      kind: 'workout',
      id: 1,
      token: 'jeton-velo',
      date: '2026-07-18',
      label: 'vélo',
      duration_min: 45,
      distance_km: null,
      pace_min_km: null,
      rpe: null,
      entries: 0,
      source: 'manual',
    },
  ],
  total: 3,
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
  duration_min: 78,
  calories: null,
  rpe: 8,
  note: null,
  source: 'manual',
  exercises: [],
  volume_kg: 0,
};

/** Une seconde séance : sans elle, on ne peut pas éprouver le passage de l'une à l'autre. */
const VELO_DETAIL = {
  ...WORKOUT_DETAIL,
  id: 1,
  token: 'jeton-velo',
  workout_id: 'w2',
  date: '2026-07-18',
  type: 'vélo',
  duration_min: 45,
  rpe: null,
};

/** Trois exercices de trois groupes : c'est le minimum pour que chercher veuille dire
 *  quelque chose. Avec un seul, un filtre qui ne filtre rien passerait. */
const CATALOGUE = [
  {
    id: 0,
    token: 'jeton-ex',
    exercise_id: 'e1',
    name: 'Développé couché',
    muscle_group: 'pectoraux',
    entries: 4,
    last_weight_kg: 90,
    last_reps: 8,
    last_sets: 3,
    last_date: '2026-07-21',
  },
  {
    id: 1,
    token: 'jeton-tractions',
    exercise_id: 'e2',
    name: 'Tractions',
    muscle_group: 'dos',
    entries: 2,
    last_weight_kg: 0,
    last_reps: 10,
    last_sets: 4,
    last_date: '2026-07-14',
  },
  {
    id: 2,
    token: 'jeton-squat',
    exercise_id: 'e3',
    name: 'Squat',
    muscle_group: 'jambes',
    entries: 6,
    last_weight_kg: 100,
    last_reps: 5,
    last_sets: 5,
    last_date: '2026-07-10',
  },
];

function stub(custom?: (url: string, init?: RequestInit) => Response | undefined) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    const override = custom?.(url, init);
    if (override) return Promise.resolve(override);

    if (url.includes('/api/ai/status'))
      return Promise.resolve(json(200, { enabled: true, message: 'disponible' }));
    if (url.includes('/activity/progress')) return Promise.resolve(json(200, PROGRESS));
    if (url.includes('/activity/exercises')) return Promise.resolve(json(200, CATALOGUE));
    if (url.includes('/activity/types'))
      return Promise.resolve(json(200, ['musculation', 'vélo', 'yoga']));
    if (url.includes('/activity/muscle-groups'))
      return Promise.resolve(json(200, ['pectoraux', 'dos', 'jambes']));
    if (url.includes('/duplicate')) return Promise.resolve(json(201, WORKOUT_DETAIL));
    if (/\/activity\/workouts\/1$/.test(url)) return Promise.resolve(json(200, VELO_DETAIL));
    if (/\/activity\/workouts\/\d+$/.test(url)) return Promise.resolve(json(200, WORKOUT_DETAIL));
    if (url.endsWith('/api/activity')) return Promise.resolve(json(200, OVERVIEW));
    return Promise.resolve(json(200, {}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/**
 * Ouvre l'assistant de création sur une nature.
 *
 * Les deux boutons « Nouvelle séance » et « Nouvelle course » ont disparu de l'en-tête :
 * la question se pose maintenant en toutes lettres à la première étape.
 */
async function startActivity(kind: 'Séance' | 'Course') {
  await userEvent.click(await screen.findByRole('button', { name: 'Enregistrer une activité' }));
  await userEvent.click(await screen.findByRole('button', { name: kind }));
}

/** Les trois routes du domaine, montées ensemble. Naviguer entre elles est testable. */
function renderActivity(at = '/activite', client = createQueryClient()) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>
        <Toaster>
          <Routes>
            <Route path="/activite" element={<Activity />} />
            <Route path="/activite/catalogue" element={<Catalogue />} />
            <Route path="/activite/statistiques" element={<Stats />} />
          </Routes>
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * La ligne qui dit **quelle** séance le journal a ouverte — date, type, durée.
 *
 * Un matcher de fonction et non une chaîne : la date est dans un `<strong>`, donc le texte
 * est coupé en plusieurs nœuds et aucune recherche littérale ne le retrouve.
 */
function ouverte(): HTMLElement {
  return screen.getByText(
    (_text, element) =>
      element?.tagName === 'P' && /^\d{2}\/\d{2}\/\d{4} · /.test(element.textContent ?? ''),
  );
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('écran Activité', () => {
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

    await startActivity('Course');
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

    await startActivity('Course');
    await userEvent.click(await screen.findByRole('button', { name: 'Saisir à la main' }));
    await userEvent.type(await screen.findByLabelText('Temps'), "n'importe quoi");
    await userEvent.type(screen.getByLabelText('Distance (km)'), '8,4');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la course' }));

    expect(await screen.findByText(/n'est pas une durée/)).toBeInTheDocument();
  });

  it('renvoie le jeton de la ligne pour supprimer une activité', async () => {
    stub();
    renderActivity();

    // Deux appuis : le premier arme, le second exécute. Sans annulation dans le projet,
    // une suppression au doigt ne doit pas partir d'un geste unique.
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

  it('reste lisible quand rien n’a été enregistré', async () => {
    stub((url) =>
      url.endsWith('/api/activity') ? json(200, { ...OVERVIEW, history: [], total: 0 }) : undefined,
    );
    renderActivity();

    expect(await screen.findByText('Aucune activité')).toBeInTheDocument();
  });

  // ── Ce qui a quitté l'écran (C03) ───────────────────

  it('ne liste plus toutes les séances dans le journal', async () => {
    // La bande de pastilles portait une entrée par séance : elle grandissait sans fin, et
    // doublait l'historique qui se trouve juste dessous.
    stub();
    renderActivity();

    await screen.findByRole('heading', { name: 'Journal de séance' });

    expect(screen.queryByRole('group', { name: 'Séance' })).toBeNull();
  });

  it('n’affiche plus ni catalogue ni statistiques dans la page', async () => {
    stub();
    renderActivity();

    await screen.findByRole('heading', { name: 'Journal de séance' });

    expect(screen.queryByRole('list', { name: 'Exercices déclarés' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Tonnage par groupe' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Volume par jour' })).toBeNull();
  });

  it('porte les deux portes vers ce qui en est sorti', async () => {
    stub();
    renderActivity();

    expect(await screen.findByRole('link', { name: 'Catalogue' })).toHaveAttribute(
      'href',
      '/activite/catalogue',
    );
    expect(screen.getByRole('link', { name: 'Statistiques' })).toHaveAttribute(
      'href',
      '/activite/statistiques',
    );
  });

  // ── Le journal, toujours affiché ────────────────────

  it('affiche le journal sans qu’aucune séance ait été ouverte', async () => {
    // La dette relevée en usage réel : le panneau de saisie des charges n'existait que
    // pendant qu'une séance était active.
    stub();
    renderActivity();

    expect(await screen.findByLabelText('Exercice')).toBeInTheDocument();
    expect(screen.getByLabelText('Charge (kg)')).toBeInTheDocument();
  });

  it('présente le journal avant l’historique', async () => {
    // L'ordre affiché doit suivre l'ordre du geste : consigner une charge est quotidien,
    // relire son historique l'est moins.
    stub();
    renderActivity();

    const journal = await screen.findByRole('heading', { name: 'Journal de séance' });
    const historique = screen.getByRole('heading', { name: /^Historique/ });

    expect(
      journal.compareDocumentPosition(historique) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('ouvre d’office la séance la plus récente, et dit laquelle', async () => {
    // Sans la bande de pastilles, cette ligne est la **seule** chose qui dise dans quelle
    // séance la charge va s'écrire. Une erreur ici coûte une donnée fausse.
    stub();
    renderActivity();

    // La durée d'abord : la date seule apparaît aussi dans l'historique, et l'attendre
    // laisserait passer le test avant que la séance ne soit relue.
    expect(await screen.findByText(/1 h 18/)).toBeInTheDocument();
    expect(ouverte()).toHaveTextContent(/21\/07/);
    expect(ouverte()).toHaveTextContent(/musculation/);
  });

  it('dit quel est le prochain geste quand aucune séance n’existe', async () => {
    // Pas de formulaire de charge sans séance où la consigner : un champ inerte vaut
    // moins qu'une phrase qui dit ce que coûte le prochain geste.
    stub((url) =>
      url.endsWith('/api/activity')
        ? json(200, { ...OVERVIEW, history: [OVERVIEW.history[1]], total: 1 })
        : undefined,
    );
    renderActivity();

    expect(await screen.findByText('Aucune séance')).toBeInTheDocument();
    expect(screen.queryByLabelText('Charge (kg)')).toBeNull();
    // Et le journal ne promet pas d'ouvrir une séance qu'il n'a pas.
    expect(screen.queryByText(/ouverte d’office/)).toBeNull();
  });

  it('ouvre le journal sur la séance choisie depuis l’historique', async () => {
    // C'est la porte qui remplace la bande supprimée, et elle existait déjà.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Ouvrir la séance du 18/ }));

    expect(await screen.findByText(/45 min/)).toBeInTheDocument();
    expect(ouverte()).toHaveTextContent(/18\/07/);
  });

  it('n’emporte pas la charge tapée d’une séance à la suivante', async () => {
    stub();
    renderActivity();

    await userEvent.type(await screen.findByLabelText('Charge (kg)'), '80');
    await userEvent.click(screen.getByRole('button', { name: /Ouvrir la séance du 18/ }));
    await screen.findByText(/45 min/);

    expect(screen.getByLabelText('Charge (kg)')).toHaveValue('');
  });

  it('ouvre le journal sur une séance qui vient d’être créée', async () => {
    // L'historique n'a pas encore été relu à cet instant : sans le rattrapage, le journal
    // afficherait la séance précédente le temps d'un aller-retour.
    const CREATED = {
      ...WORKOUT_DETAIL,
      id: 7,
      workout_id: 'w7',
      date: '2026-07-26',
      type: 'yoga',
      duration_min: 30,
      rpe: null,
    };
    stub((url, init) => {
      if (init?.method === 'POST' && url.endsWith('/api/activity/workouts')) {
        return json(201, CREATED);
      }
      return /\/activity\/workouts\/7$/.test(url) ? json(200, CREATED) : undefined;
    });
    renderActivity();

    await startActivity('Séance');
    await userEvent.type(await screen.findByLabelText('Durée de séance'), '30');
    await userEvent.click(screen.getByRole('button', { name: 'Suivant' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Enregistrer sans exercice' }));

    expect(await screen.findByText(/30 min/)).toBeInTheDocument();
    expect(ouverte()).toHaveTextContent(/26\/07/);
  });

  // ── Choisir un exercice par la recherche (C03) ──────

  it('propose les exercices récents avant toute recherche', async () => {
    // Sans recherche, la liste n'est pas vide : elle porte ce qu'on a soulevé en dernier,
    // dans l'ordre où le serveur l'a daté.
    stub();
    renderActivity();

    const proposes = within(await screen.findByRole('group', { name: 'Exercices proposés' }));

    expect(proposes.getByRole('button', { name: /Développé couché/ })).toBeInTheDocument();
    expect(proposes.getByRole('button', { name: /Squat/ })).toBeInTheDocument();
  });

  it('cherche par nom, sans accent ni casse', async () => {
    stub();
    renderActivity();

    await userEvent.type(await screen.findByLabelText('Exercice'), 'developpe');
    const proposes = within(screen.getByRole('group', { name: 'Exercices proposés' }));

    expect(proposes.getByRole('button', { name: /Développé couché/ })).toBeInTheDocument();
    expect(proposes.queryByRole('button', { name: /Squat/ })).toBeNull();
  });

  it('cherche aussi par groupe musculaire', async () => {
    // Ce qui absorbe le filtre à pastilles au lieu de le doubler.
    stub();
    renderActivity();

    await userEvent.type(await screen.findByLabelText('Exercice'), 'dos');
    const proposes = within(screen.getByRole('group', { name: 'Exercices proposés' }));

    expect(proposes.getByRole('button', { name: /Tractions/ })).toBeInTheDocument();
    expect(proposes.queryByRole('button', { name: /Développé couché/ })).toBeNull();
  });

  it('garde l’exercice choisi visible quand la recherche ne le rend plus', async () => {
    // Sinon, taper une lettre de trop effacerait de l'écran ce sur quoi la charge va
    // s'écrire — alors que le formulaire, lui, le vise toujours.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Développé couché/ }));
    await userEvent.type(screen.getByLabelText('Exercice'), 'squat');

    expect(screen.getByRole('button', { name: /Développé couché/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('dit combien d’exercices la liste ne montre pas', async () => {
    // Le plafond s'appliquait avant le compte : sept au catalogue, six à l'écran, et le
    // reste valait toujours zéro. Le défaut est sorti d'une capture, pas d'un test —
    // celui-ci existe pour qu'il n'y revienne pas.
    stub((url) =>
      url.includes('/activity/exercises')
        ? json(
            200,
            Array.from({ length: 9 }, (_unused, index) => ({
              ...CATALOGUE[0],
              id: index,
              exercise_id: `x${String(index)}`,
              name: `Exercice ${String(index)}`,
              last_date: `2026-07-${String(10 + index).padStart(2, '0')}`,
            })),
          )
        : undefined,
    );
    renderActivity();

    await screen.findByRole('group', { name: 'Exercices proposés' });

    expect(screen.getByText(/3 autres au catalogue/)).toBeInTheDocument();
  });

  it('dit que rien ne correspond, sans prétendre que le catalogue est vide', async () => {
    stub();
    renderActivity();

    await userEvent.type(await screen.findByLabelText('Exercice'), 'zzzz');

    expect(screen.getByText(/aucun exercice ne correspond/)).toBeInTheDocument();
    expect(screen.queryByText(/catalogue vide/)).toBeNull();
  });

  it('consigne une charge sur l’exercice choisi', async () => {
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Développé couché/ }));
    await userEvent.type(screen.getByLabelText('Charge (kg)'), '80');
    await userEvent.click(screen.getByRole('button', { name: 'Consigner' }));

    await waitFor(() => {
      const post = calls.find(
        (call) => call.init?.method === 'POST' && call.url.includes('/workouts/0/exercises'),
      );
      expect(JSON.parse(post?.init?.body as string)).toMatchObject({
        exercise_id: 'e1',
        weight_kg: '80',
      });
    });
  });

  it('rappelle la dernière charge de l’exercice', async () => {
    // `ACT-08` : choisir sa charge sans consulter l'historique.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Développé couché/ }));

    expect(screen.getByText(/dernière fois : 90 kg · 3×8/)).toBeInTheDocument();
  });

  it('dit quoi faire quand le catalogue est vide', async () => {
    stub((url) => (url.includes('/activity/exercises') ? json(200, []) : undefined));
    renderActivity();

    expect(await screen.findByText(/catalogue vide — déclare un exercice/)).toBeInTheDocument();
  });

  // ── Au doigt (`L17-07`) ─────────────────────────────

  it('ajuste la charge par pas de 2,5 kg sans clavier', async () => {
    // Le pas d'un disque réel. Entre deux séries, on corrige d'un pouce.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Développé couché/ }));
    const charge = screen.getByLabelText('Charge (kg)');

    await userEvent.click(screen.getByRole('button', { name: 'Charge (kg) : augmenter' }));
    expect(charge).toHaveValue('0');

    await userEvent.clear(charge);
    await userEvent.type(charge, '82,5');
    await userEvent.click(screen.getByRole('button', { name: 'Charge (kg) : augmenter' }));
    expect(charge).toHaveValue('85');

    await userEvent.click(screen.getByRole('button', { name: 'Charge (kg) : diminuer' }));
    expect(charge).toHaveValue('82,5');
  });

  it('laisse le champ tranquille quand il ne reconnaît pas ce qui est écrit', async () => {
    // Le pas-à-pas n'est pas un second analyseur de saisie : « poids du corps » ne se
    // convertit pas ici, et il ne doit surtout pas être écrasé par un 0.
    stub();
    renderActivity();

    const charge = await screen.findByLabelText('Charge (kg)');
    await userEvent.type(charge, 'poids du corps');
    await userEvent.click(screen.getByRole('button', { name: 'Charge (kg) : augmenter' }));

    expect(charge).toHaveValue('0');
  });

  it('borne les séries au lieu de descendre sous une', async () => {
    stub();
    renderActivity();

    const moins = await screen.findByRole('button', { name: 'Séries : diminuer' });
    expect(screen.getByLabelText('Séries')).toHaveValue('3');

    await userEvent.click(moins);
    await userEvent.click(moins);
    await userEvent.click(moins);

    expect(screen.getByLabelText('Séries')).toHaveValue('1');
    expect(moins).toBeDisabled();
  });

  it('propose les charges réellement soulevées, pas des valeurs devinées', async () => {
    // `max_series` vient du serveur. Une pastille propose ce qui a existé — jamais un
    // arrondi ni une progression supposée.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Développé couché/ }));
    const recentes = within(screen.getByRole('group', { name: 'Charges récentes' }));

    expect(recentes.getByRole('button', { name: '90 kg' })).toBeInTheDocument();
    expect(recentes.getByRole('button', { name: '85 kg' })).toBeInTheDocument();

    await userEvent.click(recentes.getByRole('button', { name: '85 kg' }));
    expect(screen.getByLabelText('Charge (kg)')).toHaveValue('85');
  });

  it('consigne une charge choisie entièrement au doigt', async () => {
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Développé couché/ }));
    await userEvent.click(
      within(screen.getByRole('group', { name: 'Charges récentes' })).getByRole('button', {
        name: '90 kg',
      }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Réps : augmenter' }));
    await userEvent.click(screen.getByRole('button', { name: 'Consigner' }));

    await waitFor(() => {
      const post = calls.find(
        (call) => call.init?.method === 'POST' && call.url.includes('/workouts/0/exercises'),
      );
      expect(JSON.parse(post?.init?.body as string)).toMatchObject({
        exercise_id: 'e1',
        weight_kg: '90',
        sets: 3,
        reps: 9,
      });
    });
  });

  it('passe d’une séance à l’autre en balayant le journal', async () => {
    stub();
    renderActivity();

    await screen.findByText(/1 h 18/);
    const journal = screen.getByLabelText('Charge (kg)').closest('form') as HTMLElement;

    // Vers la gauche : on remonte le temps.
    await userEvent.pointer([
      { keys: '[TouchA>]', target: journal, coords: { x: 260, y: 120 } },
      { pointerName: 'TouchA', coords: { x: 120, y: 124 } },
      { keys: '[/TouchA]', target: journal, coords: { x: 120, y: 124 } },
    ]);

    expect(await screen.findByText(/45 min/)).toBeInTheDocument();
    expect(ouverte()).toHaveTextContent(/18\/07/);
  });

  it('ne balaye pas quand le doigt descend la page', async () => {
    // Sans cette garde, faire défiler la page déclencherait une navigation à chaque
    // écart latéral — et sur l'historique, cette navigation est une suppression.
    stub();
    renderActivity();

    await screen.findByText(/1 h 18/);
    const journal = screen.getByLabelText('Charge (kg)').closest('form') as HTMLElement;

    await userEvent.pointer([
      { keys: '[TouchA>]', target: journal, coords: { x: 260, y: 60 } },
      { pointerName: 'TouchA', coords: { x: 180, y: 300 } },
      { keys: '[/TouchA]', target: journal, coords: { x: 180, y: 300 } },
    ]);

    expect(screen.getByText(/1 h 18/)).toBeInTheDocument();
  });

  it('demande confirmation avant de supprimer une ligne glissée', async () => {
    stub();
    renderActivity();

    const supprimer = await screen.findByRole('button', { name: /^Supprimer la course du 20/ });
    await userEvent.click(supprimer);

    // Premier appui : rien n'est parti.
    expect(calls.some((call) => call.init?.method === 'DELETE')).toBe(false);
    expect(screen.getByText('Confirmer ?')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /du 20.*confirmer/ }));
    await waitFor(() => {
      expect(calls.some((call) => call.init?.method === 'DELETE')).toBe(true);
    });
  });

  it('dit pourquoi quand la séance ne peut pas être lue', async () => {
    // Le refus s'affiche à la place du journal, là où le regard est déjà. Porté par un
    // toast depuis le bouton « ouvrir », il passait avant d'avoir été lu.
    stub((url) =>
      /\/activity\/workouts\/0$/.test(url)
        ? json(404, { code: 'storage_not_found', message: "Cette séance n'existe pas." })
        : undefined,
    );
    renderActivity();

    expect(await screen.findByText("Cette séance n'existe pas.")).toBeInTheDocument();
  });

  it('referme le journal sur la séance précédente quand celle ouverte est supprimée', async () => {
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Ouvrir la séance du 18/ }));
    await screen.findByText(/45 min/);
    await userEvent.click(screen.getByRole('button', { name: /^Supprimer la séance du 18/ }));
    await userEvent.click(screen.getByRole('button', { name: /du 18.*confirmer/ }));

    expect(await screen.findByText(/1 h 18/)).toBeInTheDocument();
  });

  // ── Corriger, et ce que ça coûte ────────────────────

  it('dit combien de séries une suppression de séance emporte', async () => {
    // « Confirmer ? » emploie les mêmes mots qu'elle en emporte zéro ou douze : le coût
    // se lit sur la ligne, avant que le geste ne s'arme.
    stub();
    renderActivity();

    expect(
      await screen.findByRole('button', { name: /^Supprimer la séance du 21.*2 séries/ }),
    ).toBeInTheDocument();
  });

  it('relit la séance avant de la corriger, et renvoie son jeton', async () => {
    // L'historique ne porte ni la note ni l'effort perçu : les corriger à l'aveugle les
    // effacerait. La relecture rend au passage un jeton frais pour la garde.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Corriger la séance du 21/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Corriger la séance' }));

    await waitFor(() => {
      const patch = calls.find((call) => call.init?.method === 'PATCH');
      expect(patch?.url).toContain('/api/activity/workouts/0');
      expect((patch?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-seance');
    });
  });

  it('corrige une course par la même feuille que la séance', async () => {
    stub((url) =>
      /\/activity\/runs\/0$/.test(url)
        ? json(200, {
            id: 0,
            token: 'jeton-course',
            date: MONDAY,
            distance_km: 8.4,
            duration_min: 44.2,
            pace_min_km: 5.262,
            speed_kmh: 11.4,
            avg_hr: 152,
            elevation_m: null,
            note: null,
            source: 'manual',
          })
        : undefined,
    );
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Corriger la course du 20/ }));

    // La feuille repart des valeurs de la ligne, y compris celles que l'historique ne
    // porte pas.
    expect(await screen.findByLabelText('FC moyenne')).toHaveValue('152');
    expect(screen.getByLabelText('Distance')).toHaveValue('8,4');
  });

  it('charge une série dans le formulaire quand on appuie sur sa ligne', async () => {
    stub((url) =>
      /\/activity\/workouts\/0$/.test(url)
        ? json(200, {
            ...WORKOUT_DETAIL,
            exercises: [
              {
                id: 3,
                token: 'jeton-serie',
                workout_id: 'w1',
                date: '2026-07-21',
                exercise_id: 'e1',
                exercise_name: 'Développé couché',
                muscle_group: 'pectoraux',
                weight_kg: 80,
                sets: 3,
                reps: 8,
                note: null,
                volume_kg: 1920,
                one_rep_max_kg: 100,
              },
            ],
          })
        : undefined,
    );
    renderActivity();

    await userEvent.click(
      await screen.findByRole('button', { name: /^Corriger la série — Développé couché, 80 kg/ }),
    );

    expect(screen.getByLabelText('Charge (kg)')).toHaveValue('80');
    // Ce que la correction remplace, sous les yeux jusqu'à l'envoi.
    expect(screen.getByText(/était : Développé couché, 80 kg, 3×8/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Corriger la série' }));

    await waitFor(() => {
      const patch = calls.find((call) => call.init?.method === 'PATCH');
      expect(patch?.url).toContain('/api/activity/exercise-log/3');
      expect((patch?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-serie');
    });
  });

  it('reprend les séries et les réps réellement soulevées la dernière fois', async () => {
    // Le formulaire partait de « 3×8 » écrit en dur — deux valeurs que personne n'avait
    // jamais soulevées. Le catalogue rend les vraies (`ACT-08`).
    stub((url) =>
      url.includes('/activity/exercises')
        ? json(200, [{ ...CATALOGUE[0], last_sets: 5, last_reps: 5 }])
        : undefined,
    );
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: /Développé couché/ }));

    expect(screen.getByLabelText('Séries')).toHaveValue('5');
    expect(screen.getByLabelText('Réps')).toHaveValue('5');
    // La charge, elle, reste vide : c'est elle qui progresse.
    expect(screen.getByLabelText('Charge (kg)')).toHaveValue('');
  });

  // ── L'assistant par étapes (C06) ───────────────────

  it('demande la nature avant quoi que ce soit d’autre', async () => {
    // Deux boutons en en-tête obligeaient à trancher avant d'avoir rien ouvert, et
    // laissaient deux cibles côte à côte dans 390 px.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('button', { name: 'Enregistrer une activité' }));

    expect(screen.getByRole('button', { name: 'Séance' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Course' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Durée de séance')).toBeNull();
  });

  it('revient en arrière sans rien écrire', async () => {
    stub();
    renderActivity();

    await startActivity('Séance');
    await userEvent.type(await screen.findByLabelText('Durée de séance'), '30');
    await userEvent.click(screen.getByRole('button', { name: 'Retour' }));

    expect(screen.getByRole('button', { name: 'Course' })).toBeInTheDocument();
    expect(calls.filter((call) => call.init?.method === 'POST')).toHaveLength(0);
  });

  it('écrit la séance et ses exercices en un seul appel', async () => {
    // C'est ce qui fait qu'abandonner à l'étape 2 ne laisse pas de séance vide dans
    // l'historique.
    stub();
    renderActivity();

    await startActivity('Séance');
    await userEvent.type(await screen.findByLabelText('Durée de séance'), '1h15');
    await userEvent.click(screen.getByRole('button', { name: 'Suivant' }));

    // L'assistant est une feuille posée **par-dessus** le journal, qui porte son propre
    // sélecteur d'exercice : la requête se limite au dialogue.
    const wizard = within(await screen.findByRole('dialog'));
    await userEvent.click(await wizard.findByRole('button', { name: /Développé couché/ }));
    await userEvent.type(wizard.getByLabelText('Charge (kg)'), '60');
    await userEvent.click(wizard.getByRole('button', { name: 'Ajouter à la séance' }));
    await userEvent.click(wizard.getByRole('button', { name: /Enregistrer la séance/ }));

    await waitFor(() => {
      const posts = calls.filter((call) => call.init?.method === 'POST');
      expect(posts).toHaveLength(1);
      const body = JSON.parse(posts[0]?.init?.body as string) as Record<string, unknown>;
      expect(body.duration_min).toBe('1h15');
      expect(body.exercises).toMatchObject([{ exercise_id: 'e1', weight_kg: '60' }]);
    });
  });

  it('n’envoie que l’allure quand c’est elle qu’on a corrigée', async () => {
    // Distance et allure sont liées par la durée, et le serveur calcule celle qui manque.
    // Envoyer les deux ferait trancher sa règle à l'aveugle.
    stub();
    renderActivity();

    await startActivity('Course');
    await userEvent.click(await screen.findByRole('button', { name: 'Saisir à la main' }));
    await userEvent.type(await screen.findByLabelText('Temps'), '45');
    await userEvent.type(screen.getByLabelText('Distance (km)'), '8');
    await userEvent.type(screen.getByLabelText('Allure (min/km)'), '5:00');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer la course' }));

    await waitFor(() => {
      const post = calls.find((call) => call.init?.method === 'POST');
      const body = JSON.parse(post?.init?.body as string) as Record<string, unknown>;
      expect(body.pace_min_km).toBe('5:00');
      expect(body.distance_km).toBeNull();
    });
  });

  it('refuse d’enregistrer une course sans distance ni allure', async () => {
    stub();
    renderActivity();

    await startActivity('Course');
    await userEvent.click(await screen.findByRole('button', { name: 'Saisir à la main' }));
    await userEvent.type(await screen.findByLabelText('Temps'), '45');

    expect(screen.getByRole('button', { name: 'Enregistrer la course' })).toBeDisabled();
    expect(screen.getByText(/Il manque encore la distance, ou l’allure/)).toBeInTheDocument();
  });

  // ── La lecture de notes (C07) ──────────────────────

  it('ne valide aucune ligne toute seule', async () => {
    // Le contrat du lot : aucune entrée du catalogue créée, renommée ou fusionnée sans
    // validation explicite.
    stub((url, init) =>
      url.includes('/activity/notes/read') && init?.method === 'POST'
        ? json(200, {
            source_text: 'dev couché 4x8 60kg',
            lines: [
              {
                name: 'Développé couché',
                muscle_group: 'pectoraux',
                sets: 4,
                reps: 8,
                weight_kg: 60,
                note: null,
                status: 'alias',
                exercise_id: 'e1',
                alias_of: 'dev couché',
              },
              {
                name: 'Hip thrust',
                muscle_group: 'fessiers',
                sets: 3,
                reps: 12,
                weight_kg: null,
                note: 'charge en lbs, non convertie',
                status: 'new',
                exercise_id: null,
                alias_of: null,
              },
            ],
          })
        : undefined,
    );
    renderActivity();

    await startActivity('Séance');
    await userEvent.type(await screen.findByLabelText('Durée de séance'), '1h');
    await userEvent.click(screen.getByRole('button', { name: 'Suivant' }));
    await userEvent.click(
      await screen.findByRole('button', {
        name: 'Saisir la séance depuis des notes ou une photo',
      }),
    );
    await userEvent.type(screen.getByLabelText('Tes notes'), 'dev couché 4x8 60kg');
    await userEvent.click(screen.getByRole('button', { name: 'Lire' }));

    // Les deux lignes portent leur coût, et chacune son propre bouton.
    expect(await screen.findByText('à rapprocher')).toBeInTheDocument();
    expect(screen.getByText('à créer')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Rapprocher dev couché de Développé couché' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Créer Hip thrust au catalogue' }),
    ).toBeInTheDocument();

    // Rien n'a été écrit : ni alias, ni exercice.
    expect(calls.some((call) => call.url.includes('/aliases'))).toBe(false);
    expect(
      calls.some((call) => call.url.endsWith('/exercises') && call.init?.method === 'POST'),
    ).toBe(false);
    // Et aucune ligne n'est prête tant que rien n'est validé.
    expect(screen.getByRole('button', { name: 'Valide au moins une ligne' })).toBeDisabled();
  });

  it('dit qu’une charge en livres n’est pas convertie', async () => {
    // Convertir une lecture de modèle produirait un nombre que personne n'a soulevé.
    stub((url) =>
      url.includes('/activity/notes/read')
        ? json(200, {
            source_text: 'hip thrust 3x12 135 lbs',
            lines: [
              {
                name: 'Hip thrust',
                muscle_group: 'fessiers',
                sets: 3,
                reps: 12,
                weight_kg: null,
                note: 'charge en lbs, non convertie',
                status: 'new',
                exercise_id: null,
                alias_of: null,
              },
            ],
          })
        : undefined,
    );
    renderActivity();

    await startActivity('Séance');
    await userEvent.type(await screen.findByLabelText('Durée de séance'), '1h');
    await userEvent.click(screen.getByRole('button', { name: 'Suivant' }));
    await userEvent.click(
      await screen.findByRole('button', {
        name: 'Saisir la séance depuis des notes ou une photo',
      }),
    );
    await userEvent.type(screen.getByLabelText('Tes notes'), 'hip thrust 3x12 135 lbs');
    await userEvent.click(screen.getByRole('button', { name: 'Lire' }));

    expect(await screen.findByText(/charge en lbs, non convertie/)).toBeInTheDocument();
  });

  // ── Le jour vient du serveur ────────────────────────

  it('date la saisie avec le jour du serveur, pas celui du téléphone', async () => {
    stub();
    renderActivity();

    await startActivity('Séance');

    expect(await screen.findByLabelText('Date de séance')).toHaveValue('2026-07-26');
  });
});

describe('catalogue d’exercices', () => {
  it('s’ouvre depuis le journal quand un exercice manque', async () => {
    // Le découvrir en pleine séance demandait de descendre l'écran, de le déclarer, de
    // remonter et de le re-choisir. C'est une navigation : « précédent » ramène au
    // journal, avec la séance ouverte et les champs intacts.
    stub();
    renderActivity();

    await userEvent.click(await screen.findByRole('link', { name: 'Déclarer un exercice' }));

    expect(await screen.findByRole('list', { name: 'Exercices déclarés' })).toBeInTheDocument();
  });

  it('porte son bouton d’ajout d’emblée, avant la liste', async () => {
    // Le critère du lot : atteignable sans défiler. Il est dans l'en-tête, donc avant la
    // liste dans le document — ce qui se vérifie, contrairement à une hauteur en pixels.
    stub();
    renderActivity('/activite/catalogue');

    const ajouter = await screen.findByRole('button', { name: 'Ajouter un exercice' });
    const liste = await screen.findByRole('list', { name: 'Exercices déclarés' });

    expect(ajouter.compareDocumentPosition(liste) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('n’affiche le formulaire qu’après l’appui, avec ses deux champs', async () => {
    stub();
    renderActivity('/activite/catalogue');

    await userEvent.click(await screen.findByRole('button', { name: 'Ajouter un exercice' }));

    expect(screen.getByLabelText('Nom')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Groupe musculaire' })).toBeInTheDocument();
  });

  it('montre les exercices déclarés et ce qu’un retrait laisserait', async () => {
    stub();
    renderActivity('/activite/catalogue');

    const liste = await screen.findByRole('list', { name: 'Exercices déclarés' });
    expect(within(liste).getByText(/4 séries · dernière 90 kg/)).toBeInTheDocument();
  });

  it('renvoie le jeton de la ligne pour corriger un exercice', async () => {
    stub();
    renderActivity('/activite/catalogue');

    await userEvent.click(await screen.findByRole('button', { name: 'Corriger Développé couché' }));
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer' }));

    await waitFor(() => {
      const patch = calls.find((call) => call.init?.method === 'PATCH');
      expect(patch?.url).toContain('/api/activity/exercises/0');
      expect((patch?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-ex');
    });
  });

  it('annonce ce qu’une correction de catalogue répercute', async () => {
    // Rien ne la défait : ce que le geste touche se dit avant le geste.
    stub();
    renderActivity('/activite/catalogue');

    await userEvent.click(await screen.findByRole('button', { name: 'Corriger Développé couché' }));

    expect(screen.getByText(/met aussi à jour les 4 séries déjà consignées/)).toBeInTheDocument();
  });

  it('demande deux appuis pour retirer un exercice du catalogue', async () => {
    stub();
    renderActivity('/activite/catalogue');

    await userEvent.click(
      await screen.findByRole('button', { name: 'Retirer Développé couché du catalogue' }),
    );

    // Premier appui : rien n'est parti.
    expect(calls.some((call) => call.init?.method === 'DELETE')).toBe(false);

    await userEvent.click(
      screen.getByRole('button', { name: /Retirer Développé couché du catalogue — confirmer/ }),
    );

    await waitFor(() => {
      const remove = calls.find((call) => call.init?.method === 'DELETE');
      expect(remove?.url).toContain('/api/activity/exercises/0');
      expect((remove?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-ex');
    });
  });

  it('dit quoi faire quand il est vide', async () => {
    stub((url) => (url.includes('/activity/exercises') ? json(200, []) : undefined));
    renderActivity('/activite/catalogue');

    expect(await screen.findByText('Catalogue vide')).toBeInTheDocument();
  });

  it('ramène à l’activité', async () => {
    stub();
    renderActivity('/activite/catalogue');

    expect(await screen.findByRole('link', { name: 'Retour à l’activité' })).toHaveAttribute(
      'href',
      '/activite',
    );
  });
});

describe('statistiques d’activité', () => {
  it('affiche les totaux de la semaine calculés par le serveur', async () => {
    stub();
    renderActivity('/activite/statistiques');

    expect(await screen.findByText(/semaine du 20\/07/)).toBeInTheDocument();
    expect(screen.getByText('2 h 32')).toBeInTheDocument();
    expect(screen.getByText(/allure 5:18/)).toBeInTheDocument();
  });

  it('trace un jour de repos autrement quun jour à zéro', async () => {
    // `ACT-10` : un jour de repos est un choix, pas un trou de données.
    stub();
    renderActivity('/activite/statistiques');

    expect(await screen.findAllByText('repos')).toHaveLength(4);
  });

  it('distingue « jamais travaillé » de « il y a longtemps »', async () => {
    // `ACT-16` : une valeur inventée fausserait la génération IA de planning.
    stub();
    renderActivity('/activite/statistiques');

    expect(await screen.findByText(/dos · jamais/)).toBeInTheDocument();
    expect(screen.getByText(/jambes · 20 j/)).toBeInTheDocument();
  });

  it('affiche la progression des charges avec son écart', async () => {
    stub();
    renderActivity('/activite/statistiques');

    expect(await screen.findByText(/90 kg \(\+5\)/)).toBeInTheDocument();
  });

  it('n’invente rien quand la semaine est vide', async () => {
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
          })
        : undefined,
    );
    renderActivity('/activite/statistiques');

    expect(await screen.findByText('aucun exercice consigné cette semaine')).toBeInTheDocument();
    expect(screen.getByText('aucune course')).toBeInTheDocument();
    // Un tonnage absent est un tiret, jamais un zéro qui passerait pour une mesure.
    expect(screen.getByText('aucune charge consignée')).toBeInTheDocument();
  });

  it('dit pourquoi quand le serveur ne répond pas', async () => {
    stub((url) =>
      url.endsWith('/api/activity')
        ? json(503, { code: 'storage_unavailable', message: 'Le stockage est injoignable.' })
        : undefined,
    );
    // Une panne de stockage est passagère : le client la rejoue avant d'abandonner
    // (`STO-08`). Ce test ne s'intéresse qu'à l'état terminal, il coupe donc les
    // tentatives plutôt que d'attendre leur temporisation.
    const client = createQueryClient();
    client.setDefaultOptions({ queries: { retry: false } });
    renderActivity('/activite/statistiques', client);

    expect(await screen.findByText('Le stockage est injoignable.')).toBeInTheDocument();
  });

  it('ramène à l’activité', async () => {
    stub();
    renderActivity('/activite/statistiques');

    expect(await screen.findByRole('link', { name: 'Retour à l’activité' })).toHaveAttribute(
      'href',
      '/activite',
    );
  });
});
