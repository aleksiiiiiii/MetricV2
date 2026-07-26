import { Navigate, useLocation } from 'react-router';
import type { ReactNode } from 'react';

import { useAuth } from '@/lib/auth';

import { SessionLoading } from './Shell';

/**
 * Garde de route (`AUTH-05` côté client).
 *
 * Elle ne remplace pas la protection serveur — le backend refuse déjà toute route de
 * données sans jeton. Elle évite seulement d'afficher une application dont chaque écran
 * échouerait, et mémorise la destination pour y revenir après connexion.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  const location = useLocation();

  if (state.status === 'loading') return <SessionLoading />;

  if (state.status === 'anonymous') {
    return <Navigate to="/connexion" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}
