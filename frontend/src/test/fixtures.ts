/**
 * Réponses de référence, partagées par les tests d'écran.
 *
 * Le tableau de bord est réclamé dès que la coquille s'affiche (`AGG-01`) : tout test qui
 * fait apparaître un écran authentifié doit savoir répondre à cet appel. Recopier
 * l'objet dans chaque fichier de test le ferait diverger du contrat au premier champ
 * ajouté — et un test qui ment sur la forme de la réponse ne prouve plus rien.
 */

import type { DashboardView } from '@/features/aggregates/api';
import type { DayInspection, GridsView, HeatDay, TracksView } from '@/features/heatmap/api';
import type { NotificationsView } from '@/features/notifications/api';
import type { SettingsView } from '@/features/settings/api';

export const DASHBOARD: DashboardView = {
  date: '2026-07-27',
  weight: {
    latest_kg: 72.4,
    latest_date: '2026-07-27',
    change_kg: -1.2,
    to_target_kg: 2.4,
    target_kg: 70,
    min_kg: 71.8,
    max_kg: 76.2,
    amplitude_kg: 4.4,
    count: 42,
  },
  training: {
    sessions_total: 118,
    minutes_total: 6420,
    week: {
      week_start: '2026-07-27',
      minutes: 106,
      sessions: 2,
      distance_km: 8.4,
      pace_min_km: 5.26,
    },
    // `ratio` est **servi** : l'échelle de l'histogramme se calcule là où la fenêtre
    // entière est sous la main, plus par un `Math.max` à l'écran.
    weeks: [
      { week_start: '2026-06-08', minutes: 180, sessions: 3, ratio: 0.6 },
      { week_start: '2026-06-15', minutes: 240, sessions: 4, ratio: 0.8 },
      { week_start: '2026-06-22', minutes: 120, sessions: 2, ratio: 0.4 },
      { week_start: '2026-06-29', minutes: 300, sessions: 5, ratio: 1 },
      { week_start: '2026-07-06', minutes: 0, sessions: 0, ratio: 0 },
      { week_start: '2026-07-13', minutes: 210, sessions: 4, ratio: 0.7 },
      { week_start: '2026-07-20', minutes: 260, sessions: 4, ratio: 0.87 },
      { week_start: '2026-07-27', minutes: 106, sessions: 2, ratio: 0.35 },
    ],
    split: [
      { kind: 'run', label: 'Course', sessions: 46, minutes: 2300, ratio: 0.39 },
      { kind: 'strength', label: 'Musculation', sessions: 60, minutes: 3600, ratio: 0.51 },
      { kind: 'other', label: 'Autre', sessions: 12, minutes: 520, ratio: 0.1 },
    ],
  },
  nutrition: {
    protein_g: 96,
    protein_target_g: 150,
    protein_ratio: 0.64,
    added_sugar_g: 38,
    added_sugar_max_g: 30,
    over_sugar: true,
    calories: 1840,
    calories_known: 3,
    meals: 3,
  },
  hydration: {
    today_ml: 1250,
    target_ml: 2000,
    ratio: 0.625,
    average_7d_ml: 1800,
    average_30d_ml: 1650,
    days_reached: 12,
    days_counted: 30,
  },
  supplements: { taken: 2, planned: 3, ratio: 0.667, complete: false },
  streak: {
    current: 12,
    longest: 41,
    active_days: 180,
    last_seven: [
      { date: '2026-07-21', active: true, sources: ['weight', 'hydration'] },
      { date: '2026-07-22', active: true, sources: ['runs'] },
      { date: '2026-07-23', active: false, sources: [] },
      { date: '2026-07-24', active: true, sources: ['meals'] },
      { date: '2026-07-25', active: true, sources: ['weight'] },
      { date: '2026-07-26', active: true, sources: ['workouts', 'supplements'] },
      { date: '2026-07-27', active: true, sources: ['weight', 'meals', 'hydration'] },
    ],
  },
  series: {
    metric: 'weight',
    label: 'Poids',
    unit: 'kg',
    granularity: 'day',
    subject: null,
    range: '3m',
    points: [
      { date: '2026-05-04', value: 76.2 },
      { date: '2026-06-01', value: 74.5 },
      { date: '2026-07-01', value: 73.1 },
      { date: '2026-07-27', value: 72.4 },
    ],
    stats: {
      latest: 72.4,
      latest_date: '2026-07-27',
      change: -3.8,
      average: 74.05,
      minimum: 72.4,
      maximum: 76.2,
      count: 4,
    },
  },
  highlight: 'activity',
  day: {
    date: '2026-07-27',
    tasks: [
      {
        key: 'hydration',
        label: 'Eau',
        done: 1250,
        target: 2000,
        unit: 'ml',
        ratio: 0.625,
        complete: false,
        remaining: 'encore 750 ml',
      },
      {
        key: 'protein',
        label: 'Protéines',
        done: 96,
        target: 150,
        unit: 'g',
        ratio: 0.64,
        complete: false,
        remaining: 'encore 54 g',
      },
      {
        key: 'supplements',
        label: 'Suppléments',
        done: 2,
        target: 3,
        unit: 'prises',
        ratio: 0.667,
        complete: false,
        remaining: 'encore 1 prise',
      },
    ],
    done: 0,
    total: 3,
    logged: true,
  },
  goal: null,
  next_session: null,
};

const DEFAULT_VALUES = {
  target_weight_kg: 70,
  target_protein_g: 150,
  max_added_sugar_g: 30,
  target_hydration_ml: 2000,
  hydration_presets_ml: [250, 500, 750],
  heatmap_metric: 'activity',
  // Vide, comme le sert le serveur tant que le pont n'est pas branché (**D1**).
  cadence_base_url: '',
};

export const SETTINGS: SettingsView = {
  values: { ...DEFAULT_VALUES, target_weight_kg: 68 },
  defaults: DEFAULT_VALUES,
  stored: ['target_weight_kg'],
  token: 'jeton-reglages',
};

// ── Notifications (`NOT-01`, `NOT-03`) ────────────────

/**
 * L'état par défaut d'une installation neuve : **aucun rappel, aucun appareil**.
 *
 * C'est délibérément l'état vide qui sert de référence. Un fixture qui poserait des
 * créneaux d'office ferait passer pour normal ce que le lot interdit — le défaut est le
 * silence, et chaque créneau doit être un choix explicite.
 */
export const NOTIFICATIONS: NotificationsView = {
  push: {
    configured: false,
    public_key: null,
    message:
      'Aucune clé de notification n’est configurée : les rappels sont hors service. ' +
      'Génère une paire avec « make vapid-keys ».',
  },
  devices: [],
  reminders: { supplements: null, hydration: null, meals: null, workout: null },
  token: 'jeton-reglages',
};

/** La même chose, mais côté serveur tout est prêt et un appareil est déjà abonné. */
export const NOTIFICATIONS_READY: NotificationsView = {
  push: {
    configured: true,
    public_key: 'BLP-9iZ4Z6daUOism3xCRQvnzpucJdfuG4dJRBwVajbC5CnwsBnYLxRK978jARjZa',
    message:
      'Les notifications sont configurées côté serveur. Chaque appareil doit ensuite ' +
      'être autorisé une fois, depuis lui-même.',
  },
  devices: [{ id: 'app1', created: '2026-08-01', label: 'iPhone', hint: 'ppareil-1' }],
  reminders: { supplements: '20:00', hydration: null, meals: null, workout: null },
  token: 'jeton-reglages',
};

// ── Assiduité (`HEAT` v2 §8) ──────────────────────────

/**
 * Deux pistes, choisies pour ce qu'elles opposent : une quotidienne, qui peut être
 * `missed` au jour, et une hebdomadaire, qui ne l'est **jamais** (`HEAT-11`).
 *
 * La plage est volontairement courte — sept jours au lieu de 371. Ce que les tests
 * d'écran vérifient est le rendu de chaque état, pas la géométrie de la grille, qui a sa
 * propre batterie côté composant.
 */
function heatDay(
  date: string,
  state: HeatDay['state'],
  level = 0,
  value = 0,
  reason: HeatDay['reason'] = null,
): HeatDay {
  return { date, value, state, level, reason };
}

const WATER_GRID: GridsView['grids'][number] = {
  track: {
    id: 'eau',
    label: 'Eau',
    unit: 'ml',
    binary: false,
    accent: 'signal',
    source: 'hydration.intake',
    levels: [1000, 1500, 2000, 2500],
    validation_threshold: 1500,
    created: '2026-01-01',
  },
  cadence: {
    type: 'daily',
    params: {},
    label: 'tous les jours',
    serialized: 'daily',
    valid_from: null,
  },
  range: { from: '2026-07-20', to: '2026-07-26' },
  days: [
    heatDay('2026-07-20', 'done', 2, 1800),
    heatDay('2026-07-21', 'missed'),
    heatDay('2026-07-22', 'done', 4, 2600),
    heatDay('2026-07-23', 'off', 0, 0, 'neutralised'),
    heatDay('2026-07-24', 'done', 1, 1500),
    heatDay('2026-07-25', 'off', 0, 700, 'pending'),
    heatDay('2026-07-26', 'off', 0, 0, 'future'),
  ],
  weeks: null,
  stats: {
    validated_days: 3,
    expected_days: 4,
    compliance: 0.75,
    longest_streak: 3,
    current_streak: 3,
    best_day: '2026-07-22',
    best_value: 2600,
    total: 6600,
  },
};

const TORSO_GRID: GridsView['grids'][number] = {
  track: {
    id: 'torse',
    label: 'Torse',
    unit: 'série',
    binary: false,
    accent: 'effort',
    source: 'activity.muscle_group',
    levels: [1, 3, 6, 10],
    validation_threshold: 1,
    created: '2026-01-01',
  },
  cadence: {
    type: 'per_week',
    params: { count: 2 },
    label: '2 fois par semaine',
    serialized: 'per_week:count=2',
    valid_from: null,
  },
  range: { from: '2026-07-20', to: '2026-07-26' },
  days: [
    heatDay('2026-07-20', 'done', 3, 8),
    heatDay('2026-07-21', 'off'),
    heatDay('2026-07-22', 'off'),
    heatDay('2026-07-23', 'off'),
    heatDay('2026-07-24', 'off'),
    heatDay('2026-07-25', 'off', 0, 0, 'pending'),
    heatDay('2026-07-26', 'off', 0, 0, 'future'),
  ],
  weeks: [{ start: '2026-07-20', status: 'partial', done: 1, expected: 2 }],
  stats: {
    validated_days: 1,
    expected_days: 2,
    compliance: 0.5,
    longest_streak: 1,
    current_streak: 1,
    best_day: '2026-07-20',
    best_value: 8,
    total: 8,
  },
};

export const GRIDS: GridsView = {
  range: { from: '2026-07-20', to: '2026-07-26' },
  grids: [WATER_GRID, TORSO_GRID],
};

export const DAY_DETAIL: DayInspection = {
  track: TORSO_GRID.track,
  day: heatDay('2026-07-20', 'done', 3, 8),
  entries: [
    {
      label: 'Développé couché',
      value: 4,
      unit: 'série',
      time: null,
      sets: 4,
      reps: 8,
      weight_kg: 80,
      muscle_group: 'pectoraux',
      distance_km: null,
      duration_min: null,
      pace_min_km: null,
      dose: null,
      dose_unit: null,
      note: null,
    },
    {
      label: 'Écarté poulie',
      value: 4,
      unit: 'série',
      time: null,
      sets: 4,
      reps: 12,
      weight_kg: 20,
      muscle_group: 'pectoraux',
      distance_km: null,
      duration_min: null,
      pace_min_km: null,
      dose: null,
      dose_unit: null,
      note: 'dernière série en dégressif',
    },
  ],
};

export const TRACKS: TracksView = {
  tracks: [
    {
      id: 0,
      token: 'jeton-eau',
      track_id: 'eau',
      label: 'Eau',
      source: 'hydration.intake',
      source_label: 'Volume bu',
      unit: 'ml',
      filter: '',
      validation_threshold: 1500,
      levels: [1000, 1500, 2000, 2500],
      binary: false,
      accent: 'signal',
      position: 0,
      active: true,
      created: '2026-01-01',
      cadence: {
        type: 'daily',
        params: {},
        label: 'tous les jours',
        serialized: 'daily',
        valid_from: null,
      },
      cadence_history: [],
    },
    {
      id: 1,
      token: 'jeton-torse',
      track_id: 'torse',
      label: 'Torse',
      source: 'activity.muscle_group',
      source_label: "Séries d'un groupe musculaire",
      unit: 'série',
      filter: 'pectoraux;épaules',
      validation_threshold: 1,
      levels: [1, 3, 6, 10],
      binary: false,
      accent: 'effort',
      position: 1,
      active: true,
      created: '2026-01-01',
      cadence: {
        type: 'per_week',
        params: { count: 2 },
        label: '2 fois par semaine',
        serialized: 'per_week:count=2',
        valid_from: '2026-01-01',
      },
      cadence_history: [],
    },
  ],
  sources: [
    { key: 'hydration.intake', label: 'Volume bu', unit: 'ml', filter_label: null },
    {
      key: 'activity.muscle_group',
      label: "Séries d'un groupe musculaire",
      unit: 'série',
      filter_label: 'Groupes musculaires',
    },
  ],
  off_days: [
    {
      id: 0,
      token: 'jeton-off',
      off_id: 'o1',
      track_id: 'eau',
      date_from: '2026-07-23',
      date_to: '2026-07-23',
      reason: 'grippe',
      days: 1,
    },
  ],
  highlight: 'eau',
  accents: ['signal', 'effort', 'load', 'recover'],
};
