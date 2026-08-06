import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import type { AdherenceView, MonthView, Proposal } from '@/features/planning/api';
import { createQueryClient } from '@/lib/query';

import { Planning } from './Planning';

/**
 * Écran Planning (`L13-07`).
 *
 * Ces tests portent sur ce qu'un test d'API ne peut pas voir, et que trois lots de suite
 * ont fait remonter en *utilisant* l'application :
 *
 * * une proposition **n'écrit rien** tant qu'on n'a pas adopté (`PLAN-04`) — vérifié en
 *   regardant les requêtes réellement parties, pas l'intention du code ;
 * * le retrait individuel enlève **une** séance de la charge utile, et laisse les autres ;
 * * une case de calendrier dit ce qu'elle porte à la synthèse vocale, ce que deux
 *   pastilles de six pixels ne font pas toutes seules ;
 * * un taux absent s'affiche en tiret, jamais en `0 %`.
 */

const TODAY = '2026-08-12';

/** Août 2026 : le 1er est un samedi, la grille ouvre donc au lundi 27 juillet. */
function days(): MonthView['days'] {
  const cells: MonthView['days'] = [];
  const cursor = new Date('2026-07-27T12:00:00');

  while (cursor <= new Date('2026-09-06T12:00:00')) {
    const iso = cursor.toISOString().slice(0, 10);
    cells.push({ date: iso, in_month: iso.startsWith('2026-08'), planned: [], done: [] });
    cursor.setDate(cursor.getDate() + 1);
  }
  return cells;
}

function monthView(overrides: Partial<MonthView> = {}): MonthView {
  const cells = days();

  const withData = cells.map((cell) =>
    cell.date === TODAY
      ? {
          ...cell,
          planned: [
            {
              id: 0,
              token: 'jeton-1',
              session_id: 'abc123',
              date: TODAY,
              time: '18:30',
              kind: 'muscu' as const,
              title: 'Haut du corps',
              duration_min: 60,
              note: '5×5',
              source: 'manual',
            },
          ],
          done: [{ kind: 'run' as const, id: 3, label: '8,50 km', duration_min: 45 }],
        }
      : cell,
  );

  return {
    month: '2026-08-01',
    start: '2026-07-27',
    end: '2026-09-06',
    days: withData,
    today: TODAY,
    ...overrides,
  };
}

const ADHERENCE: AdherenceView = {
  weeks: [
    { week: '2026-08-03', planned: 3, done: 2, honoured: 2, rate: 2 / 3 },
    { week: '2026-08-10', planned: 2, done: 2, honoured: 2, rate: 1 },
  ],
  rate: 0.8,
  planned: 5,
  honoured: 4,
};

const EMPTY_ADHERENCE: AdherenceView = { weeks: [], rate: null, planned: 0, honoured: 0 };

const PROPOSAL: Proposal = {
  start: '2026-08-17',
  end: '2026-08-23',
  basis: ['3,2 séance par semaine en moyenne sur 4 semaines'],
  dropped: ['Muscu du 2026-08-18 : déjà prévue.'],
  sessions: [
    {
      date: '2026-08-17',
      time: '18:30',
      kind: 'muscu',
      title: 'Haut du corps',
      duration_min: 60,
      note: null,
      reason: 'dos non travaillé depuis 12 jours',
    },
    {
      date: '2026-08-19',
      time: null,
      kind: 'course',
      title: 'Sortie longue',
      duration_min: 50,
      note: null,
      reason: 'une sortie longue par semaine',
    },
  ],
};

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

function stub(options: { adherence?: AdherenceView; aiEnabled?: boolean } = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    // `request` n'envoie que des chaînes : le typage de `fetch` est plus large que
    // l'usage, et `String(objet)` rendrait « [object Object] » sans le dire.
    const url = input as string;
    calls.push({ url, init });

    if (url.includes('/api/ai/status')) {
      return Promise.resolve(
        json(200, { enabled: options.aiEnabled ?? true, message: 'disponible' }),
      );
    }
    if (url.includes('/api/planning/adherence')) {
      return Promise.resolve(json(200, options.adherence ?? ADHERENCE));
    }
    if (url.includes('/api/planning/subscription')) {
      return Promise.resolve(
        json(200, {
          configured: true,
          url: 'http://localhost:8000/api/calendar/cle.ics',
          message: 'Cette adresse contient ta clé.',
        }),
      );
    }
    if (url.includes('/api/planning/proposal/adopt')) {
      return Promise.resolve(json(201, { created: [] }));
    }
    if (url.includes('/api/planning/proposal')) {
      return Promise.resolve(json(200, PROPOSAL));
    }
    if (url.includes('/api/planning/sessions')) {
      return Promise.resolve(json(201, {}));
    }
    return Promise.resolve(json(200, monthView()));
  });

  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderScreen() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Toaster>
          <Planning />
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function writes(): Call[] {
  return calls.filter((call) => (call.init?.method ?? 'GET') !== 'GET');
}

beforeEach(() => {
  calls.length = 0;
  // L'écran amorce son mois sur l'horloge du navigateur avant que le serveur ne réponde.
  // Sans horloge fixe, « mois suivant » viserait un mois différent chaque mois de l'année.
  // `shouldAdvanceTime` laisse les attentes internes de `user-event` se dérouler.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date('2026-08-12T10:00:00'));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

// ── Le calendrier (`PLAN-01`) ─────────────────────────

describe('calendrier mensuel', () => {
  it('affiche la grille telle que le serveur la découpe', async () => {
    stub();
    renderScreen();

    const grid = await screen.findByRole('grid');

    // 6 semaines × 7 jours, débordements compris : l'écran ne recompose rien.
    expect(within(grid).getAllByRole('button')).toHaveLength(42);
    expect(screen.getByRole('columnheader', { name: 'lundi' })).toBeInTheDocument();
  });

  it('dit à la synthèse vocale ce que porte une case', async () => {
    // Deux pastilles de six pixels ne se lisent pas, et « 12 » tout seul ne dirait rien.
    stub();
    renderScreen();

    const cell = await screen.findByRole('button', { name: /mercredi 12 août/ });

    expect(cell).toHaveAccessibleName(/1 prévue/);
    expect(cell).toHaveAccessibleName(/1 effectuée/);
  });

  it('ouvre le jour du serveur, pas celui du navigateur', async () => {
    // `HEAT-32` : le fuseau de découpage est un réglage du serveur. Un écran qui
    // calculerait « aujourd'hui » lui-même se tromperait de jour à 23 h 30.
    stub();
    renderScreen();

    expect(await screen.findByRole('heading', { name: /mercredi 12 août/ })).toBeInTheDocument();
  });

  it('montre côte à côte le prévu et l’effectué du jour', async () => {
    stub();
    renderScreen();

    expect(await screen.findByText('Haut du corps')).toBeInTheDocument();
    expect(screen.getByText('18:30 · Muscu · 1 h')).toBeInTheDocument();
    expect(screen.getByText('8,50 km')).toBeInTheDocument();
  });

  it('change de mois sans rien écrire', async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();
    await screen.findByRole('grid');

    await user.click(screen.getByRole('button', { name: 'Mois suivant' }));

    await waitFor(() => {
      expect(calls.some((call) => call.url.includes('month=2026-09'))).toBe(true);
    });
    expect(writes()).toHaveLength(0);
  });

  it('sélectionne un autre jour au doigt', async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();
    await screen.findByRole('grid');

    await user.click(screen.getByRole('button', { name: /jeudi 20 août/ }));

    expect(await screen.findByRole('heading', { name: /jeudi 20 août/ })).toBeInTheDocument();
    expect(screen.getByText('Rien ce jour-là')).toBeInTheDocument();
  });
});

// ── Le taux de respect (`PLAN-06`) ────────────────────

describe('respect du planning', () => {
  it('affiche le taux calculé par le serveur', async () => {
    stub();
    renderScreen();

    expect(await screen.findByText('80 %')).toBeInTheDocument();
    expect(screen.getByText('Honorées')).toBeInTheDocument();
  });

  it('affiche un tiret quand rien n’était prévu, jamais un zéro', async () => {
    // Une semaine sans planning n'a pas un taux de 0 % : elle n'a pas de taux du tout.
    // Un zéro la ferait passer pour une semaine ratée.
    stub({ adherence: EMPTY_ADHERENCE });
    renderScreen();

    expect(await screen.findByText('—')).toBeInTheDocument();
    expect(screen.queryByText('0 %')).not.toBeInTheDocument();
  });
});

// ── La proposition (`PLAN-03`, `PLAN-04`) ─────────────

describe('proposition assistée', () => {
  async function propose(user: ReturnType<typeof userEvent.setup>) {
    // La carte n'apparaît qu'une fois l'état de l'assistance connu (`IA-07`).
    await user.click(await screen.findByRole('button', { name: 'Proposer' }));
    return screen.findByText(/3,2 séance par semaine/);
  }

  it('n’écrit rien tant que la proposition n’est pas adoptée', async () => {
    // Le cœur de `PLAN-04`, et la moitié de la DoD du lot. Ce test tomberait au premier
    // raccourci « tant qu'on y est, écrivons-les ».
    const user = userEvent.setup();
    stub();
    renderScreen();
    await screen.findByRole('grid');

    await propose(user);

    expect(screen.getByText('Haut du corps', { selector: 'strong' })).toBeInTheDocument();
    expect(writes().filter((call) => call.url.includes('adopt'))).toHaveLength(0);
    expect(writes().filter((call) => call.url.includes('/sessions'))).toHaveLength(0);
  });

  it('montre sur quoi la proposition s’appuie', async () => {
    // Une suggestion dont on voit l'argument se discute ; une suggestion nue se croit
    // ou se rejette.
    const user = userEvent.setup();
    stub();
    renderScreen();
    await screen.findByRole('grid');

    await propose(user);

    expect(screen.getByText(/dos non travaillé depuis 12 jours/)).toBeInTheDocument();
    expect(screen.getByText(/Écarté à la relecture/)).toBeInTheDocument();
  });

  it('retire une séance sans renoncer aux autres', async () => {
    // Le « Pas d'accord » du lot L12, appliqué à une liste.
    const user = userEvent.setup();
    stub();
    renderScreen();
    await screen.findByRole('grid');
    await propose(user);

    // Le nom désigne **quelle** séance : deux boutons « Retirer » coexistent à l'écran,
    // l'un enlève une proposition, l'autre supprime une séance réelle du planning.
    await user.click(
      screen.getByRole('button', { name: 'Retirer Haut du corps de la proposition' }),
    );
    await user.click(screen.getByRole('button', { name: /Adopter/ }));

    const adopted = writes().find((call) => call.url.includes('adopt'));
    const body = JSON.parse(adopted?.init?.body as string) as { sessions: { title: string }[] };

    expect(body.sessions).toHaveLength(1);
    expect(body.sessions[0]?.title).toBe('Sortie longue');
  });

  it('rend réversible un retrait, puisque rien n’est écrit', async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();
    await screen.findByRole('grid');
    await propose(user);

    await user.click(
      screen.getByRole('button', { name: 'Retirer Haut du corps de la proposition' }),
    );
    await user.click(
      screen.getByRole('button', { name: 'Remettre Haut du corps de la proposition' }),
    );
    await user.click(screen.getByRole('button', { name: /Adopter/ }));

    const adopted = writes().find((call) => call.url.includes('adopt'));
    const body = JSON.parse(adopted?.init?.body as string) as { sessions: unknown[] };

    expect(body.sessions).toHaveLength(2);
  });

  it('adopte en un seul appel', async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();
    await screen.findByRole('grid');
    await propose(user);

    await user.click(screen.getByRole('button', { name: /Adopter/ }));

    await waitFor(() => {
      expect(writes().filter((call) => call.url.includes('adopt'))).toHaveLength(1);
    });
  });

  it('ne propose rien du tout sans clé API', async () => {
    // `IA-07` : sans clé, l'écran ne montre pas une commande qui échouerait.
    stub({ aiEnabled: false });
    renderScreen();
    await screen.findByRole('grid');
    // On attend que la réponse soit *arrivée* : constater une absence avant que la
    // question ait été posée ne prouverait rien.
    await waitFor(() => {
      expect(calls.some((call) => call.url.includes('/api/ai/status'))).toBe(true);
    });
    await screen.findByRole('heading', { name: 'Abonnement calendrier' });

    expect(screen.queryByRole('button', { name: 'Proposer' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Planifier' })).toBeInTheDocument();
  });
});

// ── La saisie manuelle (`PLAN-02`) ────────────────────

describe('saisie manuelle', () => {
  it('envoie le jeton lu en If-Match pour une correction', async () => {
    // `STO-05` : le jeton lu **est** celui qu'on renvoie. Un `If-Match` absent est un
    // conflit, et l'écran ne doit jamais l'omettre.
    const user = userEvent.setup();
    stub();
    renderScreen();
    await screen.findByText('Haut du corps');

    await user.click(screen.getByRole('button', { name: 'Modifier' }));
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }));

    await waitFor(() => {
      expect(writes().some((call) => call.init?.method === 'PATCH')).toBe(true);
    });
    const patch = writes().find((call) => call.init?.method === 'PATCH');
    expect((patch?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-1');
  });

  it('demande deux appuis pour retirer une séance', async () => {
    // Le projet n'a pas d'annulation : ce qui est supprimé l'est.
    const user = userEvent.setup();
    stub();
    renderScreen();
    await screen.findByText('Haut du corps');

    await user.click(screen.getByRole('button', { name: 'Supprimer Haut du corps du planning' }));

    expect(writes()).toHaveLength(0);
    const confirm = screen.getByRole('button', { name: 'Supprimer Haut du corps — confirmer' });
    expect(confirm).toHaveTextContent('Confirmer ?');

    await user.click(confirm);

    await waitFor(() => {
      expect(writes().some((call) => call.init?.method === 'DELETE')).toBe(true);
    });
  });

  it('pré-remplit le formulaire avec le jour sélectionné', async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();
    await screen.findByRole('grid');

    await user.click(screen.getByRole('button', { name: /jeudi 20 août/ }));
    await user.click(screen.getByRole('button', { name: 'Planifier' }));

    expect(screen.getByLabelText('Date')).toHaveValue('2026-08-20');
  });
});

// ── L'abonnement (`PLAN-05`) ──────────────────────────

describe('abonnement calendrier', () => {
  it('affiche l’adresse complète, clé comprise', async () => {
    // Elle doit se lire en entier pour se recopier quand le presse-papier n'est pas
    // disponible — sur un iPhone en contexte non sécurisé, par exemple.
    stub();
    renderScreen();

    expect(
      await screen.findByText('http://localhost:8000/api/calendar/cle.ics'),
    ).toBeInTheDocument();
  });

  it('propose aussi un téléchargement ponctuel', async () => {
    stub();
    renderScreen();

    const link = await screen.findByRole('link', { name: /Télécharger le planning/ });

    expect(link).toHaveAttribute('href', '/api/planning/export.ics');
  });
});
