/**
 * Réponses de référence, partagées par les tests d'écran.
 *
 * Le tableau de bord est réclamé dès que la coquille s'affiche (`AGG-01`) : tout test qui
 * fait apparaître un écran authentifié doit savoir répondre à cet appel. Recopier
 * l'objet dans chaque fichier de test le ferait diverger du contrat au premier champ
 * ajouté — et un test qui ment sur la forme de la réponse ne prouve plus rien.
 */

import type { DashboardView } from '@/features/aggregates/api';
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
    weeks: [
      { week_start: '2026-06-08', minutes: 180, sessions: 3 },
      { week_start: '2026-06-15', minutes: 240, sessions: 4 },
      { week_start: '2026-06-22', minutes: 120, sessions: 2 },
      { week_start: '2026-06-29', minutes: 300, sessions: 5 },
      { week_start: '2026-07-06', minutes: 0, sessions: 0 },
      { week_start: '2026-07-13', minutes: 210, sessions: 4 },
      { week_start: '2026-07-20', minutes: 260, sessions: 4 },
      { week_start: '2026-07-27', minutes: 106, sessions: 2 },
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
};

const DEFAULT_VALUES = {
  target_weight_kg: 70,
  target_protein_g: 150,
  max_added_sugar_g: 30,
  target_hydration_ml: 2000,
  hydration_presets_ml: [250, 500, 750],
  heatmap_metric: 'activity',
};

export const SETTINGS: SettingsView = {
  values: { ...DEFAULT_VALUES, target_weight_kg: 68 },
  defaults: DEFAULT_VALUES,
  stored: ['target_weight_kg'],
  token: 'jeton-reglages',
};
