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
  /** Allure lue sur la capture, en min/km. **Pas déduite** de la distance et de la durée. */
  pace_min_km: number | null;
  cadence_spm: number | null;
  avg_hr: number | null;
  elevation_m: number | null;
  /** Kilocalories **actives**. Les totales sont un champ à part : elles diffèrent. */
  calories: number | null;
  total_calories: number | null;
  start_time: string | null;
  end_time: string | null;
  split_length_km: number | null;
  /** Les paliers relevés, reliquat compris et **déjà marqué** par le serveur. */
  splits: SplitDraft[];
  /**
   * Verdict de la relecture serveur (`IMP-03`).
   *
   * Faux, l'écran affiche les paliers **marqués douteux** — il ne les refuse pas :
   * l'utilisateur a la capture sous les yeux, nous non.
   */
  splits_trusted: boolean;
  /** Ce qui cloche, en français et prêt à afficher. Vide quand la relecture est sûre. */
  splits_doubts: string[];
  /** Champs que la capture ne portait pas — à afficher vides, jamais à zéro (`IMP-03`). */
  missing: string[];
  duplicate: DuplicateWarning | null;
}

/**
 * Un palier lu dans une capture, avant toute écriture.
 *
 * `partial` ne vient pas du modèle : le serveur le déduit des durées. Sur 8,14 km, la
 * neuvième ligne fait `00:44` — un reliquat, pas un kilomètre.
 */
export interface SplitDraft {
  index: number;
  duration_s: number;
  distance_km: number | null;
  pace_min_km: number | null;
  cadence_spm: number | null;
  avg_hr: number | null;
  elevation_m: number | null;
  partial: boolean;
}

export interface ImportPayload {
  kind: 'run' | 'workout';
  date: string;
  duration_min: string;
  type: string;
  distance_km?: string | null;
  /** L'une des deux suffit : le serveur calcule celle qui manque, l'allure l'emporte. */
  pace_min_km?: string | null;
  cadence_spm?: string | null;
  avg_hr?: string | null;
  elevation_m?: string | null;
  calories?: string | null;
  note?: string | null;
  total_calories?: number | null;
  start_time?: string | null;
  end_time?: string | null;
  split_length_km?: number | null;
  /**
   * Les paliers, **retransmis tels que l'analyse les a rendus**.
   *
   * Ils ne passent par aucun champ de formulaire : corriger neuf lignes au pouce n'est
   * pas un geste qu'on demande, et les retoucher une par une donnerait à l'écran les
   * moyens de fausser ce que le serveur vient de vérifier. On les valide en bloc ou on
   * les laisse.
   */
  splits?: SplitPayload[];
}

/** Un palier à écrire. Pas de `partial` : le serveur le décide, jamais le client. */
export interface SplitPayload {
  index: number;
  duration_s: number;
  pace_min_km?: number | null;
  cadence_spm?: number | null;
  avg_hr?: number | null;
  elevation_m?: number | null;
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
  /**
   * Lit une ou plusieurs captures d'une **même** séance.
   *
   * Le champ garde son nom au singulier : c'est celui du serveur, et une requête
   * multipart qui répète `screenshot` est exactement ce qu'un `<input multiple>` produit.
   * L'ordre est conservé — le résumé d'abord, les paliers ensuite.
   */
  analyze: (screenshots: readonly File[]) => {
    const form = new FormData();
    for (const shot of screenshots) form.append('screenshot', shot);
    return request<AppleDraft>('/api/import/apple/analyze', { method: 'POST', form });
  },

  confirm: (payload: ImportPayload) =>
    request<ImportResult>('/api/import/apple', { method: 'POST', body: payload }),
};
