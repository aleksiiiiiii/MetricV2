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

export interface ProposedMemory {
  topic: string;
  note: string;
}

export interface ChatReply {
  /** Le fil, ouvert ou poursuivi. À redonner à la question suivante. */
  thread_id: string;
  title: string;
  reply: string;
  /** Ce qui mérite d'être retenu, **en attente de validation**. */
  remember: ProposedMemory[];
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

  /** Écrit une note tapée à la main, marquée `manual`. */
  remember: (topic: string, note: string) =>
    request<MemoryEntry>('/api/assistant/memory', { method: 'POST', body: { topic, note } }),

  /** Écrit une note **proposée** puis validée, marquée `ai` (`IA-10`). */
  adopt: (topic: string, note: string) =>
    request<MemoryEntry>('/api/assistant/memory/adopt', {
      method: 'POST',
      body: { topic, note },
    }),

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
