/**
 * Assistant conversationnel et mémoire de santé (`IA-09` → `IA-12`).
 *
 * Aucun calcul ici, comme partout ailleurs — mais surtout **aucune mémoire ici non plus**.
 * Le serveur ne stocke pas le fil : c'est l'écran qui lui rend l'historique à chaque
 * question, et qui le perd au rechargement. Deux onglets ouverts ne se mélangent donc
 * jamais.
 *
 * Deux appels ne se rejoignent jamais : `chat` rend des notes que personne n'a validées,
 * `adopt` écrit celles qu'on a gardées. Un écran qui enchaînerait les deux tout seul
 * romprait `IA-10`.
 */

import { request } from '@/lib/api';

export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export interface ProposedMemory {
  topic: string;
  note: string;
}

export interface ChatReply {
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

  ask: (question: string, history: Message[]) =>
    request<ChatReply>('/api/assistant/chat', { method: 'POST', body: { question, history } }),

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
