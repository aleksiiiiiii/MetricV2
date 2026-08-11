/**
 * Ce que les morceaux de l'écran Activité partagent.
 *
 * L'écran est découpé en sections — journal, historique, feuilles — comme
 * `routes/settings/` l'a fait pour Réglages. Ces quatre pièces sont les seules qui
 * traversent le découpage ; tout le reste appartient à une section et une seule.
 *
 * Les sections partagent aussi **un seul module CSS**, `../Activity.module.css`. Ce sont
 * les morceaux d'un même écran et non des composants indépendants : leur donner six
 * feuilles reviendrait à recopier six fois `.note`, `.empty` et `.error`. Ce qui devrait
 * servir ailleurs qu'ici n'a rien à faire dans un écran — il monte dans les primitives.
 */

import { useQueryClient } from '@tanstack/react-query';

import type { Workout } from '@/features/activity/api';
import { CROSS_CUTTING, keys } from '@/lib/query';

/** Ce qu'il faut d'une séance pour la proposer au choix, sans avoir à la relire. */
export interface Session {
  id: number;
  date: string;
  label: string;
}

export function toSession(workout: Workout): Session {
  return { id: workout.id, date: workout.date, label: workout.type };
}

export function useInvalidateActivity(): () => void {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.activity.all() });
    for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
  };
}

/**
 * Écrit un nombre pour le champ *et* pour le serveur.
 *
 * Volontairement sans séparateur de milliers, contrairement à `num` : ce texte part dans
 * la charge utile, et `1 000` y serait une valeur que le serveur devrait deviner. La
 * virgule, elle, fait partie du contrat `ACT-01`.
 */
export function kgText(value: number): string {
  return String(Math.round(value * 100) / 100).replace('.', ',');
}
