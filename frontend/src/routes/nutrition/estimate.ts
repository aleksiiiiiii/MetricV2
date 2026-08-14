/**
 * Ce qu'une estimation dit, en une phrase.
 *
 * Dans son propre module parce que **deux surfaces l'emploient** : la feuille d'ajout et
 * la ligne d'un repas déjà enregistré, qui rattrape ses macros après coup. L'exporter
 * depuis l'une des deux marcherait, et casserait le rechargement à chaud d'un fichier qui
 * n'exporterait plus seulement des composants.
 *
 * **C'est du formatage, pas un calcul.** Les nombres arrivent tels que le serveur les a
 * relus et bornés ; aucun n'est dérivé ici (`docs/front.md` §7).
 */

import type { MealEstimate } from '@/features/nutrition/api';
import { integer, num } from '@/lib/format';

export function estimateSentence(estimate: MealEstimate): string {
  const parts: string[] = [];
  if (estimate.protein_g !== null) parts.push(`${num(estimate.protein_g, 0)} g de protéines`);
  if (estimate.added_sugar_g !== null)
    parts.push(`${num(estimate.added_sugar_g, 0)} g de sucres ajoutés`);
  if (estimate.calories !== null) parts.push(`${integer(estimate.calories)} kcal`);

  if (parts.length === 0) return '';
  if (parts.length === 1) return parts[0] ?? '';
  return `${parts.slice(0, -1).join(', ')} et ${parts[parts.length - 1] ?? ''}`;
}
