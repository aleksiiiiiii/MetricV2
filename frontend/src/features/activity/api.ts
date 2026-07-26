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
  note: string | null;
  source: string;
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
  week: WeekTotals;
  days: DayVolume[];
  weeks: WeekVolume[];
  muscles: MuscleVolume[];
  neglected: NeglectedGroup[];
  history: ActivityItem[];
  total: number;
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

/** Les champs souples restent des chaînes jusqu'au serveur. */
export interface RunPayload {
  date: string;
  distance_km: string;
  duration_min: string;
  avg_hr?: string | null;
  elevation_m?: string | null;
  note?: string | null;
}

export interface WorkoutPayload {
  date: string;
  type: string;
  duration_min: string;
  calories?: string | null;
  rpe?: number | null;
  note?: string | null;
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
  deleteRun: (id: number, token: string) =>
    request<undefined>(`/api/activity/runs/${id}`, { method: 'DELETE', headers: guard(token) }),

  createWorkout: (payload: WorkoutPayload) =>
    request<Workout>('/api/activity/workouts', { method: 'POST', body: payload }),
  readWorkout: (id: number) => request<Workout>(`/api/activity/workouts/${id}`),
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
  createExercise: (name: string, muscle_group: string) =>
    request<Exercise>('/api/activity/exercises', {
      method: 'POST',
      body: { name, muscle_group },
    }),
  logExercise: (workoutId: number, payload: ExerciseEntryPayload) =>
    request<ExerciseEntry>(`/api/activity/workouts/${workoutId}/exercises`, {
      method: 'POST',
      body: payload,
    }),
};
