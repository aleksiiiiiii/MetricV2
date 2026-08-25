/**
 * Champ de saisie avec suggestions filtrées — le nom d'un exercice, aujourd'hui.
 *
 * ── Pourquoi pas `<datalist>` ─────────────────────────────────────────────
 *
 * L'élément natif ferait dix lignes. Trois choses l'écartent, et la première suffit :
 *
 * * **iOS ne le rend pas.** Safari mobile l'ignore en pratique, et la cible d'usage du
 *   projet est un iPhone. Un composant qui ne s'affiche pas sur l'appareil visé n'est pas
 *   un composant.
 * * **Il ne complète pas au `Tab`.** C'est précisément le geste demandé, et aucune API ne
 *   permet de l'ajouter à un `datalist`.
 * * **Il n'est pas stylable**, donc ses lignes ne peuvent porter ni les 44 px de plancher
 *   ni la mention de ce que le nom exact apporte.
 *
 * ── Ce que le composant garantit ──────────────────────────────────────────
 *
 * * La liste se réduit **à chaque frappe**, sur un repli sans accent ni casse — « epaules »
 *   trouve « épaules », et on tape rarement ses accents entre deux séries.
 * * `Tab` écrit le premier résultat et passe au champ suivant. `Entrée` écrit le résultat
 *   surligné sans quitter le champ.
 * * Le champ **reste libre** : un nom hors liste s'écrit et s'enregistre. Ces suggestions
 *   ne sont pas une liste de valeurs autorisées — n'importe quel intitulé fait tourner une
 *   séance, il perd seulement son illustration.
 * * Chaque ligne est une cible de 44 px, et le clavier la parcourt aux flèches. Les deux
 *   portes existent, comme partout.
 *
 * ── Le motif ARIA ─────────────────────────────────────────────────────────
 *
 * `combobox` + `listbox`, avec `aria-activedescendant` plutôt qu'un focus déplacé : le
 * focus doit rester dans le champ pour que la frappe continue de filtrer.
 */

import { useId, useMemo, useRef, useState } from 'react';
import type { InputHTMLAttributes, KeyboardEvent } from 'react';

import { cx } from '@/lib/cx';

import styles from './Combobox.module.css';
import primitives from './primitives.module.css';

/**
 * Une suggestion.
 *
 * `hint` n'est **pas** affiché en toutes lettres : il devient une puce à droite, et le
 * texte part à la synthèse vocale. Le nom d'un exercice fait vingt caractères, et une
 * annotation écrite le tronquait sur un écran de 360 px.
 */
export interface Suggestion {
  value: string;
  hint?: string | undefined;
}

interface ComboboxProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'value' | 'onChange' | 'onSelect'
> {
  label: string;
  value: string;
  options: readonly Suggestion[];
  onChange: (value: string) => void;
  /** Appelé quand une suggestion est **choisie**, jamais à la frappe libre. */
  onSelect?: ((option: Suggestion) => void) | undefined;
  error?: string | undefined;
  hint?: string | undefined;
  /** Nombre maximal de lignes affichées. Au-delà, la liste cesse d'être un choix. */
  limit?: number;
}

/**
 * Repli d'une chaîne pour la comparaison : minuscules, sans accents ni ponctuation.
 *
 * **Il ne décide rien.** Il filtre une liste affichée ; c'est `app/core/text.py`, côté
 * serveur, qui décide si deux noms désignent le même exercice. Les deux se ressemblent et
 * c'est voulu — mais l'un range des pixels, l'autre fusionne un historique de charge.
 */
function fold(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function Combobox({
  label,
  value,
  options,
  onChange,
  onSelect,
  error,
  hint,
  limit = 8,
  className,
  id,
  ...rest
}: ComboboxProps) {
  const generated = useId();
  const fieldId = id ?? generated;
  const listId = `${fieldId}-liste`;
  const describedBy = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;

  const [open, setOpen] = useState(false);
  const [marked, setMarked] = useState(0);
  // Un appui sur une ligne fait perdre le focus au champ avant le clic. Sans ce drapeau,
  // `onBlur` refermerait la liste et le clic tomberait dans le vide — défaut classique,
  // et invisible à la souris sur un écran large.
  const picking = useRef(false);

  const shown = useMemo(() => {
    const needle = fold(value);
    const matching =
      needle === '' ? options : options.filter((option) => fold(option.value).includes(needle));
    return matching.slice(0, limit);
  }, [options, value, limit]);

  const first = shown[0];
  /*
   * Une seule correspondance **déjà écrite à l'identique** n'a plus rien à proposer.
   *
   * La comparaison est sur le texte brut et non sur le repli, et c'est un défaut trouvé au
   * test : avec le repli, taper « plank » masquait la suggestion « Plank » — donc empêchait
   * de corriger la casse. Or c'est exactement la casse qui décide de l'illustration dans
   * Cadence, et choisir la suggestion pré-remplit aussi le groupe musculaire.
   */
  const useful = first !== undefined && !(shown.length === 1 && first.value === value);
  const visible = open && useful;
  const active = shown[Math.min(marked, shown.length - 1)];

  function choose(option: Suggestion): void {
    onChange(option.value);
    onSelect?.(option);
    setOpen(false);
    setMarked(0);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (!visible || active === undefined || first === undefined) return;

    if (event.key === 'Tab') {
      // Le geste demandé : `Tab` écrit le premier résultat **et** passe au champ suivant.
      // On ne l'empêche donc pas — compléter sans avancer surprendrait plus que ça n'aide.
      choose(first);
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setMarked((current) => (current + 1) % shown.length);
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setMarked((current) => (current - 1 + shown.length) % shown.length);
      return;
    }
    if (event.key === 'Enter') {
      // `preventDefault` : sans lui, la touche enverrait le formulaire avec le texte
      // partiel — on enregistrerait « Push » au lieu de « Push-Ups Classic ».
      event.preventDefault();
      choose(active);
      return;
    }
    if (event.key === 'Escape') {
      setOpen(false);
    }
  }

  return (
    <div className={cx(primitives.field, styles.wrap, className)}>
      <label htmlFor={fieldId}>{label}</label>

      <input
        id={fieldId}
        className={cx(primitives.input, error && primitives.inputInvalid)}
        role="combobox"
        aria-expanded={visible}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          visible && active !== undefined ? `${listId}-${String(shown.indexOf(active))}` : undefined
        }
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        autoComplete="off"
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
          setMarked(0);
        }}
        onFocus={() => {
          setOpen(true);
        }}
        onBlur={() => {
          if (!picking.current) setOpen(false);
        }}
        onKeyDown={onKeyDown}
        {...rest}
      />

      {visible && (
        <ul
          className={styles.list}
          id={listId}
          role="listbox"
          aria-label={`Suggestions — ${label}`}
        >
          {shown.map((option, index) => (
            <li key={option.value} role="presentation">
              <button
                type="button"
                id={`${listId}-${String(index)}`}
                role="option"
                aria-selected={option === active}
                className={cx(styles.option, option === active && styles.optionOn)}
                // `onMouseDown` et non `onClick` : il précède le `blur`, ce qui évite la
                // course où la liste se referme avant que le clic arrive.
                onMouseDown={() => {
                  picking.current = true;
                }}
                onClick={() => {
                  picking.current = false;
                  choose(option);
                }}
              >
                <span className={styles.optionName}>{option.value}</span>
                {/* Une puce et non le mot, et c'est une correction de capture : à 360 px,
                    « ILLUSTRATION » prenait la moitié de la ligne et tronquait « Push-Ups
                    Cla… ». Le nom est ce qu'on lit pour choisir ; l'annotation ne doit pas
                    lui prendre sa place. Le texte reste pour la synthèse vocale, et le
                    `hint` du champ dit ce que la puce signifie. */}
                {option.hint !== undefined && (
                  <>
                    <span className={styles.optionMark} aria-hidden="true" />
                    <span className="sr-only">{option.hint}</span>
                  </>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      {error !== undefined && (
        <span className={primitives.fieldError} id={`${fieldId}-error`} role="alert">
          {error}
        </span>
      )}
      {error === undefined && hint !== undefined && (
        <span className={primitives.fieldHint} id={`${fieldId}-hint`}>
          {hint}
        </span>
      )}
    </div>
  );
}
