/**
 * Planning sport (`PLAN-01` → `PLAN-06`).
 *
 * Aucun calcul ici, comme partout ailleurs : le mois arrive **découpé en semaines
 * complètes**, débordements compris, et le taux de respect arrive calculé. Recomposer la
 * grille côté client reviendrait à réécrire « la semaine commence le lundi », qui n'a
 * qu'une implémentation dans ce projet (`app/core/dates.py`).
 *
 * Deux appels ne se rejoignent jamais : `propose` rend des séances que personne n'a
 * validées, `adopt` écrit celles qu'on a gardées. Un écran qui enchaînerait les deux tout
 * seul romprait `PLAN-04`.
 */

import { request } from '@/lib/api';

export type PlanKind = 'course' | 'muscu' | 'autre';

export interface PlannedSession {
  id: number;
  token: string;
  session_id: string;
  date: string;
  time: string | null;
  kind: PlanKind;
  title: string;
  duration_min: number;
  note: string | null;
  /** `manual` ou `ai` — d'où vient la ligne, pas ce qu'elle vaut. */
  source: string;
  /**
   * L'adresse de séance Cadence **extraite de la note par le serveur**.
   *
   * Le lien vit dans la note et nulle part ailleurs — `plan.csv` ne gagne aucune colonne.
   * Mais reconnaître une adresse Cadence dans du texte libre est une règle du format, et
   * la tenir ici en ferait une seconde implémentation, qui divergerait de celle du serveur
   * au premier cas limite.
   */
  workout_url: string | null;
}

export interface DoneActivity {
  kind: 'run' | 'workout';
  id: number;
  label: string;
  duration_min: number;
}

export interface DayCell {
  date: string;
  in_month: boolean;
  planned: PlannedSession[];
  done: DoneActivity[];
}

export interface MonthView {
  month: string;
  start: string;
  end: string;
  days: DayCell[];
  /** Aujourd'hui **selon le serveur** : le fuseau de découpage est son réglage. */
  today: string;
}

export interface WeekAdherence {
  week: string;
  planned: number;
  done: number;
  honoured: number;
  /** `null` quand rien n'était prévu — jamais `0`. */
  rate: number | null;
}

export interface AdherenceView {
  weeks: WeekAdherence[];
  rate: number | null;
  planned: number;
  honoured: number;
}

export interface ProposedSession {
  date: string;
  time: string | null;
  kind: PlanKind;
  title: string;
  duration_min: number;
  note: string | null;
  reason: string | null;
}

export interface Proposal {
  sessions: ProposedSession[];
  start: string;
  end: string;
  basis: string[];
  dropped: string[];
}

export interface SubscriptionInfo {
  configured: boolean;
  url: string | null;
  message: string;
}

/** Ce qui part vers le serveur pour créer ou corriger une séance. */
export interface PlanFormValues {
  date: string;
  time: string | null;
  kind: PlanKind;
  title: string;
  duration_min: string;
  note?: string | null;
}

/** Garde anti-conflit : le jeton lu est celui qu'on renvoie (`STO-05`). */
function ifMatch(token: string): Record<string, string> {
  return { 'If-Match': token };
}

export const planningApi = {
  month: (month: string) => request<MonthView>('/api/planning/month', { query: { month } }),

  adherence: (weeks = 8) => request<AdherenceView>('/api/planning/adherence', { query: { weeks } }),

  create: (values: PlanFormValues) =>
    request<PlannedSession>('/api/planning/sessions', { method: 'POST', body: values }),

  update: (id: number, token: string, values: PlanFormValues) =>
    request<PlannedSession>(`/api/planning/sessions/${String(id)}`, {
      method: 'PATCH',
      body: values,
      headers: ifMatch(token),
    }),

  remove: (id: number, token: string) =>
    request<undefined>(`/api/planning/sessions/${String(id)}`, {
      method: 'DELETE',
      headers: ifMatch(token),
    }),

  propose: (body: { weeks: 1 | 2; constraints: string; objective: string }) =>
    request<Proposal>('/api/planning/proposal', { method: 'POST', body }),

  /** Écrit **ce qui reste** après retrait individuel, en une fois (`PLAN-04`). */
  adopt: (sessions: PlanFormValues[]) =>
    request<{ created: PlannedSession[] }>('/api/planning/proposal/adopt', {
      method: 'POST',
      body: { sessions },
    }),

  subscription: () => request<SubscriptionInfo>('/api/planning/subscription'),
};
