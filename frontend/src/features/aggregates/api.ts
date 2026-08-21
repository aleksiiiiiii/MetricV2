/**
 * Accès aux agrégats du tableau de bord (`AGG-01` → `AGG-04`).
 *
 * Les types reflètent exactement les schémas du serveur, et **aucun calcul n'a lieu
 * ici** : moyennes, variations, séries et répartitions arrivent déjà faites. Le client
 * formate, il ne dérive pas (`HEAT-30`).
 */

import type { ActiveGoal } from '@/features/goals/api';
import type { PlannedSession } from '@/features/planning/api';
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
  /**
   * Part de la semaine la plus chargée de la fenêtre, entre 0 et 1.
   *
   * **Servie.** L'écran la dérivait d'un `Math.max(...weeks.map(…))` : un maximum sur une
   * série est une dérivation, et le client n'en fait aucune (`HEAT-30`).
   */
  ratio: number;
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

// ── La journée à finir ────────────────────────────────

export interface DayTask {
  /** `hydration`, `protein` ou `supplements` — une table de correspondance, pas un calcul. */
  key: string;
  label: string;
  /**
   * Ce qui est noté aujourd'hui. **`null` quand rien ne l'est**, et ce n'est pas zéro :
   * un `0` affiché à côté d'une cible se lit comme une mesure.
   */
  done: number | null;
  target: number;
  unit: string;
  ratio: number;
  complete: boolean;
  /** Ce qu'il reste, écrit en français par le serveur : « encore 1,1 L », « fait ». */
  remaining: string;
}

export interface DayPlan {
  date: string;
  /** Ordonnées **par le serveur** : ce qui reste d'abord, ce qui est bouclé ensuite. */
  tasks: DayTask[];
  done: number;
  total: number;
  /**
   * Vrai dès qu'une donnée a été relevée aujourd'hui, **toutes sources confondues**.
   *
   * L'écran le recollait à partir de quatre champs — repas, eau, prises, date de pesée —
   * et se trompait dès qu'une course ou des mensurations faisaient la journée. La
   * définition est celle de `AGG-03`, et il n'y en a qu'une.
   */
  logged: boolean;
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
  /** Ce qu'il reste à faire aujourd'hui. */
  day: DayPlan;
  /**
   * L'objectif en cours, progression comprise. `null` quand il n'y en a pas — l'écran
   * retombe alors sur la cible de poids, puis sur son état vide.
   */
  goal: ActiveGoal | null;
  /** La prochaine séance prévue. `null` quand rien n'est prévu sur la fenêtre regardée. */
  next_session: PlannedSession | null;
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
