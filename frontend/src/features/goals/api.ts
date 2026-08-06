/**
 * Objectifs et bilan hebdomadaire (`GOAL-01` → `GOAL-06`, `IA-08`).
 *
 * Aucun calcul ici, comme partout ailleurs. L'avancement, le libellé chiffré, la fenêtre
 * d'observation et le nombre de jours restants arrivent **calculés** : recalculer un ratio
 * côté client donnerait deux pourcentages pour le même objectif dès le premier cas limite,
 * et c'est l'utilisateur qui arbitrerait entre les deux (`HEAT-30`).
 *
 * Deux appels ne se rejoignent jamais : `propose` rend un objectif que personne n'a validé,
 * `adopt` écrit celui qu'on a gardé. Un écran qui enchaînerait les deux tout seul romprait
 * `GOAL-03`. Il en va de même du bilan : `review` propose, `keep` historise.
 */

import { request } from '@/lib/api';

/** Les cinq métriques de `GOAL-04`, telles que le serveur les nomme. */
export type GoalMetric =
  'weight' | 'weekly_sessions' | 'weekly_distance_km' | 'daily_protein_g' | 'hydration';

export interface GoalProgress {
  metric: string;
  label: string;
  unit: string;
  /** Valeur au jour de l'adoption. `null` quand rien n'avait été relevé. */
  baseline: number | null;
  current: number | null;
  target: number;
  /** `0` → au point de départ, `1` → cible atteinte. `null` faute de point de départ. */
  ratio: number | null;
  /** Libellé chiffré prêt à afficher, virgule française comprise. */
  summary: string;
  /** Fenêtre d'observation, en français : « moyenne des 4 dernières semaines complètes ». */
  basis: string;
}

export interface GoalEntry {
  id: number;
  token: string;
  goal_id: string;
  created: string | null;
  title: string;
  metric: string;
  target: number;
  unit: string;
  deadline: string;
  rationale: string;
  /** `manual` ou `ai` — d'où vient la ligne, pas ce qu'elle vaut. */
  source: string;
  status: string;
  outcome: string;
  /** Libellé français du résultat : l'écran ne traduit pas un code (`API-07`). */
  outcome_label: string;
}

export interface ActiveGoal {
  goal: GoalEntry;
  progress: GoalProgress;
  /** Négatif une fois l'échéance passée. */
  days_left: number;
  expired: boolean;
}

export interface GoalsView {
  /**
   * Les deux états que le **serveur** connaît (`GOAL-05`).
   *
   * Le troisième — « suggestion en attente » — n'existe que dans l'écran qui vient de la
   * recevoir, et se perd au rechargement. C'est la traduction exacte de « rien n'est écrit
   * sans validation » : un état qui survivrait au rechargement serait un état écrit.
   */
  state: 'none' | 'active';
  active: ActiveGoal | null;
  history: GoalEntry[];
  /** Aujourd'hui **selon le serveur** : le fuseau de découpage est son réglage. */
  today: string;
}

export interface ProposedGoal {
  title: string;
  metric: string;
  label: string;
  target: number;
  unit: string;
  deadline: string;
  rationale: string;
}

export interface GoalProposal {
  goal: ProposedGoal;
  /** Le condensé factuel réellement envoyé au modèle, ligne par ligne (`GOAL-02`). */
  basis: string[];
  /** Données trop maigres : la demande s'est repliée sur un objectif de régularité. */
  fallback: boolean;
  dropped: string[];
}

/** Ce qui part vers le serveur pour adopter. Sans unité : elle vient du registre. */
export interface GoalFormValues {
  title: string;
  metric: string;
  target: number;
  deadline: string;
  rationale: string;
}

// ── Bilan hebdomadaire (`IA-08`) ──────────────────────

export interface WeeklyReview {
  week: string;
  progress: string[];
  setbacks: string[];
  action: string;
  basis: string[];
}

export interface WeeklyEntry {
  id: number;
  token: string;
  week: string;
  created: string | null;
  summary: string;
  source: string;
}

export interface WeeklyView {
  entries: WeeklyEntry[];
  /** Semaine révolue que le prochain bilan commenterait. */
  next_week: string;
  already_kept: boolean;
}

/** Garde anti-conflit : le jeton lu est celui qu'on renvoie (`STO-05`). */
function ifMatch(token: string): Record<string, string> {
  return { 'If-Match': token };
}

export const goalsApi = {
  view: () => request<GoalsView>('/api/goals'),

  propose: (focus: string) =>
    request<GoalProposal>('/api/goals/proposal', { method: 'POST', body: { focus } }),

  adopt: (values: GoalFormValues) =>
    request<GoalEntry>('/api/goals', { method: 'POST', body: values }),

  /** Clôt l'objectif ; le **serveur** décide entre « atteint » et « partiel ». */
  close: (id: number, token: string) =>
    request<GoalEntry>(`/api/goals/${String(id)}/close`, {
      method: 'POST',
      headers: ifMatch(token),
    }),

  abandon: (id: number, token: string) =>
    request<GoalEntry>(`/api/goals/${String(id)}/abandon`, {
      method: 'POST',
      headers: ifMatch(token),
    }),

  weekly: () => request<WeeklyView>('/api/goals/weekly'),

  review: () => request<WeeklyReview>('/api/goals/weekly', { method: 'POST' }),

  keep: (week: string, summary: string) =>
    request<WeeklyEntry>('/api/goals/weekly/keep', {
      method: 'POST',
      body: { week, summary },
    }),

  removeReview: (id: number, token: string) =>
    request<undefined>(`/api/goals/weekly/${String(id)}`, {
      method: 'DELETE',
      headers: ifMatch(token),
    }),
};
