/**
 * Grille d'assiduité (`L03-03`, spec `HEAT` v2).
 *
 * **Le composant ne décide rien.** Il reçoit du serveur, pour chaque jour, un état et un
 * niveau, et se contente de les peindre. Aucune règle de cadence, aucun seuil, aucun
 * calcul de série ne vit ici : `HEAT-30` l'interdit explicitement, et pour une bonne
 * raison — deux implémentations d'une fenêtre glissante divergent au premier cas limite.
 *
 * La conséquence visuelle qui compte : `off` et `missed` doivent être **immédiatement
 * distinguables**. Une piste « deux fois par semaine » est majoritairement `off`, et une
 * grille majoritairement grise ne doit pas se lire comme un échec.
 */

import { useMemo, useState } from 'react';

import { cx, cssVars } from '@/lib/cx';
import { longDate, monthAbbrev } from '@/lib/format';

import styles from './Heatmap.module.css';

/** États d'un jour, tels que le serveur les renvoie (`HEAT-05`, `HEAT-06`). */
export type DayState = 'off' | 'missed' | 'done' | 'bonus' | 'neutralised' | 'void';

export interface HeatDay {
  /** `AAAA-MM-JJ`, jour local (`HEAT-32`). */
  date: string;
  value: number;
  state: DayState;
  /** 0 à 4 (`HEAT-15`). Ignoré si l'état n'est pas validé. */
  level: number;
}

export type WeekStatus = 'reached' | 'partial' | 'missed';

export interface HeatWeek {
  /** Lundi de la semaine ISO. */
  start: string;
  status: WeekStatus;
  done: number;
  expected: number;
}

const STATE_CLASS: Record<DayState, string | undefined> = {
  off: styles.off,
  void: styles.void,
  missed: styles.missed,
  neutralised: styles.neutralised,
  done: undefined, // porté par le niveau
  bonus: undefined,
};

const LEVEL_CLASS = [undefined, styles.level1, styles.level2, styles.level3, styles.level4];

const WEEK_CLASS: Record<WeekStatus, string | undefined> = {
  reached: styles.weekReached,
  partial: styles.weekPartial,
  missed: styles.weekMissed,
};

const STATE_LABEL: Record<DayState, string> = {
  off: 'rien attendu',
  void: 'hors plage',
  missed: 'manqué',
  done: 'validé',
  bonus: 'bonus',
  neutralised: 'neutralisé',
};

function cellClass(day: HeatDay): string {
  if (day.state === 'done' || day.state === 'bonus') {
    const level = LEVEL_CLASS[Math.max(1, Math.min(4, day.level))];
    return cx(styles.cell, level, day.state === 'bonus' && styles.bonus);
  }
  return cx(styles.cell, STATE_CLASS[day.state]);
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
  weeks?: readonly HeatWeek[] | undefined;
  /** Couleur d'accent de la piste, en composantes RVB (`HEAT-20`). */
  accentRgb?: string | undefined;
  /** Unité affichée dans l'infobulle : « série », « ml », « km »… */
  unit?: string | undefined;
  label: string;
  onSelectDay?: ((day: HeatDay) => void) | undefined;
}

export function Heatmap({
  days,
  weeks,
  accentRgb = 'var(--signal-rgb)',
  unit,
  label,
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
                className={cellClass(day)}
                title={`${longDate(day.date)} — ${STATE_LABEL[day.state]}`}
                aria-label={`${longDate(day.date)}, ${STATE_LABEL[day.state]}`}
                disabled={day.state === 'void'}
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
              />
            )),
          )}
        </div>

        {weeks !== undefined && (
          <div className={styles.weekBar} role="list" aria-label={`Statut hebdomadaire — ${label}`}>
            {weeks.map((week) => (
              <span
                key={week.start}
                role="listitem"
                className={cx(styles.weekMark, WEEK_CLASS[week.status])}
                title={`Semaine du ${longDate(week.start)} — ${week.done}/${week.expected}`}
              />
            ))}
          </div>
        )}
      </div>

      {hovered && (
        <div className={styles.tip} style={{ left: hovered.x, top: hovered.y }} role="status">
          <div className={styles.tipDate}>{longDate(hovered.day.date)}</div>
          {hovered.day.state === 'off' || hovered.day.state === 'void' ? (
            STATE_LABEL[hovered.day.state]
          ) : (
            <>
              {hovered.day.value}
              {unit !== undefined && ` ${unit}`} · {STATE_LABEL[hovered.day.state]}
            </>
          )}
        </div>
      )}

      <div className={styles.legend}>
        <span>rien attendu</span>
        <i className={cx(styles.legendCell, styles.off)} />
        <span className={styles.legendSpacer} />
        <span>manqué</span>
        <i className={cx(styles.legendCell, styles.missed)} />
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
