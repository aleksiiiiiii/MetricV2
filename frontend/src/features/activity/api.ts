/**
 * Accès au domaine Activité (`ACT-01` → `ACT-18`).
 *
 * Les durées et distances partent en **texte** : le serveur normalise `44:12`, `8,40`,
 * `1h30` (`ACT-01`). Le client ne convertit rien — un second analyseur finirait par
 * diverger du premier.
 */

import { request } from '@/lib/api';

export interface Run {
  id: number;
  token: string;
  date: string;
  distance_km: number;
  duration_min: number;
  pace_min_km: number | null;
  speed_kmh: number | null;
  avg_hr: number | null;
  elevation_m: number | null;
  /** Pas par minute. Rien ne la déduit : elle est saisie ou lue sur une capture. */
  cadence_spm: number | null;
  note: string | null;
  source: string;
  /** Identifiant stable, celui auquel les paliers se rattachent. Vide sur une saisie. */
  run_id: string;
  /** Kilocalories **totales**, métabolisme de base compris — jamais « calories » tout court. */
  total_calories: number | null;
  /** `19:40:00`, telle que le serveur la rend. Situe la séance, ne la date pas. */
  start_time: string | null;
  end_time: string | null;
  split_length_km: number | null;
  /** Nombre de paliers relevés. Zéro sur une course saisie au clavier, pas une erreur. */
  splits: number;
}

/**
 * Un palier d'une course (`ACT-19`).
 *
 * `partial` est le champ qui porte tout : sur 8,14 km, la neuvième ligne fait `00:44` et
 * n'est **pas** un kilomètre. Son allure est une extrapolation de l'application, pas une
 * mesure — l'écran la grise, et n'en fait aucune moyenne.
 */
export interface RunSplit {
  index: number;
  duration_s: number;
  /** La longueur réelle — 1 pour un plein, le reliquat pour un partiel. */
  distance_km: number | null;
  pace_min_km: number | null;
  cadence_spm: number | null;
  avg_hr: number | null;
  elevation_m: number | null;
  partial: boolean;
  /** Part de la barre de cadence, servie par le serveur : aucun `Math.max` à l'écran. */
  cadence_ratio: number | null;
}

export interface RunSplits {
  splits: RunSplit[];
  full_count: number;
  partial_count: number;
  /**
   * Secondes par kilomètre, seconde moitié moins première.
   *
   * **Négatif veut dire plus rapide**, ce qui se lit à l'envers du signe : l'écran le dit
   * en toutes lettres plutôt que de montrer un `-4,2` que rien n'explique.
   */
  drift_s_per_km: number | null;
  first_half_pace_min_km: number | null;
  second_half_pace_min_km: number | null;
  fastest_index: number | null;
  slowest_index: number | null;
  /** Bornes de l'axe d'allure, **le plus lent d'abord** : l'axe arrive déjà retourné. */
  pace_domain_min_km: [number, number] | null;
  cadence_max_spm: number | null;
}

/** Une course et ses paliers. `run` à `null` = aucune course, ce qui n'est pas une panne. */
export interface RunDetail {
  run: Run | null;
  splits: RunSplits;
}

export interface ExerciseEntry {
  id: number;
  token: string;
  workout_id: string;
  date: string;
  exercise_id: string;
  exercise_name: string;
  muscle_group: string;
  weight_kg: number;
  sets: number;
  reps: number;
  note: string | null;
  volume_kg: number;
  one_rep_max_kg: number | null;
}

export interface Workout {
  id: number;
  token: string;
  workout_id: string;
  date: string;
  type: string;
  duration_min: number;
  calories: number | null;
  rpe: number | null;
  note: string | null;
  source: string;
  exercises: ExerciseEntry[];
  volume_kg: number;
}

export interface Exercise {
  id: number;
  token: string;
  exercise_id: string;
  name: string;
  muscle_group: string;
  /** Les autres écritures reconnues pour cet exercice (`C07`). */
  aliases: string[];
  /** Séries déjà consignées : ce qu'un retrait conserve, ce qu'une correction répercute. */
  entries: number;
  last_weight_kg: number | null;
  last_reps: number | null;
  last_sets: number | null;
  last_date: string | null;
}

export interface ActivityItem {
  kind: 'run' | 'workout';
  id: number;
  token: string;
  date: string;
  label: string;
  duration_min: number;
  distance_km: number | null;
  pace_min_km: number | null;
  rpe: number | null;
  /** Séries rattachées à une séance : ce que sa suppression emporterait (`ACT-04`). */
  entries: number;
  source: string;
}

export interface DayVolume {
  date: string;
  weekday: number;
  minutes: number;
  rest: boolean;
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

export interface MuscleVolume {
  muscle_group: string;
  volume_kg: number;
  sets: number;
}

export interface NeglectedGroup {
  muscle_group: string;
  days_since: number | null;
  last_date: string | null;
}

export interface ActivityOverview {
  /** Le jour, dans le fuseau du serveur. L'écran ne consulte pas l'horloge du téléphone. */
  today: string;
  week: WeekTotals;
  days: DayVolume[];
  weeks: WeekVolume[];
  muscles: MuscleVolume[];
  neglected: NeglectedGroup[];
  history: ActivityItem[];
  total: number;
}

/**
 * Un exercice lu dans une note, **avant** toute écriture (`C07`).
 *
 * `status` dit ce que la ligne coûterait si on la validait, et l'écran les distingue
 * parce qu'elles ne coûtent pas la même chose :
 *
 * * `known` — l'exercice existe, rien à écrire au catalogue ;
 * * `alias` — même mouvement sous un autre nom : la graphie de la note s'ajoute en alias,
 *   et le nom du catalogue s'impose ;
 * * `new` — absent du catalogue, à créer avec le groupe déduit.
 */
export interface NoteLine {
  name: string;
  muscle_group: string;
  sets: number | null;
  reps: number | null;
  /** `0` = poids du corps, valeur légitime. `null` = absente ou dans une autre unité. */
  weight_kg: number | null;
  /** Pourquoi la charge est vide, quand il y a une raison — « charge en lbs ». */
  note: string | null;
  status: 'known' | 'alias' | 'new';
  exercise_id: string | null;
  /** Sur un `alias` : la graphie de la note, à ajouter à l'exercice du catalogue. */
  alias_of: string | null;
}

export interface NoteDraft {
  lines: NoteLine[];
  source_text: string;
}

export interface ExerciseProgress {
  exercise_id: string;
  name: string;
  muscle_group: string;
  last_weight_kg: number | null;
  last_date: string | null;
  delta_kg: number | null;
  max_series: number[];
  dates: string[];
  best_weight_kg: number | null;
  best_one_rep_max_kg: number | null;
}

/**
 * Les champs souples restent des chaînes jusqu'au serveur.
 *
 * **Distance et allure ne s'envoient pas ensemble sans conséquence.** Elles sont deux
 * lectures du même trajet, liées par la durée, et le serveur en calcule toujours une
 * depuis l'autre — jamais ce client. Quand les deux partent, l'allure l'emporte et la
 * distance est recalculée : c'est la règle du serveur, et l'écran envoie donc **celle que
 * l'utilisateur vient de corriger**.
 *
 * L'une des deux au moins est requise ; une durée seule est refusée.
 */
export interface RunPayload {
  date: string;
  duration_min: string;
  distance_km?: string | null;
  /** `5:16` ou `5,27` — même écriture qu'une durée. */
  pace_min_km?: string | null;
  avg_hr?: string | null;
  elevation_m?: string | null;
  cadence_spm?: string | null;
  note?: string | null;
}

export interface WorkoutPayload {
  date: string;
  type: string;
  duration_min: string;
  calories?: string | null;
  rpe?: number | null;
  note?: string | null;
  /**
   * Les exercices de la séance, écrits **avec elle**.
   *
   * Facultatif : le journal consigne toujours série par série, au fil de la séance.
   * C'est l'assistant de saisie qui s'en sert — il construit la séance entière avant de
   * rien écrire, pour qu'un abandon ne laisse pas une séance vide dans l'historique.
   */
  exercises?: ExerciseEntryPayload[];
}

export interface ExerciseEntryPayload {
  exercise_id: string;
  weight_kg: string;
  sets: number;
  reps: number;
  note?: string | null;
}

function guard(token: string): Record<string, string> {
  return { 'If-Match': token };
}

export const activityApi = {
  overview: () => request<ActivityOverview>('/api/activity'),
  progress: () => request<ExerciseProgress[]>('/api/activity/progress'),
  types: () => request<string[]>('/api/activity/types'),
  muscleGroups: () => request<string[]>('/api/activity/muscle-groups'),

  createRun: (payload: RunPayload) =>
    request<Run>('/api/activity/runs', { method: 'POST', body: payload }),
  readRun: (id: number) => request<Run>(`/api/activity/runs/${id}`),
  latestRun: () => request<RunDetail>('/api/activity/runs/latest'),
  runSplits: (id: number) => request<RunDetail>(`/api/activity/runs/${id}/splits`),
  updateRun: (id: number, token: string, payload: RunPayload) =>
    request<Run>(`/api/activity/runs/${id}`, {
      method: 'PATCH',
      headers: guard(token),
      body: payload,
    }),
  deleteRun: (id: number, token: string) =>
    request<undefined>(`/api/activity/runs/${id}`, { method: 'DELETE', headers: guard(token) }),

  createWorkout: (payload: WorkoutPayload) =>
    request<Workout>('/api/activity/workouts', { method: 'POST', body: payload }),
  readWorkout: (id: number) => request<Workout>(`/api/activity/workouts/${id}`),
  updateWorkout: (id: number, token: string, payload: WorkoutPayload) =>
    request<Workout>(`/api/activity/workouts/${id}`, {
      method: 'PATCH',
      headers: guard(token),
      body: payload,
    }),
  deleteWorkout: (id: number, token: string) =>
    request<undefined>(`/api/activity/workouts/${id}`, {
      method: 'DELETE',
      headers: guard(token),
    }),
  duplicateWorkout: (id: number, date: string) =>
    request<Workout>(`/api/activity/workouts/${id}/duplicate`, {
      method: 'POST',
      body: { date },
    }),

  exercises: () => request<Exercise[]>('/api/activity/exercises'),

  /**
   * Lit une séance écrite en clair, ou photographiée. **N'écrit rien** (`C07`).
   *
   * Une photo passe par le même modèle que le texte : l'OCR n'est pas une brique à part.
   */
  readNotes: (text: string, photo: File | null) => {
    const form = new FormData();
    if (text.trim()) form.set('text', text.trim());
    if (photo) form.set('photo', photo);
    return request<NoteDraft>('/api/activity/notes/read', { method: 'POST', form });
  },

  /** Fait reconnaître une autre écriture d'un exercice. Le nom du catalogue ne bouge pas. */
  addAlias: (exerciseId: string, alias: string) =>
    request<Exercise>(`/api/activity/exercises/${exerciseId}/aliases`, {
      method: 'POST',
      body: { alias },
    }),
  createExercise: (name: string, muscle_group: string, aliases?: string[]) =>
    request<Exercise>('/api/activity/exercises', {
      method: 'POST',
      body: aliases === undefined ? { name, muscle_group } : { name, muscle_group, aliases },
    }),
  /** Corrige nom et groupe. Le serveur répercute la correction sur les séries (`ACT-06`). */
  updateExercise: (id: number, token: string, name: string, muscle_group: string) =>
    request<Exercise>(`/api/activity/exercises/${id}`, {
      method: 'PATCH',
      headers: guard(token),
      body: { name, muscle_group },
    }),
  deleteExercise: (id: number, token: string) =>
    request<undefined>(`/api/activity/exercises/${id}`, {
      method: 'DELETE',
      headers: guard(token),
    }),

  logExercise: (workoutId: number, payload: ExerciseEntryPayload) =>
    request<ExerciseEntry>(`/api/activity/workouts/${workoutId}/exercises`, {
      method: 'POST',
      body: payload,
    }),
  /** La séance et le jour d'une série ne changent pas : le serveur les préserve. */
  updateEntry: (id: number, token: string, payload: ExerciseEntryPayload) =>
    request<ExerciseEntry>(`/api/activity/exercise-log/${id}`, {
      method: 'PATCH',
      headers: guard(token),
      body: payload,
    }),
  deleteEntry: (id: number, token: string) =>
    request<undefined>(`/api/activity/exercise-log/${id}`, {
      method: 'DELETE',
      headers: guard(token),
    }),
};
