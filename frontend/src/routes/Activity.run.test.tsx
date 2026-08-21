/**
 * La page Course et ses paliers (`ACT-19`).
 *
 * La donnée de tous ces tests est celle des captures du lot C08 : 8,14 km en 40:59, neuf
 * paliers dont le dernier fait `00:44`. Elle est servie **telle que le serveur la rend**,
 * dérive et parts de barres comprises — un test qui recalculerait ces chiffres côté écran
 * validerait exactement ce que l'invariant interdit.
 *
 * Les deux adresses sont montées ensemble : `/activite/course` ouvre la dernière course,
 * `/activite/course/:id` celle qu'on désigne. Monter la seconde seule laisserait la
 * première sans épreuve, et c'est elle que le plan nomme.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createQueryClient } from '@/lib/query';

import { Run } from './activity/Run';

const calls: string[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

/** Les neuf paliers de la course de référence, tels que le serveur les rend. */
const SPLITS = [
  { index: 1, duration_s: 306, pace_min_km: 5.1, cadence_spm: 166, ratio: 0.954 },
  { index: 2, duration_s: 299, pace_min_km: 4.983, cadence_spm: 167, ratio: 0.9598 },
  { index: 3, duration_s: 305, pace_min_km: 5.083, cadence_spm: 158, ratio: 0.908 },
  { index: 4, duration_s: 306, pace_min_km: 5.1, cadence_spm: 169, ratio: 0.9713 },
  { index: 5, duration_s: 311, pace_min_km: 5.183, cadence_spm: 172, ratio: 0.9885 },
  { index: 6, duration_s: 300, pace_min_km: 5.0, cadence_spm: 173, ratio: 0.9943 },
  { index: 7, duration_s: 293, pace_min_km: 4.883, cadence_spm: 174, ratio: 1 },
  { index: 8, duration_s: 295, pace_min_km: 4.917, cadence_spm: 173, ratio: 0.9943 },
  { index: 9, duration_s: 44, pace_min_km: 5.1, cadence_spm: 163, ratio: 0.9368 },
].map((split) => ({
  index: split.index,
  duration_s: split.duration_s,
  distance_km: split.index === 9 ? 0.14 : 1,
  pace_min_km: split.pace_min_km,
  cadence_spm: split.cadence_spm,
  avg_hr: null,
  elevation_m: null,
  partial: split.index === 9,
  cadence_ratio: split.ratio,
}));

const DETAIL = {
  run: {
    id: 0,
    token: 'abc123',
    date: '2026-08-21',
    distance_km: 8.14,
    duration_min: 40.983,
    pace_min_km: 5.035,
    speed_kmh: 11.92,
    avg_hr: null,
    elevation_m: 66,
    cadence_spm: 168,
    note: null,
    source: 'apple',
    run_id: 'a1b2c3',
    total_calories: 492,
    start_time: '19:40:00',
    end_time: '20:21:00',
    split_length_km: 1,
    splits: 9,
  },
  splits: {
    splits: SPLITS,
    full_count: 8,
    partial_count: 1,
    drift_s_per_km: -4.2,
    first_half_pace_min_km: 5.067,
    second_half_pace_min_km: 4.996,
    fastest_index: 7,
    slowest_index: 5,
    pace_domain_min_km: [5.1833, 4.8833],
    cadence_max_spm: 174,
  },
};

/** Une course saisie au clavier : aucune valeur inventée, aucun palier. */
const BARE = {
  run: { ...DETAIL.run, run_id: '', total_calories: null, elevation_m: null, splits: 0 },
  splits: {
    splits: [],
    full_count: 0,
    partial_count: 0,
    drift_s_per_km: null,
    first_half_pace_min_km: null,
    second_half_pace_min_km: null,
    fastest_index: null,
    slowest_index: null,
    pace_domain_min_km: null,
    cadence_max_spm: null,
  },
};

const EMPTY = { run: null, splits: BARE.splits };

function stub(body: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      calls.push(input as string);
      return Promise.resolve(json(status, body));
    }),
  );
}

function renderRun(at = '/activite/course') {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { retry: false } });

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/activite/course" element={<Run />} />
          <Route path="/activite/course/:id" element={<Run />} />
        </Routes>
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

describe('page Course', () => {
  it('lit la dernière course sans identifiant dans l’adresse', async () => {
    stub(DETAIL);
    renderRun();

    expect(await screen.findByText('8,14')).toBeInTheDocument();
    expect(calls.some((url) => url.includes('/api/activity/runs/latest'))).toBe(true);
  });

  it('lit la course désignée par l’adresse', async () => {
    stub(DETAIL);
    renderRun('/activite/course/3');

    expect(await screen.findByText('8,14')).toBeInTheDocument();
    expect(calls.some((url) => url.includes('/api/activity/runs/3/splits'))).toBe(true);
  });

  it('affiche distance, durée et allure moyenne en tête', async () => {
    stub(DETAIL);
    renderRun();

    expect(await screen.findByText('8,14')).toBeInTheDocument();
    expect(screen.getByText('40:59')).toBeInTheDocument();
    expect(screen.getByText('5:02')).toBeInTheDocument();
  });

  it('dit la dérive en toutes lettres, parce que le signe se lit à l’envers', async () => {
    stub(DETAIL);
    renderRun();

    // `-4,2` seul laisserait conclure l'inverse : une allure qui **baisse** est une
    // course qui va plus vite.
    expect(await screen.findByText('Accélération')).toBeInTheDocument();
    expect(screen.getByText('4,2 s/km')).toBeInTheDocument();
    // Le chiffre n'est **pas** répété dans le détail : la tuile le porte déjà, et les
    // deux collés se lisaient « 4,2 s/km · 4,2 s/km plus vite… ».
    expect(screen.getByText('gagnées sur la seconde moitié de la course')).toBeInTheDocument();
  });

  it('marque le reliquat au lieu de le compter pour un neuvième kilomètre', async () => {
    stub(DETAIL);
    renderRun();

    expect(await screen.findAllByText('reliquat')).not.toHaveLength(0);
    // Huit lignes numérotées, et une neuvième qui porte ce qu'elle est.
    const table = screen.getByRole('table');
    expect(within(table).getByText('8')).toBeInTheDocument();
    expect(within(table).queryByText('9')).not.toBeInTheDocument();
  });

  it('nomme les calories totales plutôt que d’afficher un chiffre seul', async () => {
    stub(DETAIL);
    renderRun();

    expect(await screen.findByText('Calories totales')).toBeInTheDocument();
    expect(screen.getByText('492')).toBeInTheDocument();
    expect(screen.getByText('métabolisme de base compris')).toBeInTheDocument();
  });

  it('dit ce que coûte le prochain geste quand aucune course n’existe', async () => {
    stub(EMPTY);
    renderRun();

    expect(await screen.findByText('Aucune course enregistrée')).toBeInTheDocument();
    // Aucun zéro qui passerait pour une mesure.
    expect(screen.queryByText('0,00')).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('ne présente pas une course sans paliers comme un défaut', async () => {
    stub(BARE);
    renderRun();

    expect(await screen.findByText('Pas de paliers pour cette course')).toBeInTheDocument();
    // Les chiffres de la course, eux, restent là : elle est entière.
    expect(screen.getByText('8,14')).toBeInTheDocument();
    expect(screen.queryByText('Accélération')).not.toBeInTheDocument();
  });

  it('affiche l’erreur du serveur plutôt qu’un écran vide', async () => {
    stub({ code: 'storage_unavailable', message: 'Stockage injoignable.' }, 503);
    renderRun();

    expect(await screen.findByText('Course indisponible')).toBeInTheDocument();
  });

  it('annonce la page avant même que la donnée arrive', async () => {
    stub(DETAIL);
    renderRun();

    // L'en-tête est rendu d'emblée : un « chargement… » seul ne dit pas où l'on est.
    expect(screen.getByRole('heading', { name: 'Course' })).toBeInTheDocument();
    expect(await screen.findByText('8,14')).toBeInTheDocument();
  });
});
