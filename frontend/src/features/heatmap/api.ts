/**
 * Accès aux grilles d'assiduité (`L11-01` → `L11-03`, `L11-10`).
 *
 * **Rien n'est calculé ici.** Ni état, ni niveau, ni série, ni taux de respect : le
 * serveur les rend tout faits, et `HEAT-30` l'exige explicitement — deux implémentations
 * d'une fenêtre glissante divergent au premier cas limite, et c'est l'utilisateur qui
 * arbitre alors entre deux chiffres qui devraient être identiques.
 *
 * Deux choses qui pourraient passer pour dérivables sont donc servies, et il ne faut pas
 * les recalculer : le **libellé français de la cadence** (`cadence.label`) et la
 * **raison** d'un jour `off` (`day.reason`).
 */

import { request } from '@/lib/api';

/** Les quatre états de `HEAT-05`. Rien d'autre ne décide d'une couleur. */
export type DayState = 'off' | 'missed' | 'done' | 'bonus';

/**
 * Pourquoi un jour est `off`, quand ce n'est pas la cadence qui l'a décidé.
 *
 * Nuance d'**affichage** : elle ne dit pas si le jour compte — c'est `state` qui le dit,
 * et lui seul.
 */
export type DayReason = 'neutralised' | 'before_track' | 'future' | 'pending';

export type WeekStatus = 'reached' | 'partial' | 'missed' | 'off';

export interface HeatDay {
  /** `AAAA-MM-JJ`, jour local (`HEAT-32`). */
  date: string;
  value: number;
  state: DayState;
  /** 0 à 4 (`HEAT-15`). Nul sur tout ce qui n'est pas validé. */
  level: number;
  reason: DayReason | null;
}

export interface HeatWeek {
  /** Lundi de la semaine ISO. */
  start: string;
  status: WeekStatus;
  done: number;
  expected: number;
}

export interface HeatStats {
  validated_days: number;
  /** Sur une piste hebdomadaire, ce sont des créneaux et non des jours. */
  expected_days: number;
  /** `null` quand rien n'était attendu : zéro se lirait comme un échec. */
  compliance: number | null;
  longest_streak: number;
  current_streak: number;
  best_day: string | null;
  best_value: number | null;
  total: number;
}

export interface CadenceView {
  type: string;
  params: Record<string, string | number>;
  /** Formulation française, composée par le serveur (`HEAT-30`). */
  label: string;
  /** Forme stockée, à renvoyer telle quelle pour laisser la cadence inchangée. */
  serialized: string;
  valid_from: string | null;
}

export interface GridTrack {
  id: string;
  label: string;
  unit: string;
  binary: boolean;
  accent: string;
  source: string;
  levels: number[];
  validation_threshold: number;
  created: string | null;
}

export interface DateRange {
  from: string;
  to: string;
}

export interface Grid {
  track: GridTrack;
  cadence: CadenceView;
  range: DateRange;
  days: HeatDay[];
  /** `null` sur une piste qui ne se juge pas à la semaine. */
  weeks: HeatWeek[] | null;
  stats: HeatStats;
}

export interface GridsView {
  /** Partagée par toutes les grilles : elles s'affichent alignées. */
  range: DateRange;
  grids: Grid[];
}

/** Une ligne de saisie sous une cellule (`HEAT-29`). Des nombres, pas des phrases. */
export interface DayEntry {
  label: string;
  value: number;
  unit: string;
  time: string | null;
  sets: number | null;
  reps: number | null;
  weight_kg: number | null;
  muscle_group: string | null;
  distance_km: number | null;
  duration_min: number | null;
  pace_min_km: number | null;
  dose: number | null;
  dose_unit: string | null;
  note: string | null;
}

export interface DayInspection {
  track: GridTrack;
  day: HeatDay;
  entries: DayEntry[];
}

// ── Configuration (`HEAT-18` → `HEAT-22`) ─────────────

export interface SourceDescriptor {
  key: string;
  label: string;
  unit: string;
  filter_label: string | null;
}

export interface Track {
  id: number;
  /** À renvoyer en « If-Match » pour modifier ou supprimer (`STO-05`). */
  token: string;
  track_id: string;
  label: string;
  source: string;
  source_label: string;
  unit: string;
  filter: string;
  validation_threshold: number;
  levels: number[];
  binary: boolean;
  accent: string;
  position: number;
  active: boolean;
  created: string | null;
  cadence: CadenceView;
  cadence_history: CadenceView[];
}

export interface OffDay {
  id: number;
  token: string;
  off_id: string;
  /** Vide = toutes les pistes. */
  track_id: string;
  date_from: string;
  date_to: string;
  reason: string;
  days: number;
}

export interface TracksView {
  tracks: Track[];
  /** Catalogue servi par le serveur : l'écran n'en code aucune source (`HEAT-02`). */
  sources: SourceDescriptor[];
  off_days: OffDay[];
  highlight: string;
  accents: string[];
}

export interface TrackPayload {
  label: string;
  source: string;
  filter: string;
  validation_threshold: number;
  levels: number[];
  binary: boolean;
  accent: string;
  /** Forme sérialisée — `window:min_count=1;window_days=2`. */
  cadence: string;
  active: boolean;
}

export interface TrackSaved {
  track: Track;
  recalculated_history: boolean;
  warnings: string[];
}

/**
 * Ce qu'une modification ferait à l'historique, **avant** de la valider (`HEAT-20`, D4).
 *
 * Le compte vient du serveur, qui évalue la grille deux fois et compare. Le client ne
 * fait que l'afficher : recompter côté écran supposerait de réimplémenter la machine à
 * états, ce que `HEAT-30` interdit.
 */
export interface TrackImpact {
  retroactive: boolean;
  range: DateRange;
  changed_days: number;
  to_missed: number;
  to_done: number;
  restyled: number;
  warnings: string[];
}

export interface OffDayPayload {
  track_id: string;
  date_from: string;
  date_to: string;
  reason: string;
}

export const heatmapApi = {
  /** Toutes les grilles en une requête (`HEAT-25`). */
  grids: (tracks?: string[], range?: DateRange) =>
    request<GridsView>('/api/heatmap', {
      query: {
        ...(tracks && tracks.length > 0 ? { tracks: tracks.join(',') } : {}),
        ...(range ? { from: range.from, to: range.to } : {}),
      },
    }),

  grid: (trackId: string, range?: DateRange) =>
    request<Grid>(`/api/heatmap/${encodeURIComponent(trackId)}`, {
      query: range ? { from: range.from, to: range.to } : {},
    }),

  day: (trackId: string, day: string) =>
    request<DayInspection>(
      `/api/heatmap/${encodeURIComponent(trackId)}/day/${encodeURIComponent(day)}`,
    ),

  tracks: () => request<TracksView>('/api/heatmap/tracks'),

  create: (payload: TrackPayload) =>
    request<Track>('/api/heatmap/tracks', { method: 'POST', body: payload }),

  update: (trackId: string, payload: TrackPayload, token: string) =>
    request<TrackSaved>(`/api/heatmap/tracks/${encodeURIComponent(trackId)}`, {
      method: 'PATCH',
      body: payload,
      headers: { 'If-Match': token },
    }),

  /** Simulation : ne touche aucun fichier (`HEAT-20`, décision **D4**). */
  preview: (trackId: string, payload: TrackPayload) =>
    request<TrackImpact>(`/api/heatmap/tracks/${encodeURIComponent(trackId)}/preview`, {
      method: 'POST',
      body: payload,
    }),

  remove: (trackId: string, token: string) =>
    request<undefined>(`/api/heatmap/tracks/${encodeURIComponent(trackId)}`, {
      method: 'DELETE',
      headers: { 'If-Match': token },
    }),

  reorder: (trackIds: string[]) =>
    request<Track[]>('/api/heatmap/tracks/order', {
      method: 'POST',
      body: { track_ids: trackIds },
    }),

  highlight: (trackId: string) =>
    request<TracksView>(`/api/heatmap/tracks/${encodeURIComponent(trackId)}/highlight`, {
      method: 'POST',
    }),

  neutralise: (payload: OffDayPayload) =>
    request<OffDay>('/api/heatmap/off-days', { method: 'POST', body: payload }),

  cancelNeutralisation: (offId: string, token: string) =>
    request<undefined>(`/api/heatmap/off-days/${encodeURIComponent(offId)}`, {
      method: 'DELETE',
      headers: { 'If-Match': token },
    }),
};
