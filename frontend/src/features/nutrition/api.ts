/**
 * Accès à la nutrition (`NUT-01` → `NUT-10`).
 *
 * La création passe par un formulaire multipart : un fichier ne se transporte pas en
 * JSON. Le client n'envoie pas de type de contenu de confiance — c'est la signature du
 * fichier qui décide côté serveur.
 */

import { request } from '@/lib/api';

export interface Meal {
  id: number;
  token: string;
  datetime: string;
  meal_type: string;
  comment: string | null;
  /** Chemin relatif, à passer à `photoPath()`. */
  photo: string | null;
  protein_g: number | null;
  added_sugar_g: number | null;
  calories: number | null;
  source: string;
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

export interface Favorite {
  id: number;
  token: string;
  favorite_id: string;
  name: string;
  protein_g: number | null;
  added_sugar_g: number | null;
  calories: number | null;
}

export interface NutritionView {
  date: string;
  totals: DayTotals;
  meals: Meal[];
  favorites: Favorite[];
  suggested_type: string;
  types: string[];
}

export interface MealFormValues {
  meal_type: string;
  comment: string;
  protein_g: string;
  added_sugar_g: string;
  calories: string;
  photo: File | null;
}

export function photoPath(relative: string): string {
  return `/api/nutrition/photos/${relative}`;
}

function multipart(values: MealFormValues): FormData {
  const form = new FormData();
  form.set('meal_type', values.meal_type);
  if (values.comment.trim()) form.set('comment', values.comment.trim());
  for (const field of ['protein_g', 'added_sugar_g', 'calories'] as const) {
    const raw = values[field].replace(',', '.').trim();
    if (raw) form.set(field, raw);
  }
  if (values.photo) form.set('photo', values.photo);
  return form;
}

export const nutritionApi = {
  day: (limit?: number) =>
    request<NutritionView>('/api/nutrition', limit ? { query: { limit } } : {}),

  create: (values: MealFormValues) =>
    request<Meal>('/api/nutrition', { method: 'POST', form: multipart(values) }),

  update: (
    id: number,
    token: string,
    payload: {
      meal_type: string;
      comment?: string | null;
      protein_g?: number | null;
      added_sugar_g?: number | null;
      calories?: number | null;
    },
  ) =>
    request<Meal>(`/api/nutrition/${id}`, {
      method: 'PATCH',
      body: payload,
      headers: { 'If-Match': token },
    }),

  remove: (id: number, token: string) =>
    request<undefined>(`/api/nutrition/${id}`, {
      method: 'DELETE',
      headers: { 'If-Match': token },
    }),

  addFavorite: (payload: {
    name: string;
    protein_g?: number | null;
    added_sugar_g?: number | null;
    calories?: number | null;
  }) => request<Favorite>('/api/nutrition/favorites', { method: 'POST', body: payload }),

  replayFavorite: (favoriteId: string) =>
    request<Meal>(`/api/nutrition/favorites/${favoriteId}/replay`, { method: 'POST' }),

  removeFavorite: (id: number, token: string) =>
    request<undefined>(`/api/nutrition/favorites/${id}`, {
      method: 'DELETE',
      headers: { 'If-Match': token },
    }),
};
