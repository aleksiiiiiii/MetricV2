/**
 * Grille d'assiduité (`L03-03`, `L11-06`, spec `HEAT` v2).
 *
 * **Le composant ne décide rien.** Il reçoit du serveur, pour chaque jour, un état et un
 * niveau, et se contente de les peindre. Aucune règle de cadence, aucun seuil, aucun
 * calcul de série ne vit ici : `HEAT-30` l'interdit explicitement, et pour une bonne
 * raison — deux implémentations d'une fenêtre glissante divergent au premier cas limite.
 *
 * ## La contrainte qui décide de tout le reste
 *
 * `off` et `missed` doivent être **immédiatement distinguables**. Une piste « deux fois
 * par semaine » est majoritairement `off` ; si sa grille se lit comme un échec, tout le
 * travail du moteur est annulé à l'affichage.
 *
 * ## Deux pièges de rendu, repérés au lot L10
 *
 * **Les jours à venir sont `off`, et se peignent comme les autres `off`.** La plage par
 * défaut va jusqu'au dimanche de la semaine en cours : les cellules après aujourd'hui
 * existent. En faire des trous donnerait à chaque grille une entaille hebdomadaire qui
 * ne veut rien dire.
 *
 * **Ce qui précède la création d'une piste, en revanche, est un trou.** Là il n'y avait
 * rien à tenir (`HEAT-07`), et une cellule pleine y raconterait une histoire qui n'a pas
 * eu lieu.
 *
 * **Une piste `per_week` ne rend jamais de jour `missed`** (`HEAT-11`) : son rouge se
 * pose sur la bande hebdomadaire, sous la grille. Un écran qui chercherait des jours
 * rouges y verrait un sans-faute permanent.
 */

import { useMemo, useState } from 'react';

import { cx, cssVars } from '@/lib/cx';
import { longDate, monthAbbrev, num } from '@/lib/format';

import styles from './Heatmap.module.css';

/** Les quatre états du serveur (`HEAT-05`). */
export type DayState = 'off' | 'missed' | 'done' | 'bonus';

/** Nuance d'affichage d'un `off`. Ne décide jamais si le jour compte. */
export type DayReason = 'neutralised' | 'before_track' | 'future' | 'pending';

export interface HeatDay {
  /** `AAAA-MM-JJ`, jour local (`HEAT-32`). */
  date: string;
  value: number;
  state: DayState;
  /** 0 à 4 (`HEAT-15`). Ignoré si l'état n'est pas validé. */
  level: number;
  reason?: DayReason | null | undefined;
}

export type WeekStatus = 'reached' | 'partial' | 'missed' | 'off';

export interface HeatWeek {
  /** Lundi de la semaine ISO. */
  start: string;
  status: WeekStatus;
  done: number;
  expected: number;
}

const LEVEL_CLASS = [undefined, styles.level1, styles.level2, styles.level3, styles.level4];

const WEEK_CLASS: Record<WeekStatus, string | undefined> = {
  reached: styles.weekReached,
  partial: styles.weekPartial,
  missed: styles.weekMissed,
  // Semaine antérieure à la piste, neutralisée ou pas encore arrivée : elle n'a rien à
  // dire, et lui donner une couleur serait lui faire dire quelque chose.
  off: undefined,
};

const STATE_LABEL: Record<DayState, string> = {
  off: 'rien attendu',
  missed: 'manqué',
  done: 'validé',
  bonus: 'bonus',
};

/**
 * Ce que dit l'infobulle d'un jour `off`.
 *
 * Les libellés viennent du serveur par leur clé, pas par leur texte : c'est la même règle
 * que pour les codes d'erreur (`API-07`).
 */
const REASON_LABEL: Record<DayReason, string> = {
  neutralised: 'neutralisé',
  before_track: 'avant la création de la piste',
  future: 'à venir',
  pending: 'journée en cours',
};

function cellClass(day: HeatDay, isToday: boolean): string {
  const marker = isToday && styles.today;

  if (day.state === 'done' || day.state === 'bonus') {
    const level = LEVEL_CLASS[Math.max(1, Math.min(4, day.level))];
    return cx(styles.cell, level, day.state === 'bonus' && styles.bonus, marker);
  }
  if (day.state === 'missed') return cx(styles.cell, styles.missed, marker);

  // `off` — et c'est là que la nuance sert.
  if (day.reason === 'neutralised') return cx(styles.cell, styles.neutralised, marker);
  if (day.reason === 'before_track') return cx(styles.cell, styles.void);
  return cx(styles.cell, styles.off, marker);
}

function describe(day: HeatDay, unit: string | undefined): string {
  if (day.state === 'off') {
    const why = day.reason ? REASON_LABEL[day.reason] : STATE_LABEL.off;
    return day.value > 0 ? `${num(day.value)}${unit ? ` ${unit}` : ''} · ${why}` : why;
  }
  const value = day.value > 0 ? `${num(day.value)}${unit ? ` ${unit}` : ''} · ` : '';
  return `${value}${STATE_LABEL[day.state]}`;
}

/** Découpe la suite de jours en colonnes de 7, la grille se remplissant de haut en bas. */
function toColumns(days: readonly HeatDay[]): HeatDay[][] {
  const columns: HeatDay[][] = [];
  for (let index = 0; index < days.length; index += 7) {
    columns.push(days.slice(index, index + 7));
  }
  return columns;
}

/** Étiquettes de mois, posées sur la colonne où le mois commence. */
function monthLabels(columns: readonly HeatDay[][]): (string | null)[] {
  let previous = '';
  return columns.map((column) => {
    const first = column[0];
    if (!first) return null;
    const label = monthAbbrev(first.date);
    if (label === previous) return null;
    previous = label;
    return label;
  });
}

export interface HeatmapProps {
  days: readonly HeatDay[];
  /** Renseigné pour une piste `per_week` : c'est la semaine qui porte le statut. */
  weeks?: readonly HeatWeek[] | null | undefined;
  /** Couleur d'accent de la piste, en composantes RVB. */
  accentRgb?: string | undefined;
  /** Unité affichée dans l'infobulle : « série », « ml », « km »… */
  unit?: string | undefined;
  label: string;
  /** `AAAA-MM-JJ` du jour courant, pour repérer la cellule d'aujourd'hui. */
  today?: string | undefined;
  onSelectDay?: ((day: HeatDay) => void) | undefined;
}

export function Heatmap({
  days,
  weeks,
  accentRgb = 'var(--signal-rgb)',
  unit,
  label,
  today,
  onSelectDay,
}: HeatmapProps) {
  const [hovered, setHovered] = useState<{ day: HeatDay; x: number; y: number } | null>(null);

  const columns = useMemo(() => toColumns(days), [days]);
  const months = useMemo(() => monthLabels(columns), [columns]);

  return (
    <div className={styles.wrap} style={cssVars({ '--accent-rgb': accentRgb })}>
      <div className={styles.scroll}>
        <div
          className={styles.months}
          style={{
            gridTemplateColumns: `repeat(${columns.length}, calc(var(--heat-cell) + var(--heat-gap)))`,
          }}
          aria-hidden="true"
        >
          {months.map((month, index) => (
            <span className={styles.month} key={index}>
              {month}
            </span>
          ))}
        </div>

        <div className={styles.grid} role="grid" aria-label={label}>
          {columns.map((column, columnIndex) =>
            column.map((day) => (
              <button
                key={day.date}
                type="button"
                className={cellClass(day, day.date === today)}
                title={`${longDate(day.date)} — ${describe(day, unit)}`}
                aria-label={`${longDate(day.date)}, ${describe(day, unit)}`}
                // Avant l'existence de la piste il n'y a rien à ouvrir, et après
                // aujourd'hui rien ne s'est encore produit.
                disabled={day.reason === 'before_track' || day.reason === 'future'}
                onClick={() => onSelectDay?.(day)}
                onMouseEnter={(event) => {
                  const cell = event.currentTarget.getBoundingClientRect();
                  const host = event.currentTarget
                    .closest(`.${styles.wrap}`)
                    ?.getBoundingClientRect();
                  if (!host) return;
                  setHovered({
                    day,
                    x: cell.left - host.left + cell.width / 2,
                    y: cell.top - host.top,
                  });
                }}
                onMouseLeave={() => {
                  setHovered(null);
                }}
                data-column={columnIndex}
                data-state={day.state}
                data-reason={day.reason ?? undefined}
              />
            )),
          )}
        </div>

        {weeks != null && (
          <div className={styles.weekBar} role="list" aria-label={`Statut hebdomadaire — ${label}`}>
            {weeks.map((week) => (
              <span
                key={week.start}
                role="listitem"
                className={cx(styles.weekMark, WEEK_CLASS[week.status])}
                data-status={week.status}
                title={`Semaine du ${longDate(week.start)} — ${week.done}/${week.expected}`}
              />
            ))}
          </div>
        )}
      </div>

      {hovered && (
        <div className={styles.tip} style={{ left: hovered.x, top: hovered.y }} role="status">
          <div className={styles.tipDate}>{longDate(hovered.day.date)}</div>
          {describe(hovered.day, unit)}
        </div>
      )}

      <div className={styles.legend}>
        <span>rien attendu</span>
        <i className={cx(styles.legendCell, styles.off)} />
        <span className={styles.legendSpacer} />
        <span>manqué</span>
        <i className={cx(styles.legendCell, styles.missed)} />
        <span className={styles.legendSpacer} />
        <span>neutralisé</span>
        <i className={cx(styles.legendCell, styles.neutralised)} />
        <span className={styles.legendSpacer} />
        <span>validé</span>
        <i className={cx(styles.legendCell, styles.level1)} />
        <i className={cx(styles.legendCell, styles.level2)} />
        <i className={cx(styles.legendCell, styles.level3)} />
        <i className={cx(styles.legendCell, styles.level4)} />
      </div>
    </div>
  );
}
