/**
 * Assistant conversationnel et mémoire de santé (`IA-09` → `IA-12`).
 *
 * Aucun calcul ici, comme partout ailleurs. **Et l'écran ne tient plus l'historique** :
 * le fil vit sur le serveur, on lui donne son identifiant et il sait ce qui a été dit.
 * Un client pouvait envoyer le passé qu'il voulait — sans portée tant que rien ne
 * s'écrivait, ce qui n'est plus le cas.
 */

import { request } from '@/lib/api';

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

export interface ThreadMessage {
  seq: number;
  role: 'user' | 'assistant';
  content: string;
  created: string | null;
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

  /** Pose une question. Sans `threadId`, le serveur ouvre un fil et rend son identifiant. */
  ask: (question: string, threadId: string | null) =>
    request<ChatReply>('/api/assistant/chat', {
      method: 'POST',
      body: threadId === null ? { question } : { question, thread_id: threadId },
    }),

  threads: () => request<{ threads: ThreadSummary[] }>('/api/assistant/threads'),

  thread: (threadId: string) => request<ThreadDetail>(`/api/assistant/threads/${threadId}`),

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

  update: (id: number, token: string, topic: string, note: string) =>
    request<MemoryEntry>(`/api/assistant/memory/${String(id)}`, {
      method: 'PATCH',
      body: { topic, note },
      headers: ifMatch(token),
    }),

  forget: (id: number, token: string) =>
    request<undefined>(`/api/assistant/memory/${String(id)}`, {
      method: 'DELETE',
      headers: ifMatch(token),
    }),
};
