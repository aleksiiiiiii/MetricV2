/**
 * Configuration de TanStack Query (`L03-07`).
 *
 * Deux décisions structurantes :
 *
 * * **Ne jamais réessayer un refus métier.** Un `409` de conflit, un `422` de validation
 *   ou un `401` de session expirée ne deviendront pas vrais en insistant — et réessayer
 *   une écriture en conflit trois fois est le meilleur moyen d'écraser la mauvaise ligne.
 *   Seules les pannes passagères sont rejouées (`STO-08`).
 * * **Clés de cache nommées par domaine.** Une invalidation croisée — enregistrer une
 *   course doit rafraîchir les agrégats et les heatmaps — se déclare avec le préfixe du
 *   domaine, sans énumérer les requêtes concernées.
 */

import { QueryClient } from '@tanstack/react-query';

import { ApiError, NetworkError } from '@/lib/api';

/** Préfixes de clés, un par domaine. Toujours passer par eux, jamais par un littéral. */
export const keys = {
  health: () => ['health'] as const,
  session: () => ['session'] as const,

  body: {
    all: () => ['body'] as const,
    weight: () => ['body', 'weight'] as const,
    measurements: () => ['body', 'measurements'] as const,
  },
  activity: {
    all: () => ['activity'] as const,
    overview: () => ['activity', 'overview'] as const,
    progress: () => ['activity', 'progress'] as const,
    runs: () => ['activity', 'runs'] as const,
    run: (id: number) => ['activity', 'runs', id] as const,
    /** La dernière course et ses paliers — ce que `/activite/course` ouvre par défaut. */
    latestRun: () => ['activity', 'runs', 'latest'] as const,
    runProgress: () => ['activity', 'runs', 'progress'] as const,
    runSplits: (id: number) => ['activity', 'runs', id, 'splits'] as const,
    workouts: () => ['activity', 'workouts'] as const,
    workout: (id: number) => ['activity', 'workouts', id] as const,
    exercises: () => ['activity', 'exercises'] as const,
    types: () => ['activity', 'types'] as const,
    muscleGroups: () => ['activity', 'muscle-groups'] as const,
  },
  hydration: {
    all: () => ['hydration'] as const,
    day: (day: string) => ['hydration', 'day', day] as const,
  },
  supplements: {
    all: () => ['supplements'] as const,
    schedule: () => ['supplements', 'schedule'] as const,
    today: () => ['supplements', 'today'] as const,
    units: () => ['supplements', 'units'] as const,
  },
  nutrition: {
    all: () => ['nutrition'] as const,
    meals: (day: string) => ['nutrition', 'meals', day] as const,
    favorites: () => ['nutrition', 'favorites'] as const,
  },
  aggregates: {
    all: () => ['aggregates'] as const,
    dashboard: () => ['aggregates', 'dashboard'] as const,
    metrics: () => ['aggregates', 'metrics'] as const,
    series: (metric: string, range: string, subject?: string) =>
      ['aggregates', 'series', metric, range, subject ?? ''] as const,
  },
  heatmap: {
    all: () => ['heatmap'] as const,
    tracks: () => ['heatmap', 'tracks'] as const,
    grid: (tracks: string[], from: string, to: string) =>
      ['heatmap', 'grid', tracks.join(','), from, to] as const,
    /** Grilles de l'écran : toutes les pistes actives, plage par défaut du serveur. */
    screen: () => ['heatmap', 'grid', 'all'] as const,
    day: (track: string, day: string) => ['heatmap', 'day', track, day] as const,
  },
  planning: {
    all: () => ['planning'] as const,
    month: (month: string) => ['planning', 'month', month] as const,
    adherence: () => ['planning', 'adherence'] as const,
    /** Adresse d'abonnement (`PLAN-05`) — elle vient d'un réglage serveur, elle ne
     *  change pas en cours de session. */
    subscription: () => ['planning', 'subscription'] as const,
  },
  assistant: {
    all: () => ['assistant'] as const,
    /** Les fils de discussion (`IA-13`). Ils vivent sur le serveur depuis le lot L18. */
    threads: () => ['assistant', 'threads'] as const,
    thread: (id: string) => ['assistant', 'threads', id] as const,
    /** Le carnet de mémoire (`IA-11`). Le fil de conversation, lui, n'est jamais mis en
     *  cache : il n'existe pas côté serveur. */
    memory: () => ['assistant', 'memory'] as const,
    /** Le profil (« Ce que je suis »). Il vit dans `settings.csv`, d'où l'invalidation
     *  croisée avec `settings` à l'écriture — les deux se partagent un jeton de fichier. */
    profile: () => ['assistant', 'profile'] as const,
  },
  brief: {
    all: () => ['brief'] as const,
    /** La lecture du jour. Une seule par journée, et le serveur décide laquelle. */
    today: () => ['brief', 'today'] as const,
  },
  goals: {
    all: () => ['goals'] as const,
    active: () => ['goals', 'active'] as const,
    /** Historique des bilans hebdomadaires (`IA-08`). */
    weekly: () => ['goals', 'weekly'] as const,
  },
  settings: {
    all: () => ['settings'] as const,
  },
  ai: {
    all: () => ['ai'] as const,
    /** État de l'assistance (`IA-07`) — lu une fois, il ne change pas en cours de session. */
    status: () => ['ai', 'status'] as const,
  },
  notifications: {
    all: () => ['notifications'] as const,
    /** État du push, appareils abonnés et créneaux, en une requête (`NOT-01`, `NOT-03`). */
    view: () => ['notifications', 'view'] as const,
  },
} as const;

/**
 * Domaines dont l'écriture doit rafraîchir les vues transverses.
 *
 * Toute source d'une piste d'assiduité invalide les grilles (`HEAT-33`) et le tableau de
 * bord (`AGG-01`) : sans cela, cocher un supplément laisserait la heatmap mentir jusqu'à
 * la prochaine navigation.
 */
export const CROSS_CUTTING = [keys.aggregates.all(), keys.heatmap.all()];

function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof NetworkError) return failureCount < 2;
  if (error instanceof ApiError) return error.isTransient && failureCount < 2;
  return false;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        // Les données changent parce que l'utilisateur les saisit, pas tout seules :
        // une fenêtre courte évite de relire Nextcloud à chaque navigation.
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        // Une écriture n'est jamais rejouée automatiquement : un conflit (`STO-05`) doit
        // remonter à l'utilisateur, pas être forcé.
        retry: false,
      },
    },
  });
}
