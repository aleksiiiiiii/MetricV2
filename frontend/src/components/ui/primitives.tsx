/**
 * Primitives de la charte (`L03-01`).
 *
 * Reprise fidèle de `GuidelinesUI.html`. Aucune de ces valeurs n'est décidée ici : les
 * couleurs, rayons et graisses viennent des tokens. Si un écran a besoin d'une variante,
 * elle s'ajoute ici — jamais en style inline dans l'écran.
 */

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react';
import { useId } from 'react';

import { cx } from '@/lib/cx';

import styles from './primitives.module.css';

// ── Surtitre et règle graduée ─────────────────────────

export function Eyebrow({
  children,
  className,
}: {
  children: ReactNode;
  className?: string | undefined;
}) {
  return <p className={cx('eyebrow', className)}>{children}</p>;
}

/** Règle graduée : le motif signature de la charte, avec son étiquette de section. */
export function Rule({ children }: { children?: ReactNode }) {
  return <div className="rule">{children !== undefined && <span>{children}</span>}</div>;
}

// ── Boutons ───────────────────────────────────────────

export type ButtonVariant = 'primary' | 'ghost' | 'quiet';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant | undefined;
  /** Affiche l'attente sans changer la largeur du bouton. */
  busy?: boolean | undefined;
}

export function Button({
  variant = 'ghost',
  busy = false,
  className,
  disabled,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      className={cx(styles.btn, styles[variant], busy && styles.btnBusy, className)}
      disabled={disabled ?? busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {children}
    </button>
  );
}

/**
 * Bouton de saisie rapide : libellé à gauche, dernière valeur connue à droite.
 *
 * C'est la cible du projet — un relevé en un geste. Le rappel de la dernière valeur
 * évite d'aller consulter l'historique pour choisir sa charge (`ACT-08`).
 */
export function LogButton({
  label,
  hint,
  className,
  ...rest
}: { label: ReactNode; hint?: ReactNode | undefined } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" className={cx(styles.btn, styles.log, className)} {...rest}>
      <span>{label}</span>
      {hint !== undefined && <em className={styles.logHint}>{hint}</em>}
    </button>
  );
}

// ── Carte ─────────────────────────────────────────────

export function Card({
  children,
  className,
  flush = false,
}: {
  children: ReactNode;
  className?: string | undefined;
  /** Pour une carte contenant un tableau bord à bord. */
  flush?: boolean | undefined;
}) {
  return <div className={cx(styles.card, flush && styles.cardFlush, className)}>{children}</div>;
}

/** En-tête de carte : titre à gauche, indicateur à droite. */
export function CardHead({ children }: { children: ReactNode }) {
  return <div className="spread">{children}</div>;
}

// ── Badge ─────────────────────────────────────────────

/**
 * Les quatre signaux portent un sens fixe : mesure, série tenue, seuil approché, dette.
 * Le nom du ton est donc sémantique et non décoratif.
 */
export type Tone = 'signal' | 'effort' | 'load' | 'recover';

export function Badge({
  tone = 'signal',
  mono = false,
  children,
  className,
}: {
  tone?: Tone | undefined;
  /** Chiffres à chasse fixe, pour un badge qui porte une valeur. */
  mono?: boolean | undefined;
  children: ReactNode;
  className?: string | undefined;
}) {
  return (
    <span className={cx(styles.badge, styles[tone], mono && 'num', className)}>{children}</span>
  );
}

// ── Champ ─────────────────────────────────────────────

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  /** Message d'erreur par champ, tel que renvoyé par l'API (`API-06`). */
  error?: string | undefined;
  hint?: string | undefined;
}

export function Field({ label, error, hint, className, id, ...rest }: FieldProps) {
  const generated = useId();
  const fieldId = id ?? generated;
  const describedBy = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;

  return (
    <div className={cx(styles.field, className)}>
      <label htmlFor={fieldId}>{label}</label>
      <input
        id={fieldId}
        className={cx(styles.input, error && styles.inputInvalid)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...rest}
      />
      {error !== undefined && (
        <span className={styles.fieldError} id={`${fieldId}-error`} role="alert">
          {error}
        </span>
      )}
      {error === undefined && hint !== undefined && (
        <span className={styles.fieldHint} id={`${fieldId}-hint`}>
          {hint}
        </span>
      )}
    </div>
  );
}

// ── Sélecteur segmenté ────────────────────────────────

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className={styles.seg} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => {
            onChange(option.value);
          }}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// ── État vide ─────────────────────────────────────────

/**
 * Un état vide n'est pas une erreur : il dit ce que coûte le prochain geste.
 * « Deux chiffres suffisent pour que la journée compte. »
 */
export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode | undefined;
  action?: ReactNode | undefined;
}) {
  return (
    <div className={styles.empty}>
      <p className="eyebrow">{title}</p>
      {children !== undefined && <p>{children}</p>}
      {action}
    </div>
  );
}

// ── Bloc IA ───────────────────────────────────────────

/**
 * Lecture assistée. Le fond dégradé le distingue d'une donnée relevée : ce qui est écrit
 * là est une interprétation, pas une mesure (`NUT-04`, `IA-08`).
 */
export function AiBlock({
  tag,
  children,
  actions,
}: {
  tag: string;
  children: ReactNode;
  actions?: ReactNode | undefined;
}) {
  return (
    <div className={styles.ai}>
      <div className={styles.aiTag}>
        <span className={styles.aiDot} />
        <span className="eyebrow">{tag}</span>
      </div>
      {children}
      {actions !== undefined && (
        <div className="row" style={{ marginTop: 16 }}>
          {actions}
        </div>
      )}
    </div>
  );
}
