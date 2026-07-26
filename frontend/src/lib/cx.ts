/**
 * Composition de classes et de variables CSS.
 *
 * Vite type les CSS Modules par une signature d'index ; combiné à
 * `noUncheckedIndexedAccess`, `styles.foo` vaut donc `string | undefined`. Concaténer
 * ces valeurs à la main produirait des `undefined` dans le DOM et du bruit de lint sur
 * chaque composant. `cx` absorbe le problème une fois pour toutes — et sert de toute
 * façon aux classes conditionnelles.
 */

import type { CSSProperties } from 'react';

export type ClassValue = string | false | null | undefined;

/** Assemble des classes en ignorant tout ce qui est absent ou faux. */
export function cx(...values: ClassValue[]): string {
  return values.filter((v): v is string => typeof v === 'string' && v.length > 0).join(' ');
}

/**
 * Style inline portant des variables CSS personnalisées.
 *
 * React accepte les propriétés `--*` à l'exécution mais `CSSProperties` ne les décrit
 * pas. C'est le seul endroit du projet où l'on force le type, plutôt qu'un `as` répété
 * à chaque appel — utile dès qu'une piste impose sa couleur d'accent (`L11-12`).
 */
export function cssVars(
  vars: Record<`--${string}`, string | number>,
  base?: CSSProperties,
): CSSProperties {
  return { ...base, ...vars };
}
