import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import { api, onSessionExpired, tokenStore } from '@/lib/api';
import { AuthContext, type AuthState } from '@/lib/auth';
import { useToast } from '@/lib/toast';

/**
 * Détenteur de la session (`AUTH-03`, `AUTH-06`, `AUTH-07`).
 *
 * Au montage, un jeton présent n'est pas cru sur parole : il est confronté au serveur.
 * Sans cela, un jeton expiré pendant que l'app était fermée afficherait l'application
 * puis ferait échouer chaque écran l'un après l'autre.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(() =>
    tokenStore.read() ? { status: 'loading' } : { status: 'anonymous' },
  );
  const { notify } = useToast();

  useEffect(() => {
    if (state.status !== 'loading') return;

    const controller = new AbortController();
    api
      .me(controller.signal)
      .then(({ username }) => {
        setState({ status: 'authenticated', username });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: 'anonymous' });
      });

    return () => {
      controller.abort();
    };
    // Volontairement au montage seul : une revalidation à chaque changement d'état
    // boucherait le rendu.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Une expiration détectée par n'importe quelle requête ramène l'application à l'écran
  // de connexion, avec le motif renvoyé par le serveur.
  useEffect(
    () =>
      onSessionExpired((reason) => {
        setState({ status: 'anonymous', reason });
        notify(reason, 'load');
      }),
    [notify],
  );

  const login = useCallback(async (username: string, password: string) => {
    const session = await api.login(username, password);
    tokenStore.write(session.access_token);
    setState({ status: 'authenticated', username: session.username });
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Le jeton est autoporteur : même si l'appel échoue, l'effacer termine la session
      // côté client, et c'est ce qui compte (`AUTH-07`).
    }
    tokenStore.clear();
    setState({ status: 'anonymous' });
  }, []);

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
