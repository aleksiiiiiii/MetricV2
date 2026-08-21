/**
 * Composants de données (`L03-02`).
 *
 * Ils affichent des valeurs déjà calculées. Aucun ne dérive, ne moyenne ni ne compare :
 * les agrégats viennent du serveur (`AGG-01`, `HEAT-30`). Un composant qui recalculerait
 * finirait par diverger du backend au premier cas limite.
 */

import type { ReactNode } from 'react';

import { cx } from '@/lib/cx';
import { integer, num, percent } from '@/lib/format';

import type { Tone } from './primitives';
import styles from './data.module.css';

const TONE_VAR: Record<Tone, string> = {
  signal: 'var(--signal)',
  effort: 'var(--effort)',
  load: 'var(--load)',
  recover: 'var(--recover)',
};

// ── Sparkline ─────────────────────────────────────────

/**
 * Courbe minuscule sous un chiffre clé. Sans axe ni graduation : elle donne une
 * direction, pas une valeur — la valeur est juste au-dessus, en grand.
 */
export function Sparkline({
  values,
  tone = 'signal',
  label,
}: {
  values: readonly number[];
  tone?: Tone | undefined;
  label?: string | undefined;
}) {
  if (values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = 120 / (values.length - 1);

  const points = values
    .map(
      (value, index) =>
        `${(index * step).toFixed(1)},${(30 - ((value - min) / span) * 26).toFixed(1)}`,
    )
    .join(' ');

  return (
    <svg
      className={styles.spark}
      viewBox="0 0 120 34"
      preserveAspectRatio="none"
      role={label ? 'img' : 'presentation'}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <polyline points={points} fill="none" stroke={TONE_VAR[tone]} strokeWidth="1.5" />
    </svg>
  );
}

// ── Chiffre clé ───────────────────────────────────────

export function Stat({
  label,
  value,
  unit,
  detail,
  direction,
  spark,
  sparkTone = 'signal',
  compact = false,
}: {
  label: string;
  value: ReactNode;
  unit?: string | undefined;
  detail?: ReactNode | undefined;
  /** Colore le commentaire : une progression n'est pas toujours une bonne nouvelle. */
  direction?: 'up' | 'down' | undefined;
  spark?: readonly number[] | undefined;
  sparkTone?: Tone | undefined;
  /**
   * Deux tuiles côte à côte sur un téléphone.
   *
   * Le chiffre descend de `--t-num-xl` à 28 px — assez pour rester ce qu'on lit en
   * premier, assez peu pour que « 82,4 kg » ne déborde pas d'une demi-largeur d'écran.
   * Rien d'autre ne change : ce n'est pas un composant réduit, c'est le même dans une
   * colonne plus étroite.
   */
  compact?: boolean | undefined;
}) {
  return (
    <>
      <div className={styles.statKey}>{label}</div>
      <div className={cx(styles.statValue, compact && styles.statValueCompact)}>
        {value}
        {unit !== undefined && <small className={styles.statUnit}>{unit}</small>}
      </div>
      {detail !== undefined && (
        <div className={cx(styles.statDelta, direction && styles[direction])}>{detail}</div>
      )}
      {spark !== undefined && <Sparkline values={spark} tone={sparkTone} />}
    </>
  );
}

/**
 * Une largeur CSS, et non un pourcentage à lire.
 *
 * **Les deux ne s'écrivent pas pareil, et la confusion coûtait cher.** `percent()` rend
 * « 56 % » — l'espace avant le signe est la typographie française, et c'est ce qu'il faut
 * dans une phrase ou un `aria-label`. Posé en `style.width`, c'est une valeur **invalide**
 * que le navigateur jette sans rien dire : la jauge retombait alors sur sa largeur par
 * défaut, c'est-à-dire **pleine**. Toutes les barres de l'application, `Progress` comme
 * `Bars`, se peignaient donc à 100 % quelle que soit leur valeur — y compris une semaine
 * à zéro, qui s'affichait comme une semaine complète.
 *
 * Trouvé en mesurant la page, jamais par un test : le DOM porte bien un `<div>` de barre,
 * il lui manquait seulement un attribut, et aucune assertion ne regardait sa largeur.
 */
function width(ratio: number): string {
  // Arrondi au centième de point : `0,56 × 100` vaut `56.00000000000001` en virgule
  // flottante, et une largeur à quinze décimales dans le DOM ne rend service à personne.
  const clamped = Math.max(0, Math.min(1, ratio));
  return `${String(Math.round(clamped * 10000) / 100)}%`;
}

// ── Barres ────────────────────────────────────────────

export interface BarRow {
  label: string;
  /** Part de la barre, entre 0 et 1. */
  ratio: number;
  value: ReactNode;
  tone?: Tone | undefined;
}

/**
 * Barres horizontales comparatives. Le libellé est à gauche et la valeur à droite, en
 * chasse fixe : les colonnes s'alignent seules et l'œil compare sans effort.
 */
export function Bars({ rows }: { rows: readonly BarRow[] }) {
  return (
    <div className={styles.bars}>
      {rows.map((row) => (
        <div className={styles.barRow} key={row.label}>
          {/* Le libellé est tronqué plutôt que de repousser la barre : sur un téléphone,
              c'est la barre qui porte l'information, le mot ne fait que la nommer. Le
              titre complet reste lisible au survol et à la synthèse vocale. */}
          <span className={styles.barLabel} title={row.label}>
            {row.label}
          </span>
          <div className={styles.track}>
            <div
              className={styles.fill}
              style={{
                width: width(row.ratio),
                background: TONE_VAR[row.tone ?? 'signal'],
              }}
            />
          </div>
          <span className={styles.barValue}>{row.value}</span>
        </div>
      ))}
    </div>
  );
}

/** Barre de progression simple, avec son compte. */
export function Progress({
  done,
  total,
  tone,
}: {
  done: number;
  total: number;
  /** Par défaut le ton suit l'avancement : charge, signal, puis effort. */
  tone?: Tone | undefined;
}) {
  const ratio = total > 0 ? done / total : 0;
  const automatic: Tone = ratio >= 1 ? 'effort' : ratio >= 0.5 ? 'signal' : 'load';

  return (
    <div className={styles.progress}>
      <div className={styles.track}>
        <div
          className={styles.fill}
          style={{ width: width(ratio), background: TONE_VAR[tone ?? automatic] }}
        />
      </div>
      <span className={styles.progressCount}>
        {integer(done)} / {integer(total)}
      </span>
    </div>
  );
}

// ── Anneau ────────────────────────────────────────────

const RING_RADIUS = 35;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

/**
 * Anneau de progression.
 *
 * **`ratio: null` n'est pas `ratio: 0`.** Un anneau dessine un pourcentage — c'est ce
 * qu'il sait faire —, et c'est exactement par là que l'invariant « aucune valeur
 * inventée » s'est cassé au lot L14 : l'écran passait une donnée absente, choisissait de
 * ne pas colorer, et le composant écrivait quand même « 0 % » en son centre. Quatre
 * décisions correctes, une page qui ment.
 *
 * Le cas est donc dans le type, pas dans la discipline de l'appelant : sans valeur,
 * l'anneau reste vide et affiche un tiret. Il n'y a plus de façon de se tromper.
 */
export function Ring({
  ratio,
  label,
  detail,
  tone = 'effort',
}: {
  ratio: number | null;
  label: ReactNode;
  detail?: ReactNode | undefined;
  tone?: Tone | undefined;
}) {
  const clamped = ratio === null ? 0 : Math.max(0, Math.min(1, ratio));

  return (
    <div className={styles.ring}>
      <svg
        width="86"
        height="86"
        viewBox="0 0 86 86"
        role="img"
        aria-label={ratio === null ? 'aucune donnée' : percent(clamped)}
      >
        <circle
          cx="43"
          cy="43"
          r={RING_RADIUS}
          fill="none"
          stroke="var(--surface-2)"
          strokeWidth="8"
        />
        {/* Sans valeur, aucun arc n'est tracé : la piste vide dit ce qu'il y a à dire. */}
        {ratio !== null && (
          <circle
            cx="43"
            cy="43"
            r={RING_RADIUS}
            fill="none"
            stroke={TONE_VAR[tone]}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={RING_CIRCUMFERENCE}
            strokeDashoffset={RING_CIRCUMFERENCE * (1 - clamped)}
            transform="rotate(-90 43 43)"
          />
        )}
        <text
          x="43"
          y="48"
          textAnchor="middle"
          fill="var(--ink)"
          fontFamily="JetBrains Mono, monospace"
          fontSize="18"
        >
          {ratio === null ? '—' : `${num(clamped * 100, 0)}%`}
        </text>
      </svg>
      <div className={styles.ringLabel}>
        {label}
        {detail !== undefined && (
          <>
            <br />
            <span className={styles.ringSub}>{detail}</span>
          </>
        )}
      </div>
    </div>
  );
}

// ── Tableau ───────────────────────────────────────────

export interface Column<Row> {
  key: string;
  header: string;
  /** Chiffres à chasse fixe, alignés à droite. */
  numeric?: boolean | undefined;
  render: (row: Row) => ReactNode;
}

export function Table<Row>({
  columns,
  rows,
  rowKey,
  caption,
}: {
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row, index: number) => string;
  caption?: string | undefined;
}) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        {caption !== undefined && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} className={cx(column.numeric && styles.alignRight)}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)}>
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cx(
                    column.numeric && styles.cellNum,
                    column.numeric && styles.alignRight,
                  )}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Checklist ─────────────────────────────────────────

/** Groupe d'items, titré par un moment de la journée (`SUP-01`). */
export function CheckGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className={styles.group}>
      <div className={styles.groupHead}>
        <span className="eyebrow">{title}</span>
        <hr />
      </div>
      {children}
    </div>
  );
}

/**
 * Item cochable. La bascule est appliquée localement avant la réponse du serveur et
 * annulée en cas d'échec (`SUP-04`) : c'est au parent de gérer l'optimisme, ce composant
 * ne fait qu'afficher l'état qu'on lui donne.
 */
export function Check({
  label,
  dose,
  streak,
  checked,
  busy = false,
  onToggle,
}: {
  label: string;
  dose?: string | undefined;
  streak?: string | undefined;
  checked: boolean;
  busy?: boolean | undefined;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={cx(styles.check, checked && styles.checked)}
      aria-pressed={checked}
      disabled={busy}
      onClick={onToggle}
    >
      <span className={styles.box} />
      <span className={styles.checkText}>
        {label}
        {dose !== undefined && <span className={styles.dose}>{dose}</span>}
      </span>
      <span className={styles.streak}>{streak ?? '—'}</span>
    </button>
  );
}
