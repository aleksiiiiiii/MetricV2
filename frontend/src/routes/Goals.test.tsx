import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import type { GoalProposal, GoalsView, WeeklyReview, WeeklyView } from '@/features/goals/api';
import { createQueryClient } from '@/lib/query';

import { Goals } from './Goals';

/**
 * Écran Objectif (`L14-09`).
 *
 * Ces tests portent sur ce qu'un test d'API ne peut pas voir, et que trois lots de suite
 * ont fait remonter en *utilisant* l'application :
 *
 * * une proposition **n'écrit rien** tant qu'on n'a pas adopté (`GOAL-03`) — vérifié sur
 *   les requêtes réellement parties, pas sur l'intention du code ;
 * * un avancement indéterminé s'affiche en tiret, jamais en `0 %` ;
 * * le condensé envoyé au modèle est **affiché**, ce qui rend `GOAL-02` vérifiable à
 *   l'écran plutôt que dans le code ;
 * * l'écran ne recalcule aucun ratio : il montre celui qu'il reçoit, y compris quand
 *   celui-ci est incohérent avec les chiffres bruts.
 */

const TODAY = '2026-08-12';

const PROGRESS = {
  metric: 'weekly_sessions',
  label: 'Séances par semaine',
  unit: 'séances',
  baseline: 1.8,
  current: 2.4,
  target: 3,
  ratio: 0.5,
  summary: '2,4 sur 3 séances',
  basis: 'moyenne des 4 dernières semaines complètes',
};

const ACTIVE_GOAL: GoalsView = {
  state: 'active',
  active: {
    goal: {
      id: 0,
      token: 'jeton-objectif',
      goal_id: 'abc123',
      created: '2026-07-15',
      title: 'Trois séances par semaine',
      metric: 'weekly_sessions',
      target: 3,
      unit: 'séances',
      deadline: '2026-09-23',
      rationale: '1,8 séance par semaine sur les quatre dernières',
      source: 'ai',
      status: 'active',
      outcome: '',
      outcome_label: '',
    },
    progress: PROGRESS,
    days_left: 42,
    expired: false,
  },
  history: [],
  today: TODAY,
};

const NO_GOAL: GoalsView = { state: 'none', active: null, history: [], today: TODAY };

/** L'objectif actif d'une vue de référence, sans assertion de non-nullité. */
function activeOf(view: GoalsView): NonNullable<GoalsView['active']> {
  if (!view.active) throw new Error('cette vue de référence porte un objectif actif');
  return view.active;
}

const PROPOSAL: GoalProposal = {
  goal: {
    title: 'Trois séances par semaine',
    metric: 'weekly_sessions',
    label: 'Séances par semaine',
    target: 3,
    unit: 'séances',
    deadline: '2026-09-23',
    rationale: 'Tu en es à 1,8 par semaine depuis un mois',
  },
  basis: ['Séances par semaine : 1,8 séances (moyenne des 4 dernières semaines complètes)'],
  fallback: false,
  dropped: [],
};

const REVIEW: WeeklyReview = {
  week: '2026-08-03',
  progress: ['3 séances contre 2 la semaine d’avant'],
  setbacks: ['hydratation à 1 400 ml par jour, en baisse'],
  action: 'Poser une gourde de 750 ml sur le bureau chaque matin.',
  basis: ['Séances par semaine : 3 séances'],
};

const WEEKLY: WeeklyView = { entries: [], next_week: '2026-08-03', already_kept: false };

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

function stub(
  options: {
    goals?: GoalsView;
    weekly?: WeeklyView;
    proposal?: GoalProposal;
    aiEnabled?: boolean;
  } = {},
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    // `request` n'envoie que des chaînes : le typage de `fetch` est plus large que
    // l'usage, et `String(objet)` rendrait « [object Object] » sans le dire.
    const url = input as string;
    calls.push({ url, init });

    if (url.includes('/api/ai/status')) {
      return Promise.resolve(
        json(200, { enabled: options.aiEnabled ?? true, message: 'aucune clé configurée' }),
      );
    }
    if (url.includes('/api/goals/weekly/keep')) {
      return Promise.resolve(json(201, { id: 0, token: 't', week: REVIEW.week, summary: 'ok' }));
    }
    if (url.includes('/api/goals/weekly')) {
      if ((init?.method ?? 'GET') === 'POST') return Promise.resolve(json(200, REVIEW));
      return Promise.resolve(json(200, options.weekly ?? WEEKLY));
    }
    if (url.includes('/api/goals/proposal')) {
      return Promise.resolve(json(200, options.proposal ?? PROPOSAL));
    }
    if (url.includes('/close') || url.includes('/abandon')) {
      return Promise.resolve(
        json(200, { ...activeOf(ACTIVE_GOAL).goal, outcome: 'partial', outcome_label: 'partiel' }),
      );
    }
    return Promise.resolve(json(200, options.goals ?? ACTIVE_GOAL));
  });

  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderScreen() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Toaster>
          <Goals />
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function writes(): Call[] {
  return calls.filter((call) => (call.init?.method ?? 'GET') !== 'GET');
}

/** Corps d'une écriture, décodé. `null` si la requête n'est jamais partie. */
function bodyOf(fragment: string): Record<string, unknown> | null {
  const call = writes().find((item) => item.url.endsWith(fragment));
  if (!call) return null;
  return JSON.parse(call.init?.body as string) as Record<string, unknown>;
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── L'objectif en cours (`GOAL-04`, `GOAL-05`) ────────

describe('objectif en cours', () => {
  it('affiche le libellé chiffré et la fenêtre, tels que le serveur les rend', async () => {
    stub();
    renderScreen();

    expect(await screen.findByText('Trois séances par semaine')).toBeInTheDocument();
    expect(screen.getByText(PROGRESS.summary)).toBeInTheDocument();
    expect(screen.getByText(PROGRESS.basis)).toBeInTheDocument();
  });

  it("n'invente aucun avancement quand le point de départ manque", async () => {
    stub({
      goals: {
        ...ACTIVE_GOAL,
        active: {
          ...activeOf(ACTIVE_GOAL),
          progress: { ...PROGRESS, baseline: null, current: null, ratio: null },
        },
      },
    });
    renderScreen();

    // Pas d'anneau du tout : un « 0% » au centre serait une valeur inventée, et c'est
    // le chiffre que l'œil lit en premier. Défaut trouvé en regardant la page.
    expect(await screen.findByLabelText('avancement indéterminé')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: '50 %' })).not.toBeInTheDocument();
    expect(screen.getByText(/avancement indéterminé —/)).toBeInTheDocument();
  });

  it("dit que l'échéance est passée sans clore l'objectif pour autant", async () => {
    stub({
      goals: {
        ...ACTIVE_GOAL,
        active: { ...activeOf(ACTIVE_GOAL), days_left: -3, expired: true },
      },
    });
    renderScreen();

    expect(await screen.findByText('échéance passée')).toBeInTheDocument();
    expect(screen.getByText(/dépassée depuis 3 jour/)).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
  });

  it("n'abandonne qu'au second appui", async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();

    const button = await screen.findByRole('button', {
      name: /Abandonner Trois séances par semaine$/,
    });
    await user.click(button);

    expect(writes()).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: /confirmer/i }));

    await waitFor(() => {
      expect(writes().some((call) => call.url.includes('/abandon'))).toBe(true);
    });
  });

  it('renvoie en `If-Match` le jeton qu’il a lu', async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();

    await user.click(await screen.findByRole('button', { name: /Clore l'objectif/ }));

    await waitFor(() => {
      const call = writes().find((item) => item.url.includes('/close'));
      expect(call?.init?.headers).toMatchObject({ 'If-Match': 'jeton-objectif' });
    });
  });
});

// ── La proposition (`GOAL-01` → `GOAL-03`) ────────────

describe('proposition assistée', () => {
  it("ne propose rien tant qu'un objectif est en cours", async () => {
    stub();
    renderScreen();

    await screen.findByText('Trois séances par semaine');
    expect(screen.queryByRole('button', { name: /Proposer un objectif/ })).not.toBeInTheDocument();
  });

  it('écrit exactement rien avant adoption', async () => {
    const user = userEvent.setup();
    stub({ goals: NO_GOAL });
    renderScreen();

    await user.click(await screen.findByRole('button', { name: /Proposer un objectif/ }));

    expect(await screen.findByText(/Séances par semaine · échéance/)).toBeInTheDocument();
    // La demande est un `POST`, mais vers `/proposal` : rien n'a été écrit.
    expect(writes().every((call) => call.url.includes('/proposal'))).toBe(true);
  });

  it('affiche le condensé réellement envoyé au modèle', async () => {
    const user = userEvent.setup();
    stub({ goals: NO_GOAL });
    renderScreen();

    await user.click(await screen.findByRole('button', { name: /Proposer un objectif/ }));

    // `GOAL-02` vérifiable à l'écran plutôt que dans le code.
    expect(await screen.findByText(PROPOSAL.basis.join(''))).toBeInTheDocument();
  });

  it('adopte le titre retouché plutôt que celui du modèle', async () => {
    const user = userEvent.setup();
    stub({ goals: NO_GOAL });
    renderScreen();

    await user.click(await screen.findByRole('button', { name: /Proposer un objectif/ }));
    const title = await screen.findByLabelText(/Titre de l'objectif/);
    await user.clear(title);
    await user.type(title, 'Trois fois par semaine, sans exception');
    await user.click(screen.getByRole('button', { name: 'Adopter' }));

    await waitFor(() => {
      expect(bodyOf('/api/goals')).toMatchObject({
        title: 'Trois fois par semaine, sans exception',
        metric: 'weekly_sessions',
        target: 3,
      });
    });
  });

  it("n'envoie pas d'unité — elle vient du registre du serveur", async () => {
    const user = userEvent.setup();
    stub({ goals: NO_GOAL });
    renderScreen();

    await user.click(await screen.findByRole('button', { name: /Proposer un objectif/ }));
    await user.click(await screen.findByRole('button', { name: 'Adopter' }));

    await waitFor(() => {
      expect(bodyOf('/api/goals')).not.toHaveProperty('unit');
    });
  });

  it('« Pas d’accord » efface la proposition sans rien écrire', async () => {
    const user = userEvent.setup();
    stub({ goals: NO_GOAL });
    renderScreen();

    await user.click(await screen.findByRole('button', { name: /Proposer un objectif/ }));
    await user.click(await screen.findByRole('button', { name: /Pas d'accord/ }));

    expect(screen.queryByText(/Séances par semaine · échéance/)).not.toBeInTheDocument();
    expect(writes().every((call) => call.url.includes('/proposal'))).toBe(true);
  });

  it('dit quand la proposition est un repli de régularité', async () => {
    const user = userEvent.setup();
    stub({ goals: NO_GOAL, proposal: { ...PROPOSAL, fallback: true } });
    renderScreen();

    await user.click(await screen.findByRole('button', { name: /Proposer un objectif/ }));

    expect(await screen.findByText(/trop maigres pour viser une performance/)).toBeInTheDocument();
  });

  it("ne propose rien du tout quand l'assistance n'a pas de clé", async () => {
    stub({ goals: NO_GOAL, aiEnabled: false });
    renderScreen();

    expect(await screen.findByText('Aucun objectif en cours')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Proposer un objectif/ })).not.toBeInTheDocument();
    expect(screen.getByText('aucune clé configurée')).toBeInTheDocument();
  });
});

// ── Le bilan hebdomadaire (`IA-08`) ───────────────────

describe('bilan hebdomadaire', () => {
  it("n'historise rien tant que le bilan n'est pas conservé", async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();

    await user.click(await screen.findByRole('button', { name: /Faire le bilan/ }));

    expect(await screen.findByText(REVIEW.action)).toBeInTheDocument();
    expect(writes().some((call) => call.url.includes('/weekly/keep'))).toBe(false);
  });

  it('sépare ce qui progresse de ce qui décroche', async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();

    await user.click(await screen.findByRole('button', { name: /Faire le bilan/ }));

    expect(await screen.findByText('Ce qui progresse')).toBeInTheDocument();
    expect(screen.getByText('Ce qui décroche')).toBeInTheDocument();
    expect(screen.getByText(REVIEW.progress.join(''))).toBeInTheDocument();
  });

  it('conserve le bilan en une phrase, comme le fichier le rangera', async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();

    await user.click(await screen.findByRole('button', { name: /Faire le bilan/ }));
    await user.click(await screen.findByRole('button', { name: 'Conserver' }));

    await waitFor(() => {
      expect(bodyOf('/weekly/keep')).toMatchObject({ week: '2026-08-03' });
      expect(String(bodyOf('/weekly/keep')?.summary)).toContain('Action : Poser une gourde');
    });
  });

  it('prévient que reconserver une semaine remplacera son bilan', async () => {
    stub({ weekly: { ...WEEKLY, already_kept: true } });
    renderScreen();

    expect(await screen.findByText(/une semaine, une ligne/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Refaire le bilan/ })).toBeInTheDocument();
  });

  it("montre l'historique conservé même sans clé API", async () => {
    stub({
      aiEnabled: false,
      weekly: {
        entries: [
          {
            id: 0,
            token: 'jeton-bilan',
            week: '2026-07-27',
            created: '2026-08-03',
            summary: 'Progrès : 3 séances. Action : la gourde.',
            source: 'ai',
          },
        ],
        next_week: '2026-08-03',
        already_kept: false,
      },
    });
    renderScreen();

    expect(await screen.findByText(/Progrès : 3 séances/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Faire le bilan/ })).not.toBeInTheDocument();
  });
});

// ── L'historique des objectifs (`GOAL-06`) ────────────

describe('objectifs passés', () => {
  it('affiche le résultat en français, sans traduire un code', async () => {
    stub({
      goals: {
        ...NO_GOAL,
        history: [
          {
            id: 1,
            token: 'jeton-vieux',
            goal_id: 'old001',
            created: '2026-05-01',
            title: 'Courir 20 km par semaine',
            metric: 'weekly_distance_km',
            target: 20,
            unit: 'km',
            deadline: '2026-06-15',
            rationale: '',
            source: 'ai',
            status: 'closed',
            outcome: 'abandoned',
            outcome_label: 'abandonné',
          },
        ],
      },
    });
    renderScreen();

    expect(await screen.findByText('Courir 20 km par semaine')).toBeInTheDocument();
    expect(screen.getByText('abandonné')).toBeInTheDocument();
    expect(screen.queryByText('abandoned')).not.toBeInTheDocument();
  });
});
