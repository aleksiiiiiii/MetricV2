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
  {
    index: 1,
    duration_s: 306,
    pace_min_km: 5.1,
    cadence_spm: 166,
    ratio: 0.954,
    stride: 1.181,
    delta: 4.1,
  },
  {
    index: 2,
    duration_s: 299,
    pace_min_km: 4.983,
    cadence_spm: 167,
    ratio: 0.9598,
    stride: 1.201,
    delta: -2.9,
  },
  {
    index: 3,
    duration_s: 305,
    pace_min_km: 5.083,
    cadence_spm: 158,
    ratio: 0.908,
    stride: 1.245,
    delta: 3.1,
  },
  {
    index: 4,
    duration_s: 306,
    pace_min_km: 5.1,
    cadence_spm: 169,
    ratio: 0.9713,
    stride: 1.16,
    delta: 4.1,
  },
  {
    index: 5,
    duration_s: 311,
    pace_min_km: 5.183,
    cadence_spm: 172,
    ratio: 0.9885,
    stride: 1.122,
    delta: 9.1,
  },
  {
    index: 6,
    duration_s: 300,
    pace_min_km: 5.0,
    cadence_spm: 173,
    ratio: 0.9943,
    stride: 1.156,
    delta: -1.9,
  },
  {
    index: 7,
    duration_s: 293,
    pace_min_km: 4.883,
    cadence_spm: 174,
    ratio: 1,
    stride: 1.177,
    delta: -8.9,
  },
  {
    index: 8,
    duration_s: 295,
    pace_min_km: 4.917,
    cadence_spm: 173,
    ratio: 0.9943,
    stride: 1.175,
    delta: -6.9,
  },
  {
    index: 9,
    duration_s: 44,
    pace_min_km: 5.1,
    cadence_spm: 163,
    ratio: 0.9368,
    stride: 1.171,
    delta: 0,
  },
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
  speed_kmh: Math.round((60 / split.pace_min_km) * 100) / 100,
  stride_m: split.stride,
  // Écart à 5,031 min/km, l'allure moyenne des paliers pleins. Le reliquat n'en a pas :
  // son allure est extrapolée, et la comparer à une moyenne de mesures mentirait.
  delta_s_per_km: split.index === 9 ? null : split.delta,
  deviation_ratio: split.index === 9 ? null : Math.round((split.delta / 9.1) * 10000) / 10000,
  // La cadence garde les siens sur le reliquat : elle y est mesurée, pas extrapolée.
  cadence_delta_spm: Math.round((split.cadence_spm - 168) * 10) / 10,
  cadence_deviation_ratio: Math.round(((split.cadence_spm - 168) / 10) * 10000) / 10000,
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
    active_calories: 439,
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
    average_pace_min_km: 5.031,
    fastest_pace_min_km: 4.883,
    slowest_pace_min_km: 5.183,
    pace_spread_s_per_km: 18,
    pace_sd_s_per_km: 5.8,
    negative_split: true,
    cadence_avg_spm: 168,
    cadence_min_spm: 158,
    cadence_drift_spm: 8,
    stride_avg_m: 1.177,
    stride_min_m: 1.122,
    stride_max_m: 1.245,
    deviation_max_s_per_km: 9.1,
    cadence_deviation_max_spm: 10,
  },
  // Une seule course dans l'historique : rien à comparer, et la section n'existe pas.
  context: {
    runs_compared: 1,
    pace_rank: null,
    distance_rank: null,
    best_pace_min_km: null,
    longest_distance_km: null,
    average_pace_min_km: null,
    average_distance_km: null,
    pace_delta_s_per_km: null,
    distance_delta_km: null,
    recent: [],
    pace_domain_min_km: null,
  },
};

/** Une course saisie au clavier : aucune valeur inventée, aucun palier. */
const BARE = {
  run: {
    ...DETAIL.run,
    run_id: '',
    active_calories: null,
    total_calories: null,
    elevation_m: null,
    splits: 0,
  },
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
    average_pace_min_km: null,
    fastest_pace_min_km: null,
    slowest_pace_min_km: null,
    pace_spread_s_per_km: null,
    pace_sd_s_per_km: null,
    negative_split: null,
    cadence_avg_spm: null,
    cadence_min_spm: null,
    cadence_drift_spm: null,
    stride_avg_m: null,
    stride_min_m: null,
    stride_max_m: null,
    deviation_max_s_per_km: null,
    cadence_deviation_max_spm: null,
  },
  context: DETAIL.context,
};

const EMPTY = { run: null, splits: BARE.splits, context: DETAIL.context };

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

describe('page Course — ce que les paliers disent de plus', () => {
  it('nomme la régularité plutôt que de laisser lire un écart-type nu', async () => {
    stub(DETAIL);
    renderRun();

    expect(await screen.findByText('Écart-type')).toBeInTheDocument();
    // 5,8 s/km sur huit kilomètres : le mot fait le travail que le nombre ne fait pas.
    expect(screen.getByText('course très régulière')).toBeInTheDocument();
    expect(screen.getByText('Amplitude')).toBeInTheDocument();
  });

  it('désigne le kilomètre le plus rapide et le plus lent par leur numéro', async () => {
    stub(DETAIL);
    renderRun();

    expect(await screen.findByText('Kilomètre le plus rapide')).toBeInTheDocument();
    // `getAllBy` : les barres d'écart nomment les mêmes kilomètres juste en dessous, et
    // c'est voulu — la tuile dit lequel, la barre dit de combien.
    expect(screen.getAllByText('km 7').length).toBeGreaterThan(0);
    expect(screen.getAllByText('km 5').length).toBeGreaterThan(0);
  });

  it('lit les deux dérives dans leur sens propre, qui sont opposés', async () => {
    stub(DETAIL);
    renderRun();

    // L'allure baisse et la cadence monte : même constat, signes contraires. Les deux
    // phrases sont la seule chose qui empêche d'en conclure l'inverse.
    expect(await screen.findByText('Accélération')).toBeInTheDocument();
    expect(screen.getByText('Foulée plus fréquente')).toBeInTheDocument();
  });

  it('mesure les écarts contre la moyenne des paliers pleins, et non contre la course', async () => {
    stub(DETAIL);
    renderRun();

    // Le repère est l'allure des huit paliers pleins (5,031 min/km), et non celle de la
    // course entière (5,035) qui inclut le reliquat. Les deux tombent sur 5:02 à
    // l'affichage — la distinction se joue dans le calcul, pas dans ce que l'œil lit.
    const note = await screen.findByText(/Chaque barre part de l’allure moyenne/);
    expect(note).toHaveTextContent('5:02 au kilomètre');
  });

  it('ne donne aucun écart au reliquat, dont l’allure est extrapolée', async () => {
    stub(DETAIL);
    renderRun();

    await screen.findByText(/Chaque barre part de l’allure moyenne/);
    // Huit barres portent un écart signé ; la neuvième dit ce qu'elle est.
    expect(screen.getByText('extrapolé')).toBeInTheDocument();
    expect(screen.getByText('+9,1 s')).toBeInTheDocument();
    expect(screen.getByText('-8,9 s')).toBeInTheDocument();
  });

  it('affiche la foulée, que la capture ne portait nulle part', async () => {
    stub(DETAIL);
    renderRun();

    expect(await screen.findByText('Foulée moyenne')).toBeInTheDocument();
    // La tuile et la colonne du tableau portent la même valeur : c'est la moyenne d'un
    // côté, le septième palier de l'autre, et leur coïncidence à deux décimales est un
    // hasard de cette course-ci.
    expect(screen.getAllByText('1,18').length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: 'Longueur de foulée' })).toBeInTheDocument();
  });

  it('tait toute la section « parmi tes courses » quand il n’y en a qu’une', async () => {
    stub(DETAIL);
    renderRun();

    await screen.findByText('Écart-type');
    // Un « 1ᵉʳ sur 1 » serait exact et se lirait comme un record.
    expect(screen.queryByText(/Parmi tes/)).not.toBeInTheDocument();
    expect(screen.queryByText('Rang d’allure')).not.toBeInTheDocument();
  });

  it('accompagne toujours le rang du nombre de courses qui le qualifie', async () => {
    stub({
      ...DETAIL,
      context: {
        runs_compared: 3,
        pace_rank: 2,
        distance_rank: 2,
        best_pace_min_km: 4.8,
        longest_distance_km: 10,
        average_pace_min_km: 5.28,
        average_distance_km: 7.71,
        pace_delta_s_per_km: -14.7,
        distance_delta_km: 0.43,
        recent: [
          { id: 1, date: '2026-08-10', distance_km: 5, pace_min_km: 6, current: false },
          { id: 2, date: '2026-08-15', distance_km: 10, pace_min_km: 4.8, current: false },
          { id: 0, date: '2026-08-21', distance_km: 8.14, pace_min_km: 5.035, current: true },
        ],
        pace_domain_min_km: [6, 4.8],
      },
    });
    renderRun();

    expect(await screen.findByText('Parmi tes 3 courses')).toBeInTheDocument();
    // Comparer un 8 km à un 3 km est bancal : le compte laisse l'utilisateur en juger.
    expect(screen.getAllByText('sur 3').length).toBe(2);
    expect(screen.getByText('15 s/km plus vite que ta moyenne')).toBeInTheDocument();
  });

  it('ne trace la tendance qu’avec les bornes servies par le serveur', async () => {
    stub({
      ...DETAIL,
      context: {
        ...DETAIL.context,
        runs_compared: 2,
        recent: [
          { id: 1, date: '2026-08-10', distance_km: 5, pace_min_km: 6, current: false },
          { id: 0, date: '2026-08-21', distance_km: 8.14, pace_min_km: 5.035, current: true },
        ],
        pace_domain_min_km: [6, 5.035],
      },
    });
    renderRun();

    expect(
      await screen.findByRole('heading', { name: 'Allure des dernières sorties' }),
    ).toBeInTheDocument();
  });
});
