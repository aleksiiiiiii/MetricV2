/**
 * La page « Toutes tes courses » (`ACT-20`).
 *
 * Les chiffres sont servis **tels que le serveur les rend** — records par bande, volumes
 * mensuels, fenêtre glissante. Un test qui les recalculerait côté écran validerait
 * exactement ce que l'invariant interdit.
 *
 * Ce que ces tests gardent surtout, ce sont les **réserves** : la page compare des sorties
 * entre elles, où deux allures ne veulent plus dire la même chose, et la moitié de son
 * travail consiste à le dire plutôt qu'à le taire.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createQueryClient } from '@/lib/query';

import { Runs } from './activity/Runs';

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

function run(id: number, date: string, distance: number, minutes: number, splits = 0) {
  return {
    id,
    token: `t${String(id)}`,
    date,
    distance_km: distance,
    duration_min: minutes,
    pace_min_km: Math.round((minutes / distance) * 1000) / 1000,
    speed_kmh: Math.round((60 / (minutes / distance)) * 100) / 100,
    avg_hr: null,
    elevation_m: null,
    cadence_spm: null,
    note: null,
    source: splits > 0 ? 'apple' : 'manual',
    run_id: splits > 0 ? 'a1b2c3' : '',
    active_calories: null,
    total_calories: null,
    start_time: null,
    end_time: null,
    split_length_km: null,
    splits,
  };
}

/** Six sorties sur trois mois, la plus récente d'abord — comme le serveur les rend. */
const PROGRESS = {
  runs: [
    run(5, '2026-08-21', 8.14, 40.983, 9),
    run(4, '2026-08-02', 8.0, 41.6),
    run(3, '2026-07-12', 12.0, 65.0),
    run(2, '2026-06-21', 10.2, 56.1),
    run(1, '2026-06-07', 5.2, 28.1),
    run(0, '2026-06-01', 3.2, 17.6),
  ],
  total_runs: 6,
  total_distance_km: 46.74,
  total_minutes: 249.4,
  overall_pace_min_km: 5.336,
  best_pace_min_km: 5.035,
  best_pace_index: 5,
  best_pace_day: '2026-08-21',
  longest_distance_km: 12.0,
  longest_distance_index: 3,
  longest_distance_day: '2026-07-12',
  longest_duration_min: 65.0,
  bands: [
    {
      label: 'Moins de 5 km',
      runs: 1,
      best_pace_min_km: 5.5,
      best_index: 0,
      best_day: '2026-06-01',
      average_pace_min_km: 5.5,
      total_distance_km: 3.2,
    },
    {
      label: '5 à 10 km',
      runs: 3,
      best_pace_min_km: 5.035,
      best_index: 5,
      best_day: '2026-08-21',
      average_pace_min_km: 5.2,
      total_distance_km: 21.34,
    },
    {
      label: '10 km et plus',
      runs: 2,
      best_pace_min_km: 5.417,
      best_index: 3,
      best_day: '2026-07-12',
      average_pace_min_km: 5.46,
      total_distance_km: 22.2,
    },
  ],
  months: [
    { month: '2026-06', runs: 3, distance_km: 18.6, minutes: 101.8, pace_min_km: 5.473 },
    { month: '2026-07', runs: 1, distance_km: 12.0, minutes: 65.0, pace_min_km: 5.417 },
    { month: '2026-08', runs: 2, distance_km: 16.14, minutes: 82.583, pace_min_km: 5.117 },
  ],
  window: {
    size: 3,
    recent_pace_min_km: 5.117,
    previous_pace_min_km: 5.473,
    pace_delta_s_per_km: -21.4,
    recent_distance_km: 9.38,
    previous_distance_km: 6.2,
    distance_delta_km: 3.18,
  },
  pace_domain_min_km: [5.5, 5.035],
  volume_domain_km: [12.0, 18.6],
  distance_domain_km: [3.2, 12.0],
};

/** Une première sortie : rien à comparer, et la page ne doit rien inventer. */
const ALONE = {
  ...PROGRESS,
  runs: [PROGRESS.runs[0]],
  total_runs: 1,
  total_distance_km: 8.14,
  total_minutes: 40.983,
  months: [{ month: '2026-08', runs: 1, distance_km: 8.14, minutes: 40.983, pace_min_km: 5.035 }],
  window: {
    size: 0,
    recent_pace_min_km: null,
    previous_pace_min_km: null,
    pace_delta_s_per_km: null,
    recent_distance_km: null,
    previous_distance_km: null,
    distance_delta_km: null,
  },
};

const EMPTY = {
  ...PROGRESS,
  runs: [],
  total_runs: 0,
  total_distance_km: 0,
  total_minutes: 0,
  overall_pace_min_km: null,
  best_pace_min_km: null,
  best_pace_index: null,
  bands: [],
  months: [],
  window: ALONE.window,
};

function stub(body: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(json(status, body))),
  );
}

function renderRuns() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={['/activite/courses']}>
        <Routes>
          <Route path="/activite/courses" element={<Runs />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.setItem('metric.token', 'jeton');
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('page Toutes tes courses', () => {
  it('dit ce que coûte le prochain geste plutôt que d’afficher des zéros', async () => {
    stub(EMPTY);
    renderRuns();

    expect(await screen.findByText('Aucune course enregistrée')).toBeInTheDocument();
    // Pas de « 0 km » ni de « 0:00 » : rien n'a été couru, ce n'est pas une mesure.
    expect(screen.queryByText('Allure totale')).not.toBeInTheDocument();
  });

  it('nomme la progression en toutes lettres plutôt que de montrer un signe', async () => {
    stub(PROGRESS);
    renderRuns();

    // -21,4 s/km est une accélération : le signe seul se lit à l'envers.
    expect(await screen.findByText('Tu accélères')).toBeInTheDocument();
    expect(screen.getByText('21,4 s/km')).toBeInTheDocument();
  });

  it('accompagne la fenêtre de sa réserve : les distances y restent mélangées', async () => {
    stub(PROGRESS);
    renderRuns();

    await screen.findByText('Tu accélères');
    expect(screen.getByText(/Les distances y restent mélangées/)).toBeInTheDocument();
    // Et elle dit combien de sorties elle compare, jamais « les dernières » en vague.
    expect(
      screen.getByText(/sur tes 3 dernières sorties contre les 3 d’avant/),
    ).toBeInTheDocument();
  });

  it('tait la section « ce qui a changé » quand une seule course existe', async () => {
    stub(ALONE);
    renderRuns();

    await screen.findByText('Sorties');
    // Une sortie ne se compare à rien, et une fenêtre de zéro n'est pas une tendance.
    expect(screen.queryByText('Tu accélères')).not.toBeInTheDocument();
    expect(screen.queryByText('Allure stable')).not.toBeInTheDocument();
  });

  it('compare les records par bande, la seule façon honnête de le faire', async () => {
    stub(PROGRESS);
    renderRuns();

    expect(await screen.findByText('5 à 10 km')).toBeInTheDocument();
    expect(screen.getByText('Moins de 5 km')).toBeInTheDocument();
    expect(screen.getByText('10 km et plus')).toBeInTheDocument();
    // La phrase qui porte la réserve, sans quoi les trois tuiles se compareraient entre elles.
    expect(screen.getByText(/est une meilleure course que/)).toBeInTheDocument();
  });

  it('garde une bande jamais courue plutôt que de la faire disparaître', async () => {
    stub({
      ...PROGRESS,
      bands: [
        PROGRESS.bands[0],
        PROGRESS.bands[1],
        {
          label: '10 km et plus',
          runs: 0,
          best_pace_min_km: null,
          best_index: null,
          best_day: null,
          average_pace_min_km: null,
          total_distance_km: 0,
        },
      ],
    });
    renderRuns();

    // Ne l'avoir jamais courue **est** une information, et un tiret la dit sans mentir.
    expect(await screen.findByText('jamais couru')).toBeInTheDocument();
  });

  it('mène de chaque ligne au détail de sa course', async () => {
    stub(PROGRESS);
    renderRuns();

    const row = await screen.findByRole('link', { name: /21\/08/ });
    expect(row).toHaveAttribute('href', '/activite/course/5');
  });

  it('marque la meilleure allure et les courses qui portent des paliers', async () => {
    stub(PROGRESS);
    renderRuns();

    const best = await screen.findByRole('link', { name: /21\/08/ });
    // L'étoile vient du serveur (`best_pace_index`), pas d'une comparaison faite ici.
    expect(best).toHaveTextContent('★');
    expect(best).toHaveTextContent('9');

    // Une course saisie au clavier n'a pas de badge : aucun « 0 » qui se lirait comme
    // une mesure.
    const plain = screen.getByRole('link', { name: /02\/08/ });
    expect(plain).not.toHaveTextContent('9');
  });

  it('présente le volume mensuel comme la seule série sans précaution', async () => {
    stub(PROGRESS);
    renderRuns();

    expect(await screen.findByRole('heading', { name: 'Kilomètres par mois' })).toBeInTheDocument();
    expect(screen.getByText(/des kilomètres sont des kilomètres/)).toBeInTheDocument();
  });

  it('porte la distance en abscisse au lieu de la reléguer en avertissement', async () => {
    stub(PROGRESS);
    renderRuns();

    // La courbe d'allure au fil du temps a été remplacée : elle mélangeait les distances
    // et le disait en trois lignes de mise en garde. Le nuage met la distance sur un axe,
    // donc la réserve **est** le graphique et il n'y a plus rien à avertir.
    expect(
      await screen.findByRole('heading', { name: 'Chaque sortie, à sa distance' }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Cette courbe mélange les distances/)).not.toBeInTheDocument();
    expect(screen.getByText(/celui du haut est le meilleur/)).toBeInTheDocument();
  });

  it('marque la dernière sortie, qu’un nuage ne laisse pas retrouver seul', async () => {
    stub(PROGRESS);
    renderRuns();

    expect(await screen.findByText('L’anneau marque ta dernière sortie.')).toBeInTheDocument();
  });

  it('dit la panne au lieu de laisser la page vide', async () => {
    // Une erreur **non transitoire** : `storage_unavailable` et tout `5xx` sont rejoués
    // deux fois par `shouldRetry`, et la temporisation dépasse l'attente d'un `findBy`.
    // Ce que ce test garde est le rendu de l'erreur, pas la politique de reprise.
    stub({ code: 'validation_failed', message: 'Requête invalide.' }, 422);
    renderRuns();

    expect(await screen.findByText('Courses indisponibles')).toBeInTheDocument();
    // Le message vient du serveur et s'affiche tel quel : le client décide sur le code.
    expect(screen.getByText('Requête invalide.')).toBeInTheDocument();
  });
});
