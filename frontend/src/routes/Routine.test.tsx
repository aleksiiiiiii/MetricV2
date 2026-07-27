import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import { createQueryClient } from '@/lib/query';

import { Routine } from './Routine';

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

const HYDRATION = {
  stats: {
    today_ml: 1250,
    target_ml: 2000,
    ratio: 0.625,
    average_7d_ml: 1800,
    average_30d_ml: 1650,
    days_reached: 12,
    days_counted: 30,
  },
  series: [
    { date: '2026-07-25', volume_ml: 2100, reached: true },
    { date: '2026-07-26', volume_ml: 1250, reached: false },
  ],
  today: [
    {
      id: 0,
      token: 'jeton-eau',
      datetime: '2026-07-26T08:15:00+02:00',
      volume_ml: 500,
      kind: 'eau',
    },
    {
      id: 1,
      token: 'jeton-eau-2',
      datetime: '2026-07-26T12:40:00+02:00',
      volume_ml: 750,
      kind: null,
    },
  ],
  presets_ml: [250, 500, 750],
  kinds: ['eau', 'café'],
};

const CHECKLIST = {
  date: '2026-07-26',
  items: [
    {
      schedule_id: 's1',
      name: 'Créatine',
      dose: 5,
      unit: 'g',
      time: '08:00',
      cadence_label: 'tous les jours',
      taken: true,
      taken_at: '2026-07-26T08:05:00+02:00',
      intake_id: 0,
      intake_token: 'jeton-prise',
      streak: 41,
    },
    {
      schedule_id: 's2',
      name: 'Magnésium',
      dose: 300,
      unit: 'mg',
      time: '21:00',
      cadence_label: 'tous les jours',
      taken: false,
      taken_at: null,
      intake_id: null,
      intake_token: null,
      streak: 0,
    },
  ],
  ratio: { taken: 1, planned: 2, ratio: 0.5, complete: false },
};

const SCHEDULE = [
  {
    id: 0,
    token: 'jeton-planning',
    schedule_id: 's1',
    name: 'Whey',
    dose: 30,
    unit: 'g',
    time: '12:30',
    frequency: 'window:min_count=1;window_days=2',
    cadence_label: 'un jour sur deux',
    active: true,
    created: '2026-01-01',
  },
];

function stub(custom?: (url: string, init?: RequestInit) => Response | undefined) {
  // `custom` peut rendre une promesse déguisée : c'est ce qui permet de retenir une
  // réponse et d'observer l'état optimiste.
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    const override = custom?.(url, init);
    if (override) return Promise.resolve(override);

    if (url.includes('/supplements/today')) return Promise.resolve(json(200, CHECKLIST));
    if (url.includes('/supplements/schedule')) return Promise.resolve(json(200, SCHEDULE));
    if (url.includes('/supplements/units')) return Promise.resolve(json(200, ['g', 'mg']));
    if (url.includes('/hydration')) return Promise.resolve(json(200, HYDRATION));
    return Promise.resolve(json(200, {}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderRoutine() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Toaster>
          <Routine />
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

describe('écran Routine', () => {
  it("affiche le total du jour face à l'objectif", async () => {
    stub();
    renderRoutine();

    expect(await screen.findByText('1,25 L / 2 L')).toBeInTheDocument();
    expect(screen.getByText(/moyenne 7 j : 1,8 L/)).toBeInTheDocument();
  });

  it('propose les raccourcis paramétrés par le serveur', async () => {
    // `HYD-02` : le client ne code aucune valeur en dur.
    stub();
    renderRoutine();

    expect(await screen.findByRole('button', { name: '+ 250 ml' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '+ 500 ml' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '+ 750 ml' })).toBeInTheDocument();
  });

  it('enregistre une prise en un geste', async () => {
    stub();
    renderRoutine();

    await userEvent.click(await screen.findByRole('button', { name: '+ 500 ml' }));

    await waitFor(() => {
      const post = calls.find(
        (call) => call.init?.method === 'POST' && call.url.includes('/hydration'),
      );
      expect(JSON.parse(post?.init?.body as string)).toMatchObject({ volume_ml: 500 });
    });
  });

  it('permet de rattraper une erreur de saisie', async () => {
    // `HYD-04` : correction d'une prise du jour, sous garde.
    stub();
    renderRoutine();

    await userEvent.click(
      await screen.findByRole('button', { name: /Supprimer la prise de 08:15/ }),
    );

    await waitFor(() => {
      const remove = calls.find((call) => call.init?.method === 'DELETE');
      expect(remove?.url).toContain('/api/hydration/0');
      expect((remove?.init?.headers as Record<string, string>)['If-Match']).toBe('jeton-eau');
    });
  });

  it('groupe la checklist par moment de la journée', async () => {
    stub();
    renderRoutine();

    expect(await screen.findByText('Matin')).toBeInTheDocument();
    expect(screen.getByText('Soir')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Créatine/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('affiche la série par item', async () => {
    stub();
    renderRoutine();

    expect(await screen.findByText('41 j')).toBeInTheDocument();
  });

  it('coche localement avant la réponse du serveur', async () => {
    // `SUP-04` : attendre un aller-retour vers Nextcloud pour voir une case se cocher
    // condamnerait la saisie en un geste.
    let release: ((value: Response) => void) | undefined;
    stub((url, init) => {
      if (init?.method === 'POST' && url.includes('/supplements/today')) {
        // La réponse est retenue : on observe l'écran pendant que le serveur réfléchit.
        return new Promise<Response>((resolve) => {
          release = resolve;
        }) as unknown as Response;
      }
      return undefined;
    });
    renderRoutine();

    await userEvent.click(await screen.findByRole('button', { name: /Magnésium/ }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Magnésium/ })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
    });

    release?.(json(200, CHECKLIST));
  });

  it('restaure la case si le serveur refuse', async () => {
    // Sans restauration, l'écran resterait sur un état que le serveur a refusé.
    stub((url, init) =>
      init?.method === 'POST' && url.includes('/supplements/today')
        ? json(503, { code: 'storage_unavailable', message: 'Le stockage est injoignable.' })
        : undefined,
    );
    renderRoutine();

    await userEvent.click(await screen.findByRole('button', { name: /Magnésium/ }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Magnésium/ })).toHaveAttribute(
        'aria-pressed',
        'false',
      );
    });
  });

  it('décoche en supprimant la prise du jour', async () => {
    // `SUP-05`.
    stub();
    renderRoutine();

    await userEvent.click(await screen.findByRole('button', { name: /Créatine/ }));

    await waitFor(() => {
      const remove = calls.find(
        (call) => call.init?.method === 'DELETE' && call.url.includes('/supplements/today'),
      );
      expect(remove?.url).toContain('/api/supplements/today/s1');
    });
  });

  it('affiche la cadence telle que le serveur la formule', async () => {
    // Le client ne reconstruit pas la phrase : deux formulations divergeraient.
    stub();
    renderRoutine();

    expect(await screen.findByText('un jour sur deux')).toBeInTheDocument();
  });

  it('reste lisible sans aucun supplément au planning', async () => {
    stub((url) =>
      url.includes('/supplements/today')
        ? json(200, {
            date: '2026-07-26',
            items: [],
            ratio: { taken: 0, planned: 0, ratio: 0, complete: false },
          })
        : undefined,
    );
    renderRoutine();

    expect(await screen.findByText('Aucun supplément au planning')).toBeInTheDocument();
  });
});
