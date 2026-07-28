/**
 * Accès aux réglages (`L08-01`, `L08-02`).
 *
 * **Aucune valeur de repli n'est écrite ici.** Le serveur envoie les défauts avec les
 * valeurs effectives ; les recopier dans ce fichier créerait une seconde source de
 * vérité, et le jour où l'objectif de protéines changerait côté backend, l'écran
 * afficherait encore l'ancien pour un utilisateur qui n'a jamais rien réglé.
 */

import { request } from '@/lib/api';

export interface SettingsValues {
  target_weight_kg: number;
  target_protein_g: number;
  max_added_sugar_g: number;
  target_hydration_ml: number;
  hydration_presets_ml: number[];
  heatmap_metric: string;
}

export interface SettingsView {
  values: SettingsValues;
  /** Ce que vaut chaque réglage non renseigné, servi par le serveur. */
  defaults: SettingsValues;
  /** Clés effectivement présentes dans le fichier : le reste est un repli, pas un choix. */
  stored: (keyof SettingsValues)[];
  /** À renvoyer en « If-Match » pour modifier (`STO-05`). */
  token: string;
}

/** Modification partielle : un champ omis reste à sa valeur. */
export type SettingsPayload = Partial<SettingsValues>;

export const settingsApi = {
  read: () => request<SettingsView>('/api/settings'),

  update: (payload: SettingsPayload, token: string) =>
    request<SettingsView>('/api/settings', {
      method: 'PATCH',
      body: payload,
      headers: { 'If-Match': token },
    }),
};
