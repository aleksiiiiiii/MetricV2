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
  /** `ai` quand les macros viennent d'une estimation acceptée (`NUT-04`). */
  source: 'manual' | 'ai';
}

/**
 * Ce qu'un modèle **propose** pour une assiette (`NUT-04`).
 *
 * Tout est nullable, et ce n'est pas une facilité de typage : un champ que le modèle n'a
 * pas su estimer reste vide à l'écran. Le remplir d'un zéro le ferait passer pour une
 * mesure.
 */
export interface MealEstimate {
  comment: string | null;
  protein_g: number | null;
  added_sugar_g: number | null;
  calories: number | null;
  /** Faux quand le modèle annonce lui-même ne pas voir de nourriture. */
  readable: boolean;
  /** Vrai quand la réponse ne porte aucun chiffre. */
  empty: boolean;
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
  form.set('source', values.source);
  return form;
}

export const nutritionApi = {
  day: (limit?: number) =>
    request<NutritionView>('/api/nutrition', limit ? { query: { limit } } : {}),

  create: (values: MealFormValues) =>
    request<Meal>('/api/nutrition', { method: 'POST', form: multipart(values) }),

  /**
   * Propose des macros depuis une photo, une description, ou les deux. **N'écrit rien**
   * (`NUT-04`).
   *
   * Les deux paramètres sont facultatifs séparément, jamais ensemble : c'est le serveur
   * qui refuse une demande vide, et non ce client — une seconde règle ici divergerait de
   * la sienne au premier cas limite.
   */
  analyze: (photo: File | null, comment: string | null) => {
    const form = new FormData();
    if (photo) form.set('photo', photo);
    if (comment?.trim()) form.set('comment', comment.trim());
    return request<MealEstimate>('/api/nutrition/analyze', { method: 'POST', form });
  },

  /** Même proposition, pour un repas déjà enregistré avec sa photo. */
  analyzeMeal: (id: number) =>
    request<MealEstimate>(`/api/nutrition/${id}/analyze`, { method: 'POST' }),

  update: (
    id: number,
    token: string,
    payload: {
      meal_type: string;
      comment?: string | null;
      protein_g?: number | null;
      added_sugar_g?: number | null;
      calories?: number | null;
      /** À ne passer que si la provenance change réellement (`NUT-04`, `NUT-09`). */
      source?: 'manual' | 'ai';
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
