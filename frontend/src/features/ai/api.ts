/**
 * État de l'assistance IA (`IA-07`).
 *
 * Un écran ne demande jamais « y a-t-il une clé ? » à sa configuration : il le demande au
 * serveur, qui est le seul à la connaître. Le message vient de lui, en français, et
 * s'affiche tel quel — le client ne décide que sur `enabled` (`API-07`).
 */

import { request } from '@/lib/api';

export interface AiStatus {
  enabled: boolean;
  message: string;
}

export const aiApi = {
  status: () => request<AiStatus>('/api/ai/status'),
};
