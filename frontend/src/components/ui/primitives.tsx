/**
 * Primitives de la charte (`L03-01`).
 *
 * Reprise fidèle de `GuidelinesUI.html`. Aucune de ces valeurs n'est décidée ici : les
 * couleurs, rayons et graisses viennent des tokens. Si un écran a besoin d'une variante,
 * elle s'ajoute ici — jamais en style inline dans l'écran.
 */

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react';
import { useId, useState } from 'react';

import { cx } from '@/lib/cx';
import { useHorizontalSwipe } from '@/lib/swipe';

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

// ── Pas-à-pas ─────────────────────────────────────────

/**
 * Ne lit que le format que le pas-à-pas écrit lui-même.
 *
 * **Ce n'est pas un second analyseur de saisie.** `8,40`, `5mi`, `44:12`, `1h30` restent
 * l'affaire du serveur (`ACT-01`) : les reconnaître ici reviendrait à entretenir deux
 * grammaires qui divergeraient au premier cas limite. Sur tout ce qu'il ne reconnaît pas,
 * le pas-à-pas se désactive et laisse le champ libre — l'utilisateur tape, le serveur
 * tranche.
 */
function readOwn(value: string): number | null {
  const trimmed = value.trim();
  if (!/^-?\d+(?:[.,]\d+)?$/.test(trimmed)) return null;
  const parsed = Number(trimmed.replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : null;
}

function writeOwn(value: number): string {
  // Deux décimales suffisent : on incrémente des kilos, pas des microgrammes. L'arrondi
  // évite que 82,5 + 2,5 s'écrive « 85.00000000000001 ».
  return String(Math.round(value * 100) / 100).replace('.', ',');
}

/**
 * Champ numérique flanqué de deux grosses cibles (`L17-07`).
 *
 * C'est le contrôle de saisie du projet sur mobile : entre deux séries, on ajuste une
 * charge d'un pouce, sans ouvrir un clavier qui masque la moitié de l'écran. Le champ
 * reste saisissable au clavier — le pas-à-pas est un raccourci, jamais la seule porte.
 */
export function Stepper({
  label,
  value,
  onChange,
  step = 1,
  min,
  max,
  error,
  hint,
  placeholder,
  inputMode = 'decimal',
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  step?: number | undefined;
  min?: number | undefined;
  max?: number | undefined;
  error?: string | undefined;
  hint?: ReactNode | undefined;
  placeholder?: string | undefined;
  inputMode?: 'decimal' | 'numeric' | undefined;
}) {
  const fieldId = useId();
  const current = readOwn(value);

  function nudge(direction: 1 | -1): void {
    // Champ vide : le premier appui pose le plancher plutôt que de ne rien faire.
    const base = current ?? min ?? 0;
    let next = current === null ? base : base + direction * step;
    if (min !== undefined) next = Math.max(min, next);
    if (max !== undefined) next = Math.min(max, next);
    onChange(writeOwn(next));
  }

  const atMin = current !== null && min !== undefined && current <= min;
  const atMax = current !== null && max !== undefined && current >= max;

  return (
    <div className={styles.stepper}>
      <label htmlFor={fieldId}>{label}</label>
      <div className={styles.stepperRow}>
        <button
          type="button"
          className={styles.stepperKey}
          aria-label={`${label} : diminuer`}
          disabled={atMin}
          onClick={() => {
            nudge(-1);
          }}
        >
          −
        </button>
        <input
          id={fieldId}
          className={cx(styles.stepperInput, error !== undefined && styles.inputInvalid)}
          inputMode={inputMode}
          value={value}
          placeholder={placeholder}
          aria-invalid={error !== undefined ? true : undefined}
          aria-describedby={error !== undefined ? `${fieldId}-error` : undefined}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
        <button
          type="button"
          className={styles.stepperKey}
          aria-label={`${label} : augmenter`}
          disabled={atMax}
          onClick={() => {
            nudge(1);
          }}
        >
          +
        </button>
      </div>
      {error !== undefined && (
        <span className={styles.fieldError} id={`${fieldId}-error`} role="alert">
          {error}
        </span>
      )}
      {error === undefined && hint !== undefined && (
        <span className={styles.stepperHint}>{hint}</span>
      )}
    </div>
  );
}

// ── Pastilles ─────────────────────────────────────────

/** Choix en un appui. `aria-pressed` porte l'état — la couleur seule ne le dirait pas. */
export function Chip({
  selected = false,
  className,
  children,
  ...rest
}: { selected?: boolean | undefined } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={cx(styles.chip, selected && styles.chipOn, className)}
      {...rest}
    >
      {children}
    </button>
  );
}

/**
 * Bande de pastilles qu'on fait défiler au doigt, avec accroche.
 *
 * Préférée à une liste déroulante native quand le choix est court et fréquent : la liste
 * native cache ses options derrière un appui et un panneau système, la bande les montre
 * toutes et se parcourt d'un pouce.
 */
export function ChipStrip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.strip} role="group" aria-label={label}>
      {children}
    </div>
  );
}

// ── Ligne à glisser ───────────────────────────────────

/**
 * Ligne de liste dont un glissement vers la gauche découvre une action destructrice.
 *
 * **L'action existe toujours dans le document**, révélée par le geste au doigt et
 * affichée d'emblée là où il y a un pointeur fin. Un geste ne doit jamais être la seule
 * façon d'atteindre une commande : il s'apprend en le découvrant, or on ne découvre pas
 * ce qu'on ne voit pas.
 *
 * **Deux appuis pour détruire.** Le premier arme, le second exécute. Un glissement part
 * tout seul dans une poche ou en faisant défiler une liste, et le projet n'a pas
 * d'annulation : ce qui est supprimé l'est.
 */
export function SwipeRow({
  actionLabel,
  confirmLabel = 'Confirmer ?',
  onAction,
  busy = false,
  children,
}: {
  /** Nom accessible de l'action — il doit désigner *quelle* ligne, pas seulement quoi faire. */
  actionLabel: string;
  confirmLabel?: string | undefined;
  onAction: () => void;
  busy?: boolean | undefined;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [armed, setArmed] = useState(false);

  function close(): void {
    setOpen(false);
    setArmed(false);
  }

  const swipe = useHorizontalSwipe({
    track: true,
    touchOnly: true,
    onLeft: () => {
      setOpen(true);
    },
    onRight: close,
  });

  // Le suivi du doigt ne va que vers la gauche, et pas au-delà du panneau : tirer une
  // ligne vers la droite dans le vide donnerait l'impression d'un geste possible.
  const shift = Math.max(-96, Math.min(0, open ? -96 + swipe.offset : swipe.offset));

  return (
    <div className={cx(styles.swipeRow, open && styles.swipeRowOpen)}>
      <div
        className={styles.swipeContent}
        style={{ transform: `translateX(${String(shift)}px)` }}
        {...swipe.handlers}
      >
        {children}
      </div>

      <div className={styles.swipeAction}>
        <button
          type="button"
          className={cx(styles.swipeKey, armed && styles.swipeKeyArmed)}
          aria-label={armed ? `${actionLabel} — confirmer` : actionLabel}
          disabled={busy}
          onClick={() => {
            if (!armed) {
              setArmed(true);
              return;
            }
            close();
            onAction();
          }}
        >
          {armed ? confirmLabel : 'supprimer'}
        </button>
      </div>
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
