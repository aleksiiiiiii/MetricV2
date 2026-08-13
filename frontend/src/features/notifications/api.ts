/**
 * Accès aux notifications push et aux rappels (`NOT-01`, `NOT-03`).
 *
 * **Des types et des appels, rien d'autre.** Aucune valeur de repli, aucun horaire par
 * défaut : le serveur sert l'état complet, y compris ce qui manque et la phrase à
 * afficher. Écrire ici « 20:00 par défaut » recréerait une seconde source de vérité, et
 * poserait surtout un rappel que personne n'a demandé.
 */

import { request } from '@/lib/api';

/** Les quatre types de rappel. Mêmes noms que les clés `reminders_*` du serveur. */
export type ReminderKind = 'supplements' | 'hydration' | 'meals' | 'workout';

export interface PushStatus {
  /** Une paire de clés VAPID est configurée côté serveur. */
  configured: boolean;
  /** Clé publique pour `pushManager.subscribe`. `null` tant qu'il n'y en a pas. */
  public_key: string | null;
  /** Ce qu'il y a à dire à l'écran, en français, servi par le serveur. */
  message: string;
}

export interface SubscribedDevice {
  id: string;
  created: string | null;
  /** Nom court — « iPhone », « Mac », « Appareil ». **Dérivé par le serveur** du
   *  `user-agent`, qui n'est pas publié : tronqué dans une liste, il ne nomme rien. */
  label: string;
  /** Les derniers caractères de l'adresse d'abonnement — l'adresse entière est un secret. */
  hint: string;
}

/** Un créneau `HH:MM`, ou `null` quand le rappel est éteint. */
export type Reminders = Record<ReminderKind, string | null>;

export interface NotificationsView {
  push: PushStatus;
  devices: SubscribedDevice[];
  reminders: Reminders;
  /** À renvoyer en « If-Match » : les créneaux vivent dans `settings.csv` (`STO-05`). */
  token: string;
}

/**
 * Modification des créneaux.
 *
 * `undefined` — la clé absente — laisse le créneau à sa valeur ; `null` l'éteint. La
 * distinction est celle du serveur, et elle compte : sans elle, on ne saurait pas
 * exprimer « arrête ce rappel ».
 */
export type RemindersPayload = Partial<Record<ReminderKind, string | null>>;

export interface SubscriptionPayload {
  endpoint: string;
  p256dh: string;
  auth: string;
  user_agent: string;
}

export const notificationsApi = {
  read: () => request<NotificationsView>('/api/notifications'),

  subscribe: (payload: SubscriptionPayload) =>
    request<undefined>('/api/notifications/subscribe', { method: 'POST', body: payload }),

  unsubscribe: (endpoint: string) =>
    request<undefined>('/api/notifications/subscribe', { method: 'DELETE', query: { endpoint } }),

  // `PATCH` et non `PUT` : la modification est **partielle** — une clé absente laisse le
  // créneau à sa valeur. C'est aussi ce que fait déjà `/api/settings`, qui édite le même
  // fichier ; deux verbes pour la même sémantique se seraient contredits.
  updateReminders: (payload: RemindersPayload, token: string) =>
    request<NotificationsView>('/api/notifications/reminders', {
      method: 'PATCH',
      body: payload,
      headers: { 'If-Match': token },
    }),

  /** Envoie une notification d'essai à tous les appareils abonnés. */
  test: () => request<undefined>('/api/notifications/test', { method: 'POST' }),
};
