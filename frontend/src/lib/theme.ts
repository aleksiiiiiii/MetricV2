/**
 * Le thème, côté client.
 *
 * Trois modes, deux thèmes. `system` suit la préférence de l'appareil et en change avec
 * elle ; `light` et `dark` sont un choix explicite, qui l'emporte et qui persiste.
 *
 * **Un seul endroit résout le mode en thème** — ici. La feuille de style ne consulte pas
 * `prefers-color-scheme` : elle ne connaît qu'un attribut `data-theme` sur `<html>`, posé
 * avant la première peinture par le script en tête d'`index.html`, puis tenu par
 * `ThemeProvider`. Deux résolutions, en CSS et en JavaScript, donneraient deux réponses
 * le jour où l'une des deux changerait.
 *
 * Le contexte et le hook vivent ici, séparés du composant qui les fournit — même
 * découpage que [`auth.ts`](./auth.ts), pour la même raison : le rafraîchissement à chaud
 * de React veut qu'un module n'exporte qu'un composant.
 */

import { createContext, useContext } from 'react';

/** Ce que l'utilisateur choisit. */
export type ThemeMode = 'system' | 'light' | 'dark';

/** Ce qui finit par être peint. */
export type Theme = 'light' | 'dark';

/** Même préfixe que `metric.token` : tout ce que l'application range est sous `metric.`. */
export const THEME_KEY = 'metric.theme';

const MODES: readonly ThemeMode[] = ['system', 'light', 'dark'];

/**
 * Le mode enregistré, ou `system` par défaut.
 *
 * Un `localStorage` indisponible — navigation privée sur certains navigateurs, stockage
 * plein — ne doit pas empêcher l'application de s'afficher : elle repart du système, qui
 * est le défaut de toute façon.
 */
export function readMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return MODES.includes(stored as ThemeMode) ? (stored as ThemeMode) : 'system';
  } catch {
    return 'system';
  }
}

/** Enregistre le choix. `system` efface la clé plutôt que d'écrire le défaut. */
export function storeMode(mode: ThemeMode): void {
  try {
    if (mode === 'system') localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, mode);
  } catch {
    // Le thème s'applique quand même pour cette session : ne rien persister est une
    // dégradation, pas une panne.
  }
}

/** Ce que l'appareil demande. `matchMedia` manque en test : le sombre reste le défaut. */
export function systemTheme(): Theme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'dark';
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

/** Le mode, résolu en thème. C'est la seule fonction qui décide. */
export function resolveTheme(mode: ThemeMode): Theme {
  return mode === 'system' ? systemTheme() : mode;
}

/**
 * Peint le thème : l'attribut que lit `tokens.css`, et les deux balises que lit le
 * système d'exploitation.
 *
 * `theme-color` teinte la barre d'état d'iOS et le contour de la fenêtre sur Android ;
 * `color-scheme` fait suivre les champs natifs, les menus déroulants et les barres de
 * défilement. Sans elles, une page claire garde une barre d'état noire et des `<select>`
 * sombres — le genre de détail qui se voit tout de suite sur un téléphone.
 *
 * La couleur n'est pas écrite en dur : elle est **lue sur `--bg`**, une fois le thème
 * posé. `tokens.css` reste la source de vérité, y compris pour ce que voit le système.
 */
export function applyTheme(theme: Theme): void {
  if (typeof document === 'undefined') return;

  const root = document.documentElement;
  root.dataset.theme = theme;

  const bg = getComputedStyle(root).getPropertyValue('--bg').trim();
  const meta = (name: string, content: string) => {
    const tag = document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`);
    if (tag && content) tag.content = content;
  };

  meta('color-scheme', theme);
  meta('theme-color', bg);
}

/**
 * S'abonne aux changements de préférence du système. Rend la fonction de désabonnement.
 *
 * N'a d'effet qu'en mode `system` — c'est l'appelant qui le sait, pas nous.
 */
export function watchSystem(onChange: (theme: Theme) => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => {};

  const query = window.matchMedia('(prefers-color-scheme: light)');
  const listener = (event: MediaQueryListEvent) => {
    onChange(event.matches ? 'light' : 'dark');
  };

  query.addEventListener('change', listener);
  return () => {
    query.removeEventListener('change', listener);
  };
}

export interface ThemeContextValue {
  /** Ce que l'utilisateur a choisi — `system` tant qu'il n'a rien choisi. */
  mode: ThemeMode;
  /** Ce qui est peint en ce moment. En mode `system`, il suit l'appareil. */
  theme: Theme;
  setMode: (mode: ThemeMode) => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (value === null) {
    throw new Error("useTheme doit être utilisé à l'intérieur de <ThemeProvider>.");
  }
  return value;
}
