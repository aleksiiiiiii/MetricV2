/**
 * Assistant conversationnel et mémoire de santé (`IA-09` → `IA-12`).
 *
 * Aucun calcul ici, comme partout ailleurs. **Et l'écran ne tient plus l'historique** :
 * le fil vit sur le serveur, on lui donne son identifiant et il sait ce qui a été dit.
 * Un client pouvait envoyer le passé qu'il voulait — sans portée tant que rien ne
 * s'écrivait, ce qui n'est plus le cas.
 */

import { ApiError, request, tokenStore } from '@/lib/api';

/** Ce qu'on dit quand le flux s'arrête sans avoir rien conclu. */
const INTERRUPTED = 'La réponse a été interrompue. Réessaie.';

/** Une valeur du flux, quand — et seulement quand — c'est bien une chaîne. */
function asText(value: unknown, fallback: string): string {
  return typeof value === 'string' && value !== '' ? value : fallback;
}

/** Un bloc `text/event-stream` décodé, ou `null` s'il n'en est pas un. */
function readEvent(block: string): { event: string; data: Record<string, unknown> } | null {
  let event = '';
  let raw = '';
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim();
    if (line.startsWith('data: ')) raw = line.slice(6);
  }
  if (event === '' || raw === '') return null;
  try {
    return { event, data: JSON.parse(raw) as Record<string, unknown> };
  } catch {
    return null;
  }
}

export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export interface ThreadSummary {
  thread_id: string;
  title: string;
  created: string | null;
  updated: string | null;
  messages: number;
}

export interface ThreadList {
  threads: ThreadSummary[];
  /**
   * Le fil à **rouvrir de lui-même**, ou `null`.
   *
   * La décision vient du serveur : c'est lui qui tient l'heure et le fuseau, et mesurer
   * l'écart ici serait un second calcul de temps — celui que l'invariant « le jour vient
   * du serveur » interdit. L'écran reçoit un identifiant ou rien.
   */
  resume: string | null;
}

export interface ThreadMessage {
  seq: number;
  role: 'user' | 'assistant';
  content: string;
  created: string | null;
  /**
   * Le condensé qui a produit **ce** message (`IA-09`).
   *
   * Vide sur une question, et vide sur les réponses écrites avant que la colonne existe :
   * un fil ancien ne ment pas, il dit qu'il ne sait pas.
   */
  context: string[];
  /**
   * Ce que ce tour a fait, **sans son annulation**.
   *
   * Le jeton d'une ligne périme dès qu'elle change ; proposer « annuler » trois jours plus
   * tard mènerait à un `409` que rien n'explique. Ce qui reste ne périme pas : la phrase,
   * le lien, l'identifiant — et un lien Cadence porte la séance entière.
   */
  actions: ActionReport[];
}

export interface ThreadDetail {
  thread_id: string;
  title: string;
  created: string | null;
  updated: string | null;
  messages: ThreadMessage[];
}

export interface UndoRef {
  /** Le **chemin** de la ressource, sans `/api/` ni la ligne : « body/weight ». */
  domain: string;
  row_id: number;
  token: string;
}

export interface ActionReport {
  name: string;
  level: 'add' | 'change';
  /** `done` — écrit, annulable. `pending` — un appui décidera. `refused` — rien n'a eu lieu. */
  status: 'done' | 'pending' | 'refused';
  /** Une phrase française, destinée à être lue telle quelle. */
  summary: string;
  /** Les arguments relus, à renvoyer pour confirmer une action en attente. */
  args: Record<string, unknown>;
  undo: UndoRef | null;
  /**
   * Une adresse **hors de l'application** — aujourd'hui une séance Cadence.
   *
   * Elle est rendue en bouton, jamais recopiée dans le texte : c'est le serveur qui l'a
   * fabriquée, et c'est ce qui garantit qu'elle décrit la séance qu'on croit.
   */
  link: string | null;
  /**
   * L'identifiant **stable** de ce qui a été créé, quand la ligne en porte un.
   *
   * `undo.row_id` est une position dans un fichier : elle se décale à la première
   * suppression. Elle suffit à annuler dans la seconde qui suit, pas à retrouver la même
   * ligne en rouvrant le fil trois jours plus tard.
   */
  resource_id: string | null;
}

export interface ChatReply {
  /** Le fil, ouvert ou poursuivi. À redonner à la question suivante. */
  thread_id: string;
  title: string;
  reply: string;
  /** Ce qui vient d'être **retenu** — écrit, avec de quoi le retirer (`IA-10`). */
  remember: MemoryEntry[];
  /** Ce que l'assistant a fait, ou demande à faire. Vide le plus souvent. */
  actions: ActionReport[];
  /** Le condensé factuel réellement envoyé au modèle, ligne par ligne (`IA-09`). */
  context: string[];
}

export interface MemoryEntry {
  id: number;
  token: string;
  memory_id: string;
  created: string | null;
  topic: string;
  note: string;
  /** `ai` ou `manual` — d'où vient la note, pas ce qu'elle vaut. */
  source: string;
  /**
   * Le jour où la note a cessé d'être vraie. `null` tant qu'elle l'est encore.
   *
   * Une date et non un booléen : « résolu le 30/05 » situe une reprise de volume, et une
   * blessure guérie reste une information — elle dit ce qui a déjà lâché.
   */
  resolved: string | null;
}

/** Un matériel proposé à la case à cocher. La liste vient du serveur — voir `ProfileView`. */
export interface EquipmentOption {
  value: string;
  /** Montré d'emblée, ou rangé derrière le dépliant. Choix d'affichage, pas de filtrage. */
  common: boolean;
}

export interface ProfileView {
  height_cm: number | null;
  birth_year: number | null;
  training_days: string;
  /** Le matériel possédé, en valeurs du catalogue Cadence. */
  equipment: string[];
  /**
   * Ce que la cellule portait et que le catalogue ne reconnaît pas — le texte libre d'un
   * profil d'avant la fermeture du champ. Montré ici, **pas envoyé au modèle**.
   */
  equipment_unknown: string[];
  /**
   * Les 28 matériels et leur rang d'affichage, **servis par le serveur**.
   *
   * L'écran n'en tient aucune copie : une liste tenue dans deux langages finit par ne plus
   * décrire la même chose, et la divergence serait muette — un matériel absent d'ici ne se
   * cocherait jamais.
   */
  equipment_catalogue: EquipmentOption[];
  preferences: string;
  constraints: string;
  /** L'âge, **calculé par le serveur**. Un âge rangé est faux au premier anniversaire. */
  age: number | null;
  /** Les lignes exactes envoyées au modèle — la promesse se vérifie à l'écran. */
  lines: string[];
  token: string;
}

export interface ProfilePayload {
  height_cm: number | null;
  birth_year: number | null;
  training_days: string;
  equipment: string[];
  preferences: string;
  constraints: string;
}

export interface AssistantView {
  memories: MemoryEntry[];
  /** Sujets les plus fréquents, servis par le serveur. La colonne reste libre. */
  topics: string[];
  today: string;
}

/** Garde anti-conflit : le jeton lu est celui qu'on renvoie (`STO-05`). */
function ifMatch(token: string): Record<string, string> {
  return { 'If-Match': token };
}

export const assistantApi = {
  memory: () => request<AssistantView>('/api/assistant/memory'),

  profile: () => request<ProfileView>('/api/assistant/profile'),

  /**
   * Remplace le profil **en entier**.
   *
   * `PUT` et non `PATCH` : vider un champ — « je n'ai plus de rack » — est un geste normal
   * sur un formulaire qu'on voit en entier, et « absent = inchangé » le rendrait
   * impossible depuis l'écran même qui montre le champ.
   */
  setProfile: (payload: ProfilePayload, token: string) =>
    request<ProfileView>('/api/assistant/profile', {
      method: 'PUT',
      body: payload,
      headers: ifMatch(token),
    }),

  /** Pose une question. Sans `threadId`, le serveur ouvre un fil et rend son identifiant. */
  ask: (question: string, threadId: string | null) =>
    request<ChatReply>('/api/assistant/chat', {
      method: 'POST',
      body: threadId === null ? { question } : { question, thread_id: threadId },
    }),

  /**
   * La même question, en suivant ce que le serveur fait pendant qu'il le fait.
   *
   * **Le flux transporte les étapes et la réponse pendant qu'elle s'écrit.** Il ne l'a pas
   * toujours fait : une seconde passe remplace entièrement la première, donc un texte
   * affiché au fil de l'eau aurait parfois dû être effacé. C'est le serveur qui a levé
   * l'objection, pas l'écran — il ne diffuse que ce qu'il peut prouver final.
   *
   * Ce qui arrive ici est donc sûr : `onDelta` ne reçoit que du texte qui restera, et
   * `onReset` n'est appelé que si un modèle tombe après avoir parlé, cas où le suivant
   * repart de zéro. **La réponse rendue reste l'autorité** : c'est elle qui a été relue,
   * bornée et stockée, et l'appelant l'affiche telle quelle à la fin.
   *
   * Écrit à la main plutôt qu'avec `request` : celui-ci lit le corps en entier avant de
   * rendre, ce qui est exactement ce qu'un flux ne doit pas faire. Et `EventSource` ne
   * sait pas poster ni porter un en-tête d'autorisation.
   *
   * **Un repli existe.** Si le flux échoue avant d'avoir rendu quoi que ce soit — un
   * proxy qui ne le laisse pas passer, un navigateur sans `ReadableStream` —, l'appel
   * ordinaire prend le relais : on perd l'avancement, jamais la réponse (`IA-07` dans son
   * esprit — l'agrément tombe, la fonction reste).
   */
  askStreaming: async (
    question: string,
    threadId: string | null,
    onStep: (step: string) => void,
    onDelta?: (text: string) => void,
    onReset?: () => void,
  ): Promise<ChatReply> => {
    const token = tokenStore.read();
    let response: Response;
    try {
      response = await fetch('/api/assistant/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(threadId === null ? { question } : { question, thread_id: threadId }),
      });
    } catch {
      return assistantApi.ask(question, threadId);
    }

    // `!response.body` et non `=== null` : un navigateur sans flux de lecture rend
    // `undefined`, et c'est précisément le cas où le repli doit prendre la main.
    if (!response.ok || !response.body) {
      return assistantApi.ask(question, threadId);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let reply: ChatReply | null = null;
    let failure: ApiError | null = null;

    // Un événement se termine par une ligne vide ; le tampon garde ce qui n'est pas
    // encore complet, parce qu'un paquet réseau coupe où il veut.
    for (;;) {
      const { done, value } = await reader.read();
      if (value !== undefined) buffer += decoder.decode(value, { stream: true });

      let cut = buffer.indexOf('\n\n');
      while (cut !== -1) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const parsed = readEvent(block);
        if (parsed?.event === 'step') onStep(asText(parsed.data.step, ''));
        if (parsed?.event === 'delta') onDelta?.(asText(parsed.data.text, ''));
        if (parsed?.event === 'reset') onReset?.();
        if (parsed?.event === 'reply') reply = parsed.data as unknown as ChatReply;
        if (parsed?.event === 'error') {
          failure = new ApiError(
            {
              code: asText(parsed.data.code, 'ai_unavailable'),
              message: asText(parsed.data.message, 'Question impossible.'),
            },
            503,
          );
        }
        cut = buffer.indexOf('\n\n');
      }

      if (done) break;
    }

    if (failure !== null) throw failure;
    // Un flux qui se termine sans réponse ni erreur — coupure en cours de route.
    if (reply === null) throw new ApiError({ code: 'ai_unavailable', message: INTERRUPTED }, 503);
    return reply;
  },

  threads: () => request<ThreadList>('/api/assistant/threads'),

  thread: (threadId: string) => request<ThreadDetail>(`/api/assistant/threads/${threadId}`),

  /** Change le titre d'un fil, et rien d'autre — sa place dans la liste ne bouge pas. */
  renameThread: (threadId: string, title: string) =>
    request<ThreadSummary>(`/api/assistant/threads/${threadId}`, {
      method: 'PATCH',
      body: { title },
    }),

  forgetThread: (threadId: string) =>
    request<undefined>(`/api/assistant/threads/${threadId}`, { method: 'DELETE' }),

  forgetAllThreads: () => request<undefined>('/api/assistant/threads', { method: 'DELETE' }),

  /** Exécute une action laissée en attente. Elle est revalidée côté serveur. */
  confirmAction: (name: string, args: Record<string, unknown>) =>
    request<ActionReport>('/api/assistant/actions/confirm', {
      method: 'POST',
      body: { name, args },
    }),

  /**
   * Défait un ajout, par la route du domaine.
   *
   * Aucune table de correspondance ici : `domain` **est** le chemin de la ressource, et un
   * test du serveur vérifie qu'il désigne une route de suppression réelle. C'est la même
   * requête que celle qu'un écran envoie quand on supprime une ligne à la main.
   */
  undo: (ref: UndoRef) =>
    request<undefined>(`/api/${ref.domain}/${String(ref.row_id)}`, {
      method: 'DELETE',
      headers: ifMatch(ref.token),
    }),

  /** Écrit une note tapée à la main, marquée `manual`. */
  remember: (topic: string, note: string) =>
    request<MemoryEntry>('/api/assistant/memory', { method: 'POST', body: { topic, note } }),

  /**
   * Corrige une note, et optionnellement son statut.
   *
   * `resolved` omis ne touche à rien — corriger une faute de frappe ne doit pas réveiller
   * une blessure guérie. La **date** de résolution est décidée par le serveur : un écran
   * ne date aucune donnée.
   */
  update: (id: number, token: string, topic: string, note: string, resolved?: boolean) =>
    request<MemoryEntry>(`/api/assistant/memory/${String(id)}`, {
      method: 'PATCH',
      body: resolved === undefined ? { topic, note } : { topic, note, resolved },
      headers: ifMatch(token),
    }),

  forget: (id: number, token: string) =>
    request<undefined>(`/api/assistant/memory/${String(id)}`, {
      method: 'DELETE',
      headers: ifMatch(token),
    }),
};
