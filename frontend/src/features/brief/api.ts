/**
 * La lecture du jour.
 *
 * Aucun calcul ici, comme partout ailleurs : le message est écrit par le serveur, le
 * condensé sur lequel il s'appuie est rangé avec lui, et le client ne fait que les
 * afficher.
 *
 * **Trois lectures par jour** — matin, midi, soir. L'écran ne demande jamais laquelle :
 * le serveur rend celle du moment, parce que lui seul tient l'heure.
 *
 * **Trois appels qui ne se confondent pas.** `read` lit et n'écrit rien — c'est lui que
 * l'écran d'accueil appelle. `write` demande la lecture au modèle et la range ; il n'est
 * déclenché que par un appui, en repli de l'ordonnanceur du serveur. `openThread` ouvre le
 * fil dans lequel répondre, et il le fait **au premier appui seulement**.
 */

import { request } from '@/lib/api';

/** Les trois moments de la journée. Décidés par le serveur, jamais déduits ici. */
export type BriefSlot = 'matin' | 'midi' | 'soir';

export interface BriefView {
  day: string;
  /**
   * Le moment commenté.
   *
   * **L'écran ne le calcule pas.** Il n'a ni l'horloge ni le fuseau du serveur, et deux
   * idées de « il est midi » finiraient par diverger — c'est la même règle que « le jour
   * vient du serveur ». Il reçoit le créneau et l'affiche.
   */
  slot: BriefSlot;
  /**
   * `absent` n'est pas « il n'y a rien à dire » : c'est « ce n'est pas encore écrit ».
   *
   * Un message vide dirait les deux à la fois, et l'écran ne saurait pas s'il doit offrir
   * de la demander ou se taire. Un échec, lui, n'est pas un état : c'est une erreur, avec
   * son code et son message français (`API-07`).
   */
  state: 'ready' | 'absent';
  /** Vide tant que `state` vaut `absent`. Jamais une phrase de remplacement. */
  message: string;
  /** Le condensé factuel réellement envoyé au modèle, ligne par ligne (`IA-09`). */
  basis: string[];
  /** Le fil ouvert pour répondre, `null` tant que personne n'a répondu. */
  thread_id: string | null;
}

export interface BriefThread {
  thread_id: string;
}

export const briefApi = {
  read: () => request<BriefView>('/api/brief'),

  /** Demande la lecture du jour. Rappelée, elle remplace celle du jour. */
  write: () => request<BriefView>('/api/brief', { method: 'POST' }),

  /** Le fil dans lequel répondre — créé au premier appui, rendu tel quel ensuite. */
  openThread: () => request<BriefThread>('/api/brief/thread', { method: 'POST' }),
};
