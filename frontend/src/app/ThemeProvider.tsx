import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import {
  ThemeContext,
  applyTheme,
  readMode,
  storeMode,
  systemTheme,
  watchSystem,
  type ThemeMode,
} from '@/lib/theme';

/**
 * Détenteur du thème.
 *
 * Il ne peint rien au premier rendu : l'attribut `data-theme` est déjà sur `<html>`,
 * posé par le script en tête d'`index.html` avant la première peinture. Le provider
 * reprend cet état et le tient — un `useEffect` qui poserait l'attribut au montage
 * ferait clignoter la page une fois par chargement.
 *
 * L'abonnement au système n'existe qu'en mode `system`. Un utilisateur qui a choisi
 * « clair » garde le clair quand son téléphone bascule en sombre à la tombée du jour :
 * c'est le sens de « le choix manuel l'emporte ».
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(readMode);
  const [system, setSystem] = useState(systemTheme);

  /**
   * Le thème est **dérivé**, jamais stocké. Le tenir en état demanderait de le
   * resynchroniser à chaque fois que l'une de ses deux sources bouge, et c'est
   * exactement là que naissent les désaccords : un mode « système » qui reste sombre
   * parce qu'un `setState` a été oublié dans une branche.
   */
  const theme = mode === 'system' ? system : mode;

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    storeMode(next);
  }, []);

  // L'abonnement vit tant que l'application vit, quel que soit le mode : au retour sur
  // « système », la préférence est déjà à jour plutôt qu'en attente du prochain
  // basculement.
  useEffect(() => watchSystem(setSystem), []);

  // Le script d'`index.html` a déjà posé cet attribut avant la première peinture ; ce
  // premier passage réécrit donc la même valeur, sans rien faire clignoter. Les suivants
  // sont les vrais changements.
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const value = useMemo(() => ({ mode, theme, setMode }), [mode, theme, setMode]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
