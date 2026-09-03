/**
 * Ce que les morceaux de l'écran Activité partagent.
 *
 * L'écran est découpé en sections — circuits, historique, feuilles — comme
 * `routes/settings/` l'a fait pour Réglages. Ces pièces sont les seules qui traversent le
 * découpage ; tout le reste appartient à une section et une seule.
 *
 * Les sections partagent aussi **un seul module CSS**, `../Activity.module.css`. Ce sont
 * les morceaux d'un même écran et non des composants indépendants : leur donner six
 * feuilles reviendrait à recopier six fois `.note`, `.empty` et `.error`. Ce qui devrait
 * servir ailleurs qu'ici n'a rien à faire dans un écran — il monte dans les primitives.
 */

import { useQueryClient } from '@tanstack/react-query';

import type { Circuit, CircuitExercisePayload, CircuitPayload } from '@/features/activity/api';
import { num } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';

export function useInvalidateActivity(): () => void {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.activity.all() });
    for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
  };
}

/**
 * Ce qu'une écriture de charge invalide — et ce qu'elle **n'invalide pas**.
 *
 * `keys.activity.all()` couvre les charges **et les circuits**, et le second est le point :
 * une charge change le 4ᵉ champ du lien de chaque séance qui emploie l'exercice, et un
 * lien périmé dans le cache est un bouton qui ouvre la mauvaise séance.
 *
 * `CROSS_CUTTING` est délibérément absent. Noter une charge n'écrit **aucune mesure**
 * (**C4**) : les séances tabata ne portent pas de tonnage, donc ni les agrégats ni
 * l'assiduité ne bougent. Si cette décision se rouvre un jour, cette ligne est la seconde
 * à changer, après `mark_done`.
 */
export function useInvalidateLoads(): () => void {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.activity.all() });
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

/**
 * Repli d'une chaîne pour la comparaison : minuscules, sans accents.
 *
 * Chercher « epaules » doit trouver « épaules », et « Développé » se tape rarement avec
 * son accent sur un clavier de téléphone quand on est entre deux séries.
 *
 * **Celui-ci ne décide rien.** Il filtre une liste affichée ; c'est `app/core/text.py`,
 * côté serveur, qui décide si deux noms désignent le même exercice. Les deux se
 * ressemblent et c'est voulu — mais l'un range des pixels, l'autre fusionne un historique,
 * et seul le second a besoin d'être la seule implémentation de sa règle.
 */
export function fold(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
}

/** La durée d'un circuit, avec le `~` que lui impose la présence de répétitions. */
export function circuitDuration(circuit: Circuit): string {
  const minutes = `${num(circuit.estimated_duration_min, 0)} min`;
  return circuit.exact ? minutes : `~${minutes}`;
}

/** Ce qu'un circuit dit de son contenu, sans avoir à l'ouvrir. */
export function circuitDetail(circuit: Circuit): string {
  return circuit.exercises
    .map((item) =>
      item.reps === null
        ? `${item.name} ${String(item.duration_s ?? 0)} s`
        : `${item.name} ${String(item.reps)}×`,
    )
    .join(' · ');
}

// ── Le brouillon d'un circuit ─────────────────────────
//
// Deux écrans le manipulent : le formulaire manuel de `Circuits.tsx` et la page de
// composition assistée. Il vit ici plutôt que recopié dans le second — deux modèles pour
// la même saisie divergeraient au premier champ ajouté, et c'est la charge utile du
// serveur qui en paierait la différence.

/** Le brouillon d'un exercice. Des chaînes : un champ passe par « 1 » avant « 15 ». */
export interface Draft {
  name: string;
  muscle_group: string;
  mode: 'time' | 'reps';
  value: string;
  rest: string;
  /** Ce qu'on veut lire sous le nom pendant l'effort — le 4ᵉ champ du lien Cadence. */
  note: string;
}

export const NEW_LINE: Draft = {
  name: '',
  muscle_group: 'abdos',
  mode: 'time',
  value: '30',
  rest: '10',
  note: '',
};

export const MODES = [
  { value: 'time' as const, label: 'Secondes' },
  { value: 'reps' as const, label: 'Répétitions' },
];

export function toDrafts(circuit: Circuit): Draft[] {
  return circuit.exercises.map((item) => ({
    name: item.name,
    muscle_group: item.muscle_group,
    mode: item.reps === null ? 'time' : 'reps',
    value: String(item.reps ?? item.duration_s ?? ''),
    rest: String(item.rest_s),
    // La note **saisie**, jamais celle du lien : `link_note` y joint la charge, et la
    // recopier dans le champ l'écrirait en dur au prochain enregistrement — elle cesserait
    // alors de suivre les changements de charge.
    note: item.note,
  }));
}

/** Un entier saisi, ou `null` quand le champ n'en porte pas un. Le serveur borne. */
export function whole(raw: string): number | null {
  const cleaned = raw.trim();
  if (!/^\d+$/.test(cleaned)) return null;
  return Number.parseInt(cleaned, 10);
}

/**
 * Le brouillon → la charge utile, ou `null` quand il manque de quoi écrire.
 *
 * `null` et non une charge partielle : c'est ce qui désactive « Enregistrer » plutôt que
 * d'envoyer une séance amputée que le serveur refuserait avec un message que personne
 * n'aurait vu venir.
 */
export function toPayload(
  name: string,
  rounds: string,
  rest: string,
  lines: Draft[],
): CircuitPayload | null {
  const exercises: CircuitExercisePayload[] = [];
  for (const line of lines) {
    const value = whole(line.value);
    if (line.name.trim() === '' || value === null) return null;
    exercises.push({
      name: line.name.trim(),
      muscle_group: line.muscle_group,
      ...(line.mode === 'time' ? { duration_s: value } : { reps: value }),
      rest_s: whole(line.rest) ?? 0,
      note: line.note.trim(),
    });
  }

  const roundCount = whole(rounds);
  if (name.trim() === '' || roundCount === null || exercises.length === 0) return null;
  return {
    name: name.trim(),
    rounds: roundCount,
    round_rest_s: whole(rest) ?? 0,
    exercises,
  };
}
