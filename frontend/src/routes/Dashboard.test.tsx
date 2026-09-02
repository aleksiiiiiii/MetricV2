import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import type { MetricDescriptor, SeriesView } from '@/features/aggregates/api';
import { createQueryClient } from '@/lib/query';
import { DASHBOARD } from '@/test/fixtures';

import { Dashboard } from './Dashboard';

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

const CATALOGUE: MetricDescriptor[] = [
  { key: 'weight', label: 'Poids', unit: 'kg', granularity: 'day', subjects: [] },
  { key: 'hydration', label: 'Hydratation', unit: 'ml', granularity: 'day', subjects: [] },
  {
    key: 'exercise_load',
    label: 'Charge par exercice',
    unit: 'kg',
    granularity: 'day',
    subjects: [{ key: 'e1', label: 'Développé couché' }],
  },
];

const HYDRATION_SERIES: SeriesView = {
  metric: 'hydration',
  label: 'Hydratation',
  unit: 'ml',
  granularity: 'day',
  subject: null,
  range: '3m',
  points: [
    { date: '2026-07-25', value: 2100 },
    { date: '2026-07-26', value: 1400 },
    { date: '2026-07-27', value: 1250 },
  ],
  stats: {
    latest: 1250,
    latest_date: '2026-07-27',
    change: -850,
    average: 1583.33,
    minimum: 1250,
    maximum: 2100,
    count: 3,
  },
};

/** L'assistance disponible, telle que `/api/ai/status` la rend (`IA-07`). */
const AI_ON = { enabled: true, message: 'L’assistance IA est disponible.' };
const AI_OFF = { enabled: false, message: 'Aucune clé OpenRouter n’est configurée.' };

/** Une lecture du jour écrite, et le condensé qui l'accompagne (`IA-09`). */
const READING = {
  day: '2026-07-27',
  slot: 'matin',
  state: 'ready',
  message: 'Deux séances cette semaine sur les **3** visées.',
  basis: ['Poids : 72,4 kg', 'Séances par semaine : 2,4'],
  thread_id: null,
};

const ABSENT = {
  day: '2026-07-27',
  slot: 'soir',
  state: 'absent',
  message: '',
  basis: [],
  thread_id: null,
};

function stub(dashboard: unknown = DASHBOARD, brief: unknown = ABSENT, ai: unknown = AI_ON) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    if (url.includes('/aggregates/dashboard')) return Promise.resolve(json(200, dashboard));
    if (url.includes('/aggregates/metrics')) return Promise.resolve(json(200, CATALOGUE));
    if (url.includes('/aggregates/series')) return Promise.resolve(json(200, HYDRATION_SERIES));
    // Sans clé OpenRouter, la lecture du jour ne s'affiche pas du tout (`IA-07`) : les
    // tests qui ne s'y intéressent pas partent donc de l'assistance **disponible**, pour
    // que la carte soit là, et de `brief` absent, qui est l'état d'une installation neuve.
    if (url.includes('/ai/status')) return Promise.resolve(json(200, ai));
    if (url.includes('/api/brief')) return Promise.resolve(json(200, brief));
    return Promise.resolve(json(200, {}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderDashboard(client = createQueryClient()) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Toaster>
          <Dashboard />
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Les appels d'agrégats, catalogue du sélecteur exclu. */
function aggregateCalls() {
  return calls.filter(
    (call) => call.url.includes('/aggregates/') && !call.url.includes('/aggregates/metrics'),
  );
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('bloc assistant (C01)', () => {
  it('porte trois portes, dont une seule principale', async () => {
    // Le paragraphe qui énumérait ce que l'assistant lit est parti : six lignes de texte
    // au-dessus d'un bouton de 44 px, pour décrire ce que l'assistant montre lui-même.
    stub();
    renderDashboard();

    expect(await screen.findByRole('link', { name: 'Ouvrir l’assistant' })).toHaveAttribute(
      'href',
      '/assistant',
    );
    expect(screen.getByRole('link', { name: 'Discussions' })).toHaveAttribute(
      'href',
      '/assistant?ouvre=discussions',
    );
    expect(screen.getByRole('link', { name: 'Mémoire' })).toHaveAttribute(
      'href',
      '/assistant?ouvre=memoire',
    );
    expect(screen.queryByText(/L’assistant lit ton poids/)).toBeNull();
  });
});

describe('la lecture du jour', () => {
  it('affiche le message du modèle, et le condensé sur lequel il s’appuie', async () => {
    // `AiBlock` et rien d'autre : le projet a **deux** façons de dire « proposé », et une
    // troisième affaiblirait les deux. Le condensé publié rend `IA-09` vérifiable plutôt
    // que déclaratif.
    stub(DASHBOARD, READING);
    renderDashboard();

    expect(await screen.findByText(/Deux séances cette semaine/)).toBeInTheDocument();
    // L'étiquette dit **de quel moment** la carte parle : trois lectures se succèdent
    // dans la journée, et sans elle relire le soir une phrase du matin laisserait croire
    // à une carte qui n'a pas été rafraîchie.
    expect(screen.getByText(/Le matin · lundi 27 juillet/)).toBeInTheDocument();
    expect(screen.getByText(/Ce qui a été envoyé \(2 lignes, aucun fichier\)/)).toBeInTheDocument();
    // Les chiffres arrivent **en gras** : c'est la forme que `GuidelinesUI.html` §10
    // donne à cette carte, et la consigne du serveur la demande explicitement. Aucun HTML
    // n'est injecté — `Markdown` construit des nœuds React depuis une fonction pure.
    expect(screen.getAllByText('3').some((node) => node.tagName === 'STRONG')).toBe(true);
  });

  it('ouvre le fil semé quand on touche le message', async () => {
    // Le fil commence **sur le message de l'assistant**. Poser le texte dans le champ de
    // saisie aurait fait répondre le modèle à une phrase qu'il ne se souvient pas d'avoir
    // écrite — elle ne serait pas dans l'historique du fil.
    stub(DASHBOARD, READING);
    renderDashboard();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Répondre à la lecture du jour dans l’assistant' }),
    );

    await waitFor(() => {
      const opened = calls.filter((call) => call.url.includes('/api/brief/thread'));
      expect(opened).toHaveLength(1);
      expect(opened[0]?.init?.method).toBe('POST');
    });
  });

  it('offre une porte à côté, qui n’emporte pas le message', async () => {
    stub(DASHBOARD, READING);
    renderDashboard();

    expect(await screen.findByRole('link', { name: 'Ouvrir sans ce message' })).toHaveAttribute(
      'href',
      '/assistant',
    );
  });

  it('dit de quel moment l’état vide parle', async () => {
    // Deux états vides à trois heures d'écart ne disent pas la même chose : « rien pour
    // ce soir » à 19 h n'est pas « rien pour ce matin » à 7 h.
    stub(DASHBOARD, ABSENT);
    renderDashboard();

    expect(await screen.findByText(/Ce soir · lundi 27 juillet/)).toBeInTheDocument();
  });

  it('propose de l’écrire quand l’ordonnanceur n’est pas passé', async () => {
    // `absent` n'est pas « rien à dire » : c'est « pas encore écrite ». Aucun chiffre
    // inventé, aucune phrase d'encouragement générique en attendant.
    stub(DASHBOARD, ABSENT);
    renderDashboard();

    expect(await screen.findByRole('button', { name: 'Demander la lecture' })).toBeInTheDocument();
    expect(
      screen.getByText(/Rien n’est encore écrit pour ce moment de la journée/),
    ).toBeInTheDocument();
  });

  it('n’écrit rien tant que personne n’a appuyé', async () => {
    stub(DASHBOARD, ABSENT);
    renderDashboard();

    await screen.findByRole('button', { name: 'Demander la lecture' });

    expect(calls.filter((call) => call.init?.method === 'POST')).toHaveLength(0);
  });

  it('demande la lecture au serveur quand on appuie', async () => {
    stub(DASHBOARD, ABSENT);
    renderDashboard();

    await userEvent.click(await screen.findByRole('button', { name: 'Demander la lecture' }));

    await waitFor(() => {
      const asked = calls.filter(
        (call) => call.url.endsWith('/api/brief') && call.init?.method === 'POST',
      );
      expect(asked).toHaveLength(1);
    });
  });

  it('disparaît entièrement sans clé OpenRouter', async () => {
    // `IA-07` : l'assistance est un confort, jamais un prérequis. Un bouton mort et une
    // phrase d'explication sur l'écran qu'on ouvre le plus en seraient le contraire.
    stub(DASHBOARD, ABSENT, AI_OFF);
    renderDashboard();

    await screen.findByText('Sept derniers jours');

    expect(screen.queryByRole('button', { name: 'Demander la lecture' })).toBeNull();
    expect(calls.some((call) => call.url.includes('/api/brief'))).toBe(false);
    // Les portes de l'assistant restent : sur ordinateur, c'est la seule entrée.
    expect(screen.getByRole('link', { name: 'Ouvrir l’assistant' })).toBeInTheDocument();
  });

  it('affiche le message du serveur quand la lecture est en panne', async () => {
    const client = createQueryClient();
    client.setDefaultOptions({ queries: { retry: false } });
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = input as string;
        calls.push({ url, init: undefined });
        if (url.includes('/aggregates/dashboard')) return Promise.resolve(json(200, DASHBOARD));
        if (url.includes('/aggregates/metrics')) return Promise.resolve(json(200, CATALOGUE));
        if (url.includes('/ai/status')) return Promise.resolve(json(200, AI_ON));
        if (url.includes('/api/brief'))
          return Promise.resolve(
            json(503, { code: 'ai_unavailable', message: 'Aucun modèle n’a répondu.' }),
          );
        return Promise.resolve(json(200, {}));
      }),
    );
    renderDashboard(client);

    // Le client décide sur le code, jamais sur le texte ; le texte vient du serveur et
    // s'affiche tel quel (`API-07`).
    expect(await screen.findByText('Aucun modèle n’a répondu.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeInTheDocument();
  });
});

describe('il reste aujourd’hui', () => {
  it('dit ce qu’il reste, avec la phrase du serveur', async () => {
    // Aucune soustraction côté client : les restants sont servis par les domaines qui
    // détiennent les cibles, et la phrase française avec.
    stub();
    renderDashboard();

    expect(await screen.findByText('encore 750 ml')).toBeInTheDocument();
    expect(screen.getByText('encore 54 g')).toBeInTheDocument();
    expect(screen.getByText('encore 1 prise')).toBeInTheDocument();
  });

  it('mène chaque ligne là où elle se remplit', async () => {
    // Naviguer n'est pas écrire : la ligne dit un écart et ouvre l'écran qui le comble.
    // La case à cocher reste dans `/routine`, le `⊕` garde la saisie en un chiffre.
    stub();
    renderDashboard();

    // `/routine` s'intitule « Hydratation & suppléments » et porte les deux.
    expect(await screen.findByRole('link', { name: /^Eau : encore 750 ml/ })).toHaveAttribute(
      'href',
      '/routine',
    );
    expect(screen.getByRole('link', { name: /^Protéines : encore 54 g/ })).toHaveAttribute(
      'href',
      '/nutrition',
    );
    expect(screen.getByRole('link', { name: /^Suppléments : encore 1 prise/ })).toHaveAttribute(
      'href',
      '/routine',
    );
  });

  it('dit la destination aux lecteurs d’écran, pas seulement au doigt', async () => {
    // Le chevron est décoratif : c'est l'intitulé du lien qui porte où l'on va.
    stub();
    renderDashboard();

    const eau = await screen.findByRole('link', { name: /^Eau/ });
    expect(eau).toHaveAccessibleName('Eau : encore 750 ml. Ouvrir Hydratation & suppléments.');
  });

  it('laisse lisible une ligne dont l’écran ignore la destination', async () => {
    // Le serveur peut ajouter une ligne avant que le client sache où elle mène. L'afficher
    // morte vaut mieux que de la faire disparaître ou de l'envoyer au hasard.
    stub({
      ...DASHBOARD,
      day: {
        ...DASHBOARD.day,
        tasks: [
          {
            key: 'sommeil',
            label: 'Sommeil',
            done: 6.5,
            target: 8,
            unit: 'h',
            ratio: 0.81,
            complete: false,
            remaining: 'encore 1,5 h',
          },
        ],
        total: 1,
      },
    });
    renderDashboard();

    expect(await screen.findByText('Sommeil')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /^Sommeil/ })).toBeNull();
  });

  it('montre la séance prévue sans prétendre qu’elle est faite', async () => {
    // `PLAN-06` détient le rapprochement prévu / réalisé. Une seconde version ici
    // donnerait deux verdicts pour le même mardi.
    stub({
      ...DASHBOARD,
      next_session: {
        id: 0,
        token: 't',
        session_id: 'p1',
        date: '2026-07-28',
        time: '18:30',
        kind: 'musculation',
        title: 'Haut du corps',
        duration_min: 45,
        note: null,
        source: 'manual',
      },
    });
    renderDashboard();

    expect(await screen.findByText('Haut du corps')).toBeInTheDocument();
    expect(screen.getByText(/prévu le 28\/07/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /^Haut du corps/ })).toHaveAttribute(
      'href',
      '/planning',
    );
  });

  it('dit où aller quand rien n’est prévu', async () => {
    stub();
    renderDashboard();

    expect(await screen.findByText(/Aucune séance prévue d’ici deux semaines/)).toBeInTheDocument();
  });
});

describe('où je vais', () => {
  it('affiche l’objectif en cours, calculé par le serveur', async () => {
    stub({
      ...DASHBOARD,
      goal: {
        goal: {
          id: 0,
          token: 't',
          goal_id: 'g1',
          created: '2026-07-01',
          title: 'Trois séances par semaine',
          metric: 'weekly_sessions',
          target: 3,
          unit: 'séances',
          deadline: '2026-09-07',
          rationale: '',
          source: 'ai',
          status: 'active',
          outcome: '',
          outcome_label: '',
        },
        progress: {
          metric: 'weekly_sessions',
          label: 'Séances par semaine',
          unit: 'séances',
          baseline: 1.8,
          current: 2.4,
          target: 3,
          ratio: 0.5,
          summary: '2,4 sur 3 séances',
          basis: 'moyenne des 4 dernières semaines complètes',
        },
        days_left: 42,
        expired: false,
      },
    });
    renderDashboard();

    expect(await screen.findByText('Trois séances par semaine')).toBeInTheDocument();
    // Le libellé chiffré et la fenêtre d'observation arrivent **rédigés**.
    expect(screen.getByText('2,4 sur 3 séances')).toBeInTheDocument();
    expect(screen.getByText('moyenne des 4 dernières semaines complètes')).toBeInTheDocument();
    expect(screen.getByText(/42 jours restants/)).toBeInTheDocument();
  });

  it('ne dessine aucun anneau quand l’avancement est indéterminé', async () => {
    // Le défaut du L14, dans son type : un anneau dessine un pourcentage, et « 0 % » au
    // centre d'une donnée absente est une valeur inventée.
    stub({
      ...DASHBOARD,
      goal: {
        goal: {
          id: 0,
          token: 't',
          goal_id: 'g1',
          created: '2026-07-01',
          title: 'Trois séances par semaine',
          metric: 'weekly_sessions',
          target: 3,
          unit: 'séances',
          deadline: '2026-09-07',
          rationale: '',
          source: 'ai',
          status: 'active',
          outcome: '',
          outcome_label: '',
        },
        progress: {
          metric: 'weekly_sessions',
          label: 'Séances par semaine',
          unit: 'séances',
          baseline: null,
          current: null,
          target: 3,
          ratio: null,
          summary: '— sur 3 séances',
          basis: 'moyenne des 4 dernières semaines complètes',
        },
        days_left: 42,
        expired: false,
      },
    });
    renderDashboard();

    await screen.findByText('Trois séances par semaine');
    expect(screen.queryByRole('img', { name: 'Séances par semaine' })).toBeNull();
    expect(screen.queryByText('0 %')).toBeNull();
  });

  it('retombe sur la cible de poids, en disant que c’est un réglage', async () => {
    stub();
    renderDashboard();

    expect(await screen.findByText(/Cible de poids 70 kg/)).toBeInTheDocument();
    expect(screen.getByText(/C’est un réglage, pas un objectif daté/)).toBeInTheDocument();
  });

  it('porte l’état vide quand il n’y a ni objectif ni cible', async () => {
    stub({ ...DASHBOARD, weight: { ...DASHBOARD.weight, to_target_kg: null } });
    renderDashboard();

    expect(await screen.findByText('Aucun objectif en cours')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Fixer un objectif' })).toHaveAttribute(
      'href',
      '/objectif',
    );
  });
});

describe('tableau de bord', () => {
  it("ne fait qu'un seul appel d'agrégats au chargement", async () => {
    // `AGG-01`, la raison d'être du lot. Dix appels parallèles au chargement d'un écran
    // signifieraient dix allers-retours vers Nextcloud — et c'est précisément ce que le
    // graphique inclus dans la réponse permet d'éviter.
    stub();
    renderDashboard();

    await screen.findByText('Sept derniers jours');

    expect(aggregateCalls()).toHaveLength(1);
    expect(aggregateCalls()[0]?.url).toContain('/api/aggregates/dashboard');
  });

  it('affiche les chiffres tels que le serveur les a calculés', async () => {
    stub();
    renderDashboard();

    // Le poids apparaît à plusieurs endroits — chiffre clé, dernier point, graduation.
    // Ce sont les commentaires qui l'accompagnent qui prouvent d'où viennent les calculs.
    expect(await screen.findByText(/−1,2 kg sur 8 pesées/)).toBeInTheDocument();
    expect(screen.getAllByText('72,4').length).toBeGreaterThan(0);
    expect(screen.getByText(/2 séances · 8,4 km/)).toBeInTheDocument();
    // L'hydratation a quitté la bande de chiffres : elle vit dans la liste du jour,
    // où elle dit le restant plutôt que le total.
    expect(screen.getByText('1,25 L')).toBeInTheDocument();
    expect(screen.getByText(/record 41 · 180 jours suivis/)).toBeInTheDocument();
  });

  it('trace la série livrée avec le tableau de bord', async () => {
    stub();
    renderDashboard();

    expect(await screen.findByRole('img', { name: 'Poids' })).toBeInTheDocument();
    expect(screen.getByText(/−3,8/)).toBeInTheDocument();
  });

  it('nomme les deux parts de la répartition', async () => {
    // Deux et non trois depuis le rebranchement : le champ `type` libre d'une séance
    // n'existe plus dans la source, donc plus de part « autre » à nommer.
    stub();
    renderDashboard();

    expect(await screen.findByText('Course')).toBeInTheDocument();
    expect(screen.getByText('Tabata')).toBeInTheDocument();
  });

  it('montre les sept derniers jours, trous compris', async () => {
    // `AGG-03` : la plage est complète, un jour sans donnée est présent et vide.
    stub();
    renderDashboard();

    await screen.findByText('Sept derniers jours');

    // Le quantième seul : sous un titre « Sept derniers jours », le mois est le même six
    // fois sur sept et n'apprend rien — et `26/07` en chasse fixe demandait 36 px, soit
    // sept cases de 42 px pour 294 disponibles à 360. L'infobulle garde la date entière.
    expect(screen.getByText('23')).toBeInTheDocument();
    expect(screen.getByTitle('23/07 — aucune donnée')).toBeInTheDocument();
    expect(screen.getByTitle('27/07 — poids, repas, hydratation')).toBeInTheDocument();
  });

  it('signale un dépassement du plafond de sucres', async () => {
    stub();
    renderDashboard();

    expect(
      await screen.findByText(/Plafond de sucres dépassé : 38 g sur 30 g/),
    ).toBeInTheDocument();
  });

  it('demande une nouvelle série quand la plage change, et rien d’autre', async () => {
    stub();
    renderDashboard();

    await screen.findByText('Sept derniers jours');
    await userEvent.click(screen.getByRole('button', { name: '1 mois' }));

    await waitFor(() => {
      const series = calls.filter((call) => call.url.includes('/aggregates/series'));
      expect(series).toHaveLength(1);
      expect(series[0]?.url).toContain('range=1m');
    });

    // Le tableau de bord n'a pas été rechargé : seule la série l'a été.
    expect(calls.filter((call) => call.url.includes('/aggregates/dashboard'))).toHaveLength(1);
  });

  it('propose les métriques publiées par le serveur, pas une liste en dur', async () => {
    stub();
    renderDashboard();

    // La charge par exercice exige un sujet : elle n'a pas sa place dans ce sélecteur.
    expect(await screen.findByRole('button', { name: 'Hydratation' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Charge par exercice' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Hydratation' }));

    await waitFor(() => {
      expect(calls.some((call) => call.url.includes('metric=hydration'))).toBe(true);
    });
  });

  it('annonce une journée vide sans inventer de chiffre', async () => {
    stub({
      ...DASHBOARD,
      weight: { ...DASHBOARD.weight, latest_kg: null, latest_date: null, change_kg: null },
      nutrition: { ...DASHBOARD.nutrition, meals: 0, over_sugar: false },
      hydration: { ...DASHBOARD.hydration, today_ml: 0 },
      supplements: { taken: 0, planned: 3, ratio: 0, complete: false },
      // `logged` vient du serveur, qui le tient de `AGG-03` : sept sources, une seule
      // définition. L'écran le recollait à partir de quatre champs et annonçait « aucun
      // relevé » un jour où l'on avait couru.
      day: {
        ...DASHBOARD.day,
        logged: false,
        tasks: DASHBOARD.day.tasks.map((task) => ({ ...task, done: null, ratio: 0 })),
      },
    });
    renderDashboard();

    expect(await screen.findByText('Aucun relevé aujourd’hui')).toBeInTheDocument();
    // Un tiret, jamais un zéro qui passerait pour une mesure.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(screen.queryByText('0 g')).toBeNull();
  });

  it('affiche le message du serveur quand la lecture échoue', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          json(503, { code: 'storage_unavailable', message: 'Nextcloud est injoignable.' }),
        ),
      ),
    );

    // Une panne de stockage est passagère : le client la rejoue avant d'abandonner
    // (`STO-08`), et c'est le bon comportement. Ce test ne s'intéresse qu'à l'état
    // terminal, il coupe donc les tentatives plutôt que d'attendre leur temporisation.
    const client = createQueryClient();
    client.setDefaultOptions({ queries: { retry: false } });
    renderDashboard(client);

    expect(await screen.findByText('Nextcloud est injoignable.')).toBeInTheDocument();
    // Le message vient du serveur et s'affiche tel quel : il est déjà en français.
    expect(screen.getByText('Tableau de bord indisponible')).toBeInTheDocument();
  });
});
