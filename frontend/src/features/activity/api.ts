/**
 * Accès au domaine Activité (`ACT-01` → `ACT-18`).
 *
 * Les durées et distances partent en **texte** : le serveur normalise `44:12`, `8,40`,
 * `1h30` (`ACT-01`). Le client ne convertit rien — un second analyseur finirait par
 * diverger du premier.
 */

import { request } from '@/lib/api';

export interface Run {
  id: number;
  token: string;
  date: string;
  distance_km: number;
  duration_min: number;
  pace_min_km: number | null;
  speed_kmh: number | null;
  avg_hr: number | null;
  elevation_m: number | null;
  /** Pas par minute. Rien ne la déduit : elle est saisie ou lue sur une capture. */
  cadence_spm: number | null;
  note: string | null;
  source: string;
  /** Identifiant stable, celui auquel les paliers se rattachent. Vide sur une saisie. */
  run_id: string;
  /** Kilocalories **actives** : la dépense de la séance seule. */
  active_calories: number | null;
  /** Kilocalories **totales**, métabolisme de base compris — jamais « calories » tout court. */
  total_calories: number | null;
  /** `19:40:00`, telle que le serveur la rend. Situe la séance, ne la date pas. */
  start_time: string | null;
  end_time: string | null;
  split_length_km: number | null;
  /** Nombre de paliers relevés. Zéro sur une course saisie au clavier, pas une erreur. */
  splits: number;
}

/**
 * Un palier d'une course (`ACT-19`).
 *
 * `partial` est le champ qui porte tout : sur 8,14 km, la neuvième ligne fait `00:44` et
 * n'est **pas** un kilomètre. Son allure est une extrapolation de l'application, pas une
 * mesure — l'écran la grise, et n'en fait aucune moyenne.
 */
export interface RunSplit {
  index: number;
  duration_s: number;
  /** La longueur réelle — 1 pour un plein, le reliquat pour un partiel. */
  distance_km: number | null;
  pace_min_km: number | null;
  cadence_spm: number | null;
  avg_hr: number | null;
  elevation_m: number | null;
  partial: boolean;
  /** Part de la barre de cadence, servie par le serveur : aucun `Math.max` à l'écran. */
  cadence_ratio: number | null;
  /** L'autre lecture de l'allure, pour qui lit en km/h. */
  speed_kmh: number | null;
  /** Mètres par pas — `distance ÷ (cadence × durée)`. Absente sans cadence relevée. */
  stride_m: number | null;
  /** Écart à l'allure moyenne des paliers pleins. **Négatif = plus rapide.** */
  delta_s_per_km: number | null;
  /**
   * Part **signée** de la barre divergente, entre -1 et 1.
   *
   * Le signe porte le côté et la valeur absolue la longueur : l'écran ne cherche ni
   * maximum ni sens dans la liste — les deux seraient un calcul métier sur une collection
   * de mesures.
   */
  deviation_ratio: number | null;
  /** Écart à la cadence moyenne, en pas par minute, et sa barre signée. */
  cadence_delta_spm: number | null;
  cadence_deviation_ratio: number | null;
}

export interface RunSplits {
  splits: RunSplit[];
  full_count: number;
  partial_count: number;
  /**
   * Secondes par kilomètre, seconde moitié moins première.
   *
   * **Négatif veut dire plus rapide**, ce qui se lit à l'envers du signe : l'écran le dit
   * en toutes lettres plutôt que de montrer un `-4,2` que rien n'explique.
   */
  drift_s_per_km: number | null;
  first_half_pace_min_km: number | null;
  second_half_pace_min_km: number | null;
  fastest_index: number | null;
  slowest_index: number | null;
  /** Bornes de l'axe d'allure, **le plus lent d'abord** : l'axe arrive déjà retourné. */
  pace_domain_min_km: [number, number] | null;
  cadence_max_spm: number | null;

  /**
   * Allure de référence des paliers pleins, celle contre laquelle les écarts se mesurent.
   * Elle diffère de l'allure de la course, qui inclut le reliquat.
   */
  average_pace_min_km: number | null;
  fastest_pace_min_km: number | null;
  slowest_pace_min_km: number | null;
  pace_spread_s_per_km: number | null;
  /** Écart-type des allures, en s/km — la régularité de la course en une valeur. */
  pace_sd_s_per_km: number | null;
  negative_split: boolean | null;

  cadence_avg_spm: number | null;
  cadence_min_spm: number | null;
  /**
   * **Positive = la foulée s'accélère** — le signe inverse de celui de `drift_s_per_km`.
   * Deux sens opposés pour deux dérives : l'écran nomme chacun en toutes lettres.
   */
  cadence_drift_spm: number | null;
  stride_avg_m: number | null;
  stride_min_m: number | null;
  stride_max_m: number | null;
  deviation_max_s_per_km: number | null;
  cadence_deviation_max_spm: number | null;
}

/** Une course de l'historique, réduite à ce qu'une courbe de tendance en montre. */
export interface RunMark {
  id: number;
  date: string;
  distance_km: number;
  pace_min_km: number | null;
  /** Celle qu'on regarde. Le serveur la désigne — l'écran ne compare pas d'identifiants. */
  current: boolean;
}

/**
 * Ce que l'historique dit de cette course-ci.
 *
 * **Un rang n'est pas un classement absolu.** Comparer l'allure d'un 8 km à celle d'un
 * 3 km est bancal : `runs_compared` accompagne toujours le rang, pour que l'écran écrive
 * « 2ᵉ sur 14 » et non « 2ᵉ ». Vide quand il n'y a qu'une course — une première sortie ne
 * se compare à rien, et un rang de 1 sur 1 ressemblerait à un record.
 */
export interface RunContext {
  runs_compared: number;
  pace_rank: number | null;
  distance_rank: number | null;
  best_pace_min_km: number | null;
  longest_distance_km: number | null;
  average_pace_min_km: number | null;
  average_distance_km: number | null;
  /** Écart de cette course aux moyennes. Négatif sur l'allure = plus rapide. */
  pace_delta_s_per_km: number | null;
  distance_delta_km: number | null;
  /** Les dernières sorties, la plus ancienne d'abord. */
  recent: RunMark[];
  /** Bornes de l'axe de tendance, le plus lent d'abord — servies, jamais dérivées ici. */
  pace_domain_min_km: [number, number] | null;
}

/**
 * Une bande de distance et son meilleur temps (`ACT-20`).
 *
 * **La seule comparaison d'allures honnête de la page.** 5'30" sur 15 km est une meilleure
 * course que 5'10" sur 3 km ; à l'intérieur d'une bande, les sorties se ressemblent assez
 * pour qu'un record veuille dire quelque chose.
 */
export interface DistanceBand {
  label: string;
  runs: number;
  best_pace_min_km: number | null;
  /** La course qui détient le record — l'écran y mène, il ne la cherche pas. */
  best_index: number | null;
  best_day: string | null;
  average_pace_min_km: number | null;
  total_distance_km: number;
}

/** Un mois de course. C'est ici que « progresser » se lit sans réserve à poser. */
export interface MonthTotals {
  /** `2026-08`. L'écran le met en forme, il ne le calcule pas. */
  month: string;
  runs: number;
  distance_km: number;
  minutes: number;
  pace_min_km: number | null;
}

/** Les N dernières sorties contre les N précédentes. `size` à 0 = trop peu pour comparer. */
export interface RunWindow {
  size: number;
  recent_pace_min_km: number | null;
  previous_pace_min_km: number | null;
  /** Secondes par kilomètre, récent moins précédent. **Négatif = plus rapide.** */
  pace_delta_s_per_km: number | null;
  recent_distance_km: number | null;
  previous_distance_km: number | null;
  distance_delta_km: number | null;
}

/** La page « Toutes tes courses » : la liste et ce qu'elle raconte, en une réponse. */
export interface RunProgress {
  /** Toutes les courses, la plus récente d'abord. */
  runs: Run[];
  total_runs: number;
  total_distance_km: number;
  total_minutes: number;
  /** Distance totale sur temps total — et non la moyenne des allures. */
  overall_pace_min_km: number | null;
  best_pace_min_km: number | null;
  best_pace_index: number | null;
  best_pace_day: string | null;
  longest_distance_km: number | null;
  longest_distance_index: number | null;
  longest_distance_day: string | null;
  longest_duration_min: number | null;
  bands: DistanceBand[];
  /** Du plus ancien au plus récent. Les mois sans course sont **absents**. */
  months: MonthTotals[];
  window: RunWindow;
  /** Bornes d'allure, **le plus lent d'abord** : l'axe arrive retourné. */
  pace_domain_min_km: [number, number] | null;
  volume_domain_km: [number, number] | null;
  /** Bornes de distance, le plus court d'abord — l'abscisse du nuage de points. */
  distance_domain_km: [number, number] | null;
}

/** Une course et ses paliers. `run` à `null` = aucune course, ce qui n'est pas une panne. */
export interface RunDetail {
  run: Run | null;
  splits: RunSplits;
  context: RunContext;
}

export interface ActivityItem {
  /**
   * `workout` désigne une **séance tabata déclarée faite**, plus une séance de
   * musculation saisie à la main : celle-ci n'existe plus. Le mot du fil est resté celui
   * de l'historique fusionné, où il distingue « ce qui n'est pas une course ».
   */
  kind: 'run' | 'workout';
  /** La position de la ligne dans son fichier — `runs.csv` ou `circuit_sessions.csv`. */
  id: number;
  token: string;
  date: string;
  label: string;
  duration_min: number;
  distance_km: number | null;
  pace_min_km: number | null;
  rpe: number | null;
  /** Les **rounds** d'une séance tabata. Zéro sur une course, qui n'en a pas. */
  entries: number;
  source: string;
}

export interface DayVolume {
  date: string;
  weekday: number;
  minutes: number;
  rest: boolean;
}

export interface WeekTotals {
  week_start: string;
  minutes: number;
  sessions: number;
  distance_km: number;
  pace_min_km: number | null;
}

export interface WeekVolume {
  week_start: string;
  minutes: number;
  sessions: number;
}

export interface NeglectedGroup {
  muscle_group: string;
  days_since: number | null;
  last_date: string | null;
}

export interface ActivityOverview {
  /** Le jour, dans le fuseau du serveur. L'écran ne consulte pas l'horloge du téléphone. */
  today: string;
  week: WeekTotals;
  days: DayVolume[];
  weeks: WeekVolume[];
  neglected: NeglectedGroup[];
  history: ActivityItem[];
  total: number;
}

export interface RunPayload {
  date: string;
  duration_min: string;
  distance_km?: string | null;
  /** `5:16` ou `5,27` — même écriture qu'une durée. */
  pace_min_km?: string | null;
  avg_hr?: string | null;
  elevation_m?: string | null;
  cadence_spm?: string | null;
  note?: string | null;
}

/** L'en-tête de garde d'une écriture destructrice (`STO-05`). */
function guard(token: string): Record<string, string> {
  return { 'If-Match': token };
}

// ── Circuits ouverts dans Cadence Tabata ──────────────

export interface CircuitExercise {
  position: number;
  name: string;
  muscle_group: string;
  duration_s: number | null;
  reps: number | null;
  rest_s: number;
  /** Ce qui a été **saisi** sur cet exercice. Vide et jamais `null` : c'est un champ. */
  note: string;
  /**
   * Ce que le **lien** porte en 4ᵉ champ — la charge et la note, déjà composées.
   *
   * `null` quand il n'y a ni l'une ni l'autre. Servi plutôt que recomposé
   * ici : il n'y a qu'un endroit au monde où « 12 » devient « 12 kg » et où les deux se
   * joignent, et c'est celui qui fabrique le lien. Deux compositions divergeraient, et la
   * carte annoncerait autre chose que ce que la séance affichera.
   */
  link_note: string | null;
}

export interface Circuit {
  id: number;
  token: string;
  circuit_id: string;
  name: string;
  rounds: number;
  round_rest_s: number;
  created: string | null;
  note: string | null;
  exercises: CircuitExercise[];
  /**
   * L'adresse à ouvrir, **déjà construite par le serveur**.
   *
   * `null` tant que l'adresse de Cadence n'est pas réglée. L'échappement, le bornage et le
   * suffixe qui distingue quinze répétitions de quinze secondes sont des règles métier :
   * l'écran pose ce qu'il reçoit dans un `href`, il ne fabrique rien.
   */
  url: string | null;
  estimated_duration_min: number;
  /** Faux dès qu'un exercice est en répétitions : le total s'affiche alors préfixé d'un `~`. */
  exact: boolean;
}

/**
 * Un nom d'exercice proposé à la saisie d'un circuit.
 *
 * **Servi par le serveur, jamais écrit ici.** Cadence embarque 1324 démonstrations : les
 * recopier ici mettrait 70 ko dans le paquet de l'application et les ferait diverger du
 * jour où elle en ajoute une. Le serveur cherche, l'écran affiche.
 */
export interface CircuitSuggestion {
  name: string;
  /** Le groupe musculaire quand l'exercice est au catalogue de Metric, `null` sinon. */
  muscle_group: string | null;
  /** Zone du corps et matériel quand la suggestion vient du catalogue de Cadence. */
  body_part: string | null;
  equipment: string | null;
}

export interface CircuitList {
  circuits: Circuit[];
  /**
   * Vrai quand une adresse de Cadence est réglée.
   *
   * **Non déductible de la liste** : sur une liste vide, l'écran doit distinguer « aucun
   * circuit » de « aucune adresse », et ces deux états ne proposent pas le même geste.
   */
  linkable: boolean;
}

export interface CircuitExercisePayload {
  name: string;
  muscle_group: string;
  duration_s?: number;
  reps?: number;
  rest_s: number;
  /** Ce qu'on veut lire sous le nom pendant l'effort. Le serveur y joint la charge. */
  note: string;
}

export interface CircuitPayload {
  name: string;
  rounds: number;
  round_rest_s: number;
  exercises: CircuitExercisePayload[];
  note?: string | null;
}

export interface CircuitDonePayload {
  duration_min: number;
  rpe?: number | null;
}

/** Une série d'un exercice, dans une séance déclarée faite. */
export interface CircuitSessionSet {
  exercise_name: string;
  muscle_group: string;
  sets: number;
  /** `null` sur un exercice au temps : la sentinelle du fichier ne sort pas de l'API. */
  reps: number | null;
}

/**
 * Un circuit **déclaré fait**, tel que le serveur le rend.
 *
 * Elle a remplacé `Workout` dans la réponse de « je l'ai fait » : la séance de
 * musculation manuelle n'existe plus, et rendre l'ancien schéma aurait obligé l'écran à
 * lire un `type` et un `workout_id` qui ne désignent plus rien.
 */
export interface CircuitSession {
  id: number;
  token: string;
  session_id: string;
  circuit_id: string;
  date: string;
  /** Le nom du circuit au moment où il a été fait (`ACT-06`). */
  name: string;
  rounds: number;
  duration_min: number;
  rpe: number | null;
  source: string;
  sets: CircuitSessionSet[];
}

// ── Charges des exercices de tabata ───────────────────

/**
 * L'état d'une charge, **décidé par le serveur**.
 *
 * Trois valeurs et non deux : « pas encore renseigné » n'est pas « poids du corps ». La
 * page groupe ses sections sur cette étiquette ; la déduire d'un `weight_kg` à `null`
 * reviendrait à tenir ici une règle qui vit là-bas.
 */
export type LoadState = 'unset' | 'bodyweight' | 'weighted';

/** Un exercice **proposé** par la composition assistée — ajustable, jamais écrit. */
export interface ProposedCircuitExercise {
  name: string;
  muscle_group: string;
  duration_s: number | null;
  reps: number | null;
  rest_s: number;
  /**
   * Vrai quand le nom est exactement celui d'un exercice du catalogue Cadence, donc quand
   * une démonstration s'affichera pendant l'effort.
   *
   * Faux **n'est pas une erreur** : un nom hors catalogue reste valide et la séance
   * tourne. C'est l'écran qui le dit, pour qu'on choisisse de corriger ou non.
   */
  illustrated: boolean;
}

export interface CircuitProposal {
  name: string;
  rounds: number;
  round_rest_s: number;
  exercises: ProposedCircuitExercise[];
  /** Ce sur quoi la proposition s'appuie — matériel pris en compte, groupes les plus anciens. */
  basis: string[];
  /** Exercices écartés à la relecture, et pourquoi. */
  dropped: string[];
}

export interface Load {
  /**
   * `null` tant qu'aucune charge n'a été déclarée : il n'y a alors **aucune ligne**, donc
   * ni position ni jeton. C'est ce couple à `null` qui dit à l'écran de créer plutôt que
   * de corriger.
   */
  id: number | null;
  token: string | null;
  name: string;
  state: LoadState;
  weight_kg: number | null;
  updated: string | null;
  /** Nombre de séances tabata qui emploient cet exercice. */
  circuits: number;
  /**
   * Jours depuis le dernier **changement** de charge, lu au journal des décisions.
   *
   * `null` quand le journal ne porte rien — jamais `0`, qui voudrait dire « changée
   * aujourd'hui ».
   */
  days_since_change: number | null;
  /**
   * Séances tenues à cette charge depuis ce changement.
   *
   * `0` est une mesure : « montée il y a trois jours, aucune séance depuis ». C'est `null`
   * qui dit qu'il n'y a rien depuis quoi compter.
   */
  sessions_since: number | null;
}

export interface LoadList {
  loads: Load[];
  /** Le pas des boutons plus et moins, servi plutôt que codé ici. */
  step_kg: number;
}

export interface LoadPoint {
  date: string;
  /**
   * `null` quand ce point est un passage au poids du corps : la courbe s'y **interrompt**
   * plutôt que de retomber à zéro, qui serait une charge nulle.
   */
  weight_kg: number | null;
}

export interface LoadDay {
  date: string;
  /** Séances de ce jour portant cet exercice. Zéro est une mesure, pas une absence. */
  count: number;
}

export interface LoadDetail {
  name: string;
  state: LoadState;
  weight_kg: number | null;
  /** Les décisions de charge, dans l'ordre. Vient du journal des changements. */
  history: LoadPoint[];
  /** **Exactement 30 entrées**, la dernière étant le jour du serveur. */
  sessions: LoadDay[];
  circuits: string[];
  /**
   * L'adresse du GIF de démonstration, servi par l'instance Cadence de l'utilisateur.
   *
   * `null` dans trois cas — pas d'adresse de base réglée, instance injoignable, nom sans
   * correspondance exacte au catalogue — et l'écran ne les distingue pas : aucun n'appelle
   * un geste différent, et « démonstration indisponible » ferait passer pour une panne
   * l'état normal d'un exercice écrit à la main.
   *
   * Metric ne relaie aucun octet : le navigateur va chercher l'image là où elle est déjà
   * servie. L'adresse porte donc la clé d'accès de la base.
   */
  demo_url: string | null;
}

export interface LoadPayload {
  name: string;
  weight_kg?: number;
  bodyweight?: boolean;
}

export const activityApi = {
  overview: () => request<ActivityOverview>('/api/activity'),
  muscleGroups: () => request<string[]>('/api/activity/muscle-groups'),

  createRun: (payload: RunPayload) =>
    request<Run>('/api/activity/runs', { method: 'POST', body: payload }),
  readRun: (id: number) => request<Run>(`/api/activity/runs/${id}`),
  latestRun: () => request<RunDetail>('/api/activity/runs/latest'),
  runProgress: () => request<RunProgress>('/api/activity/runs/progress'),
  runSplits: (id: number) => request<RunDetail>(`/api/activity/runs/${id}/splits`),
  updateRun: (id: number, token: string, payload: RunPayload) =>
    request<Run>(`/api/activity/runs/${id}`, {
      method: 'PATCH',
      headers: guard(token),
      body: payload,
    }),
  deleteRun: (id: number, token: string) =>
    request<undefined>(`/api/activity/runs/${id}`, { method: 'DELETE', headers: guard(token) }),

  circuits: () => request<CircuitList>('/api/activity/circuits'),
  circuitExercises: (query = '') =>
    request<CircuitSuggestion[]>(`/api/activity/circuits/exercises?q=${encodeURIComponent(query)}`),

  loads: () => request<LoadList>('/api/activity/loads'),
  loadDetail: (name: string) =>
    request<LoadDetail>(`/api/activity/loads/detail?name=${encodeURIComponent(name)}`),
  createLoad: (payload: LoadPayload) =>
    request<Load>('/api/activity/loads', { method: 'POST', body: payload }),
  updateLoad: (id: number, token: string, payload: LoadPayload) =>
    request<Load>(`/api/activity/loads/${id}`, {
      method: 'PATCH',
      headers: guard(token),
      body: payload,
    }),
  createCircuit: (payload: CircuitPayload) =>
    request<Circuit>('/api/activity/circuits', { method: 'POST', body: payload }),
  importCircuit: (url: string) =>
    request<Circuit>('/api/activity/circuits/import', { method: 'POST', body: { url } }),
  updateCircuit: (id: number, token: string, payload: CircuitPayload) =>
    request<Circuit>(`/api/activity/circuits/${id}`, {
      method: 'PATCH',
      headers: guard(token),
      body: payload,
    }),
  deleteCircuit: (id: number, token: string) =>
    request<undefined>(`/api/activity/circuits/${id}`, {
      method: 'DELETE',
      headers: guard(token),
    }),
  /**
   * Une phrase → un circuit **proposé**. N'écrit rien : c'est `createCircuit` qui écrit.
   *
   * Le matériel possédé, les contraintes et les groupes négligés partent avec la demande
   * côté serveur — l'écran n'a rien à leur sujet à envoyer, ni à tenir.
   */
  composeCircuit: (wish: string) =>
    request<CircuitProposal>('/api/activity/circuits/propose', {
      method: 'POST',
      body: { wish },
    }),
  completeCircuit: (id: number, payload: CircuitDonePayload) =>
    request<CircuitSession>(`/api/activity/circuits/${id}/done`, {
      method: 'POST',
      body: payload,
    }),

  /**
   * Supprime une séance tabata **et ses séries**.
   *
   * C'est ce qui autorise « je l'ai fait » à ne rien demander : l'addition se défait par
   * la suppression que l'utilisateur ferait de toute façon. Cadence ne pouvant pas dire à
   * Metric qu'une séance a eu lieu, la déclarer deux fois reste possible.
   */
  deleteSession: (id: number, token: string) =>
    request<undefined>(`/api/activity/sessions/${id}`, {
      method: 'DELETE',
      headers: guard(token),
    }),
};
