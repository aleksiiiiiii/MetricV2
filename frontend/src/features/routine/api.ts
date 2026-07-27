/**
 * Accès à l'hydratation (`HYD-01` → `HYD-05`) et aux suppléments (`SUP-01` → `SUP-06`).
 *
 * Les deux domaines partagent un écran — la routine du jour — mais restent deux
 * ressources distinctes côté API.
 */

import { request } from '@/lib/api';

// ── Hydratation ───────────────────────────────────────

export interface HydrationIntake {
  id: number;
  token: string;
  datetime: string;
  volume_ml: number;
  kind: string | null;
}

export interface HydrationDay {
  date: string;
  volume_ml: number;
  reached: boolean;
}

export interface HydrationStats {
  today_ml: number;
  target_ml: number;
  ratio: number;
  average_7d_ml: number | null;
  average_30d_ml: number | null;
  days_reached: number;
  days_counted: number;
}

export interface HydrationView {
  stats: HydrationStats;
  series: HydrationDay[];
  today: HydrationIntake[];
  presets_ml: number[];
  kinds: string[];
}

// ── Suppléments ───────────────────────────────────────

export interface Supplement {
  id: number;
  token: string;
  schedule_id: string;
  name: string;
  dose: number;
  unit: string;
  time: string;
  frequency: string;
  cadence_label: string;
  active: boolean;
  created: string | null;
}

export interface ChecklistItem {
  schedule_id: string;
  name: string;
  dose: number;
  unit: string;
  time: string;
  cadence_label: string;
  taken: boolean;
  taken_at: string | null;
  intake_id: number | null;
  intake_token: string | null;
  streak: number;
}

export interface DayRatio {
  taken: number;
  planned: number;
  ratio: number;
  complete: boolean;
}

export interface ChecklistView {
  date: string;
  items: ChecklistItem[];
  ratio: DayRatio;
}

export interface SupplementPayload {
  name: string;
  dose: number;
  unit: string;
  time: string;
  frequency?: string;
  active?: boolean;
}

export const routineApi = {
  hydration: (days = 30) => request<HydrationView>('/api/hydration', { query: { days } }),
  drink: (volume_ml: number, kind?: string) =>
    request<HydrationIntake>('/api/hydration', {
      method: 'POST',
      body: { volume_ml, ...(kind ? { kind } : {}) },
    }),
  undrink: (id: number, token: string) =>
    request<undefined>(`/api/hydration/${id}`, {
      method: 'DELETE',
      headers: { 'If-Match': token },
    }),

  checklist: () => request<ChecklistView>('/api/supplements/today'),
  take: (schedule_id: string) =>
    request<ChecklistView>('/api/supplements/today', {
      method: 'POST',
      body: { schedule_id },
    }),
  untake: (schedule_id: string) =>
    request<ChecklistView>(`/api/supplements/today/${schedule_id}`, { method: 'DELETE' }),

  schedule: () => request<Supplement[]>('/api/supplements/schedule'),
  addSupplement: (payload: SupplementPayload) =>
    request<Supplement>('/api/supplements/schedule', { method: 'POST', body: payload }),
  removeSupplement: (id: number, token: string) =>
    request<undefined>(`/api/supplements/schedule/${id}`, {
      method: 'DELETE',
      headers: { 'If-Match': token },
    }),
  units: () => request<string[]>('/api/supplements/units'),
};
