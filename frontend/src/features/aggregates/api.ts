/**
 * Accès aux agrégats du tableau de bord (`AGG-01` → `AGG-04`).
 *
 * Les types reflètent exactement les schémas du serveur, et **aucun calcul n'a lieu
 * ici** : moyennes, variations, séries et répartitions arrivent déjà faites. Le client
 * formate, il ne dérive pas (`HEAT-30`).
 */

import { request } from '@/lib/api';

// ── Blocs repris des domaines ─────────────────────────

export interface WeightStats {
  latest_kg: number | null;
  latest_date: string | null;
  change_kg: number | null;
  to_target_kg: number | null;
  target_kg: number;
  min_kg: number | null;
  max_kg: number | null;
  amplitude_kg: number | null;
  count: number;
}

export interface WeekTotals {
  week_start: string;
  minutes: number;
  sessions: number;
  distance_km: number;
  pace_min_km: number | null;
}

export interface WeekVolume {
  week_start: string;
  minutes: number;
  sessions: number;
}

export interface TrainingSplit {
  kind: string;
  label: string;
  sessions: number;
  minutes: number;
  ratio: number;
}

export interface TrainingTotals {
  sessions_total: number;
  minutes_total: number;
  week: WeekTotals;
  weeks: WeekVolume[];
  split: TrainingSplit[];
}

export interface DayTotals {
  protein_g: number;
  protein_target_g: number;
  protein_ratio: number;
  added_sugar_g: number;
  added_sugar_max_g: number;
  over_sugar: boolean;
  calories: number;
  calories_known: number;
  meals: number;
}

export interface HydrationStats {
  today_ml: number;
  target_ml: number;
  ratio: number;
  average_7d_ml: number | null;
  average_30d_ml: number | null;
  days_reached: number;
  days_counted: number;
}

export interface DayRatio {
  taken: number;
  planned: number;
  ratio: number;
  complete: boolean;
}

// ── Série d'assiduité (`AGG-03`) ──────────────────────

export interface StreakDay {
  date: string;
  active: boolean;
  sources: string[];
}

export interface Streak {
  current: number;
  longest: number;
  active_days: number;
  last_seven: StreakDay[];
}

// ── Séries temporelles (`AGG-04`) ─────────────────────

/** Les trois plages du contrat. Le serveur refuse tout le reste. */
export type RangeKey = '1m' | '3m' | 'all';

export interface MetricSubject {
  key: string;
  label: string;
}

export interface MetricDescriptor {
  key: string;
  label: string;
  unit: string;
  granularity: 'day' | 'week';
  subjects: MetricSubject[];
}

export interface SeriesPoint {
  date: string;
  value: number;
}

export interface SeriesStats {
  latest: number | null;
  latest_date: string | null;
  change: number | null;
  average: number | null;
  minimum: number | null;
  maximum: number | null;
  count: number;
}

export interface SeriesView {
  metric: string;
  label: string;
  unit: string;
  granularity: 'day' | 'week';
  subject: string | null;
  range: RangeKey;
  points: SeriesPoint[];
  stats: SeriesStats;
}

// ── Tableau de bord (`AGG-01`) ────────────────────────

export interface DashboardView {
  date: string;
  weight: WeightStats;
  training: TrainingTotals;
  nutrition: DayTotals;
  hydration: HydrationStats;
  supplements: DayRatio;
  streak: Streak;
  /** Incluse : la première peinture de l'écran, graphique compris, tient en un appel. */
  series: SeriesView;
  highlight: string;
}

export const aggregatesApi = {
  dashboard: (metric?: string, range?: RangeKey) =>
    request<DashboardView>('/api/aggregates/dashboard', {
      query: { ...(metric ? { metric } : {}), ...(range ? { range } : {}) },
    }),

  metrics: () => request<MetricDescriptor[]>('/api/aggregates/metrics'),

  series: (metric: string, range: RangeKey, subject?: string) =>
    request<SeriesView>('/api/aggregates/series', {
      query: { metric, range, ...(subject ? { subject } : {}) },
    }),
};
