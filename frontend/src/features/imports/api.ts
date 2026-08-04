/**
 * Import d'une capture Apple (`IMP-01` → `IMP-06`).
 *
 * Deux appels, et il n'y a pas de raccourci entre eux : `analyze` rend un brouillon que
 * personne n'a encore validé, `confirm` écrit ce que l'utilisateur a validé. Un écran qui
 * enchaînerait les deux tout seul romprait `IMP-01`.
 *
 * Les champs souples partent en **texte**, comme partout ailleurs : le serveur détient la
 * seule grammaire des durées et des distances (`ACT-01`, `IMP-03`).
 */

import { request } from '@/lib/api';

export interface DuplicateWarning {
  kind: 'run' | 'workout';
  id: number;
  date: string;
  label: string;
  duration_min: number;
}

export interface AppleDraft {
  kind: 'run' | 'workout';
  date: string | null;
  workout_type: string | null;
  distance_km: number | null;
  duration_min: number | null;
  avg_hr: number | null;
  elevation_m: number | null;
  calories: number | null;
  /** Champs que la capture ne portait pas — à afficher vides, jamais à zéro (`IMP-03`). */
  missing: string[];
  duplicate: DuplicateWarning | null;
}

export interface ImportPayload {
  kind: 'run' | 'workout';
  date: string;
  duration_min: string;
  type: string;
  distance_km?: string | null;
  avg_hr?: string | null;
  elevation_m?: string | null;
  calories?: string | null;
  note?: string | null;
}

export interface ImportResult {
  kind: 'run' | 'workout';
  id: number;
  date: string;
  label: string;
  duration_min: number;
  distance_km: number | null;
  source: string;
}

export const importsApi = {
  analyze: (screenshot: File) => {
    const form = new FormData();
    form.set('screenshot', screenshot);
    return request<AppleDraft>('/api/import/apple/analyze', { method: 'POST', form });
  },

  confirm: (payload: ImportPayload) =>
    request<ImportResult>('/api/import/apple', { method: 'POST', body: payload }),
};
