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

function stub(dashboard: unknown = DASHBOARD) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    if (url.includes('/aggregates/dashboard')) return Promise.resolve(json(200, dashboard));
    if (url.includes('/aggregates/metrics')) return Promise.resolve(json(200, CATALOGUE));
    if (url.includes('/aggregates/series')) return Promise.resolve(json(200, HYDRATION_SERIES));
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
    expect(await screen.findByText(/−1,2 kg sur les 8 dernières pesées/)).toBeInTheDocument();
    expect(screen.getAllByText('72,4').length).toBeGreaterThan(0);
    expect(screen.getByText(/2 séances, 8,4 km/)).toBeInTheDocument();
    expect(screen.getByText('1,25 L')).toBeInTheDocument();
    expect(screen.getByText(/record 41 jours · 180 jours suivis/)).toBeInTheDocument();
  });

  it('trace la série livrée avec le tableau de bord', async () => {
    stub();
    renderDashboard();

    expect(await screen.findByRole('img', { name: 'Poids' })).toBeInTheDocument();
    expect(screen.getByText(/−3,8/)).toBeInTheDocument();
  });

  it('nomme la part qui n’est ni course ni musculation', async () => {
    stub();
    renderDashboard();

    expect(await screen.findByText('Course')).toBeInTheDocument();
    expect(screen.getByText('Musculation')).toBeInTheDocument();
    expect(screen.getByText('Autre')).toBeInTheDocument();
  });

  it('montre les sept derniers jours, trous compris', async () => {
    // `AGG-03` : la plage est complète, un jour sans donnée est présent et vide.
    stub();
    renderDashboard();

    await screen.findByText('Sept derniers jours');

    expect(screen.getByText('23/07')).toBeInTheDocument();
    expect(screen.getByTitle('aucune donnée')).toBeInTheDocument();
    expect(screen.getByTitle('poids, repas, hydratation')).toBeInTheDocument();
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
    });
    renderDashboard();

    expect(await screen.findByText('Aucun relevé aujourd’hui')).toBeInTheDocument();
    // Un tiret, jamais un zéro qui passerait pour une mesure.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
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
