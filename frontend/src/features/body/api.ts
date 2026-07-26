/**
 * Accès au domaine Corps (`BODY-01` → `BODY-10`).
 *
 * Les types reflètent exactement les schémas du serveur. Aucun calcul ici : indicateurs,
 * tendance et écarts arrivent déjà calculés — c'est la règle du projet.
 */

import { request } from '@/lib/api';

export interface WeightEntry {
  id: number;
  /** À renvoyer en `If-Match` pour corriger ou supprimer (`STO-05`). */
  token: string;
  date: string;
  weight_kg: number;
  note: string | null;
  source: string;
}

export interface WeightPoint {
  date: string;
  weight_kg: number;
  trend_kg: number | null;
}

export interface WeightStats {
  latest_kg: number | null;
  latest_date: string | null;
  change_kg: number | null;
  to_target_kg: number | null;
  target_kg: number;
  min_kg: number | null;
  max_kg: number | null;
  amplitude_kg: number | null;
  count: number;
}

export interface WeightView {
  stats: WeightStats;
  series: WeightPoint[];
  entries: WeightEntry[];
  total: number;
}

export interface WeightPayload {
  date: string;
  weight_kg: number;
  note?: string | null;
}

export interface MeasurementEntry {
  id: number;
  token: string;
  date: string;
  waist_cm: number | null;
  chest_cm: number | null;
  arm_cm: number | null;
  hips_cm: number | null;
  thigh_cm: number | null;
  body_fat_pct: number | null;
  note: string | null;
}

export interface MeasurementIndicator {
  field: string;
  label: string;
  latest: number | null;
  latest_date: string | null;
  delta: number | null;
  direction: 'up' | 'down' | 'flat' | null;
  unit: string;
}

export interface MeasurementView {
  indicators: MeasurementIndicator[];
  entries: MeasurementEntry[];
  total: number;
}

export interface MeasurementPayload {
  date: string;
  waist_cm?: number | null;
  chest_cm?: number | null;
  arm_cm?: number | null;
  hips_cm?: number | null;
  thigh_cm?: number | null;
  body_fat_pct?: number | null;
  note?: string | null;
}

/** L'en-tête qui porte la garde anti-conflit. */
function guard(token: string): Record<string, string> {
  return { 'If-Match': token };
}

export const bodyApi = {
  weight: (limit = 50) => request<WeightView>('/api/body/weight', { query: { limit } }),

  createWeight: (payload: WeightPayload) =>
    request<WeightEntry>('/api/body/weight', { method: 'POST', body: payload }),

  updateWeight: (id: number, token: string, payload: WeightPayload) =>
    request<WeightEntry>(`/api/body/weight/${id}`, {
      method: 'PATCH',
      body: payload,
      headers: guard(token),
    }),

  deleteWeight: (id: number, token: string) =>
    request<undefined>(`/api/body/weight/${id}`, { method: 'DELETE', headers: guard(token) }),

  measurements: (limit = 50) =>
    request<MeasurementView>('/api/body/measurements', { query: { limit } }),

  createMeasurement: (payload: MeasurementPayload) =>
    request<MeasurementEntry>('/api/body/measurements', { method: 'POST', body: payload }),

  deleteMeasurement: (id: number, token: string) =>
    request<undefined>(`/api/body/measurements/${id}`, {
      method: 'DELETE',
      headers: guard(token),
    }),
};
