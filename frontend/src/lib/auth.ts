/**
 * État de session, côté client (`AUTH-03`, `AUTH-06`, `AUTH-07`).
 *
 * Le contexte et le hook vivent ici, séparés du composant qui les fournit : c'est ce qui
 * permet à `AuthProvider.tsx` de n'exporter qu'un composant, et au rafraîchissement à
 * chaud de React de fonctionner sans recharger la page entière.
 */

import { createContext, useContext } from 'react';

export type AuthState =
  /** Jeton présent, en cours de validation auprès du serveur. */
  | { status: 'loading' }
  /** Pas de session. `reason` est renseigné quand elle vient d'expirer. */
  | { status: 'anonymous'; reason?: string }
  | { status: 'authenticated'; username: string };

export interface AuthContextValue {
  state: AuthState;
  /** Ouvre une session. Laisse remonter `ApiError` pour que le formulaire l'affiche. */
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth doit être utilisé à l'intérieur de <AuthProvider>.");
  }
  return value;
}
