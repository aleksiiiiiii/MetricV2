import { useState } from 'react';
import type { SyntheticEvent } from 'react';
import { Navigate, useLocation } from 'react-router';

import { Button, Card, Field } from '@/components/ui';
import { ApiError, NetworkError } from '@/lib/api';
import { useAuth } from '@/lib/auth';

import styles from './Login.module.css';

interface LocationState {
  from?: string;
}

/**
 * Écran de connexion (`AUTH-01`, `L03-08`).
 *
 * Le message d'erreur vient du serveur et s'affiche tel quel : il est déjà en français,
 * et le client décide sur le **code**, jamais sur le texte (`API-07`). Deux codes ont un
 * traitement particulier, parce que la conduite à tenir diffère :
 *
 * * `too_many_attempts` — attendre, ce n'est pas une erreur de saisie ;
 * * `auth_not_configured` — rien à ressaisir, c'est le serveur qu'il faut configurer.
 */
export function Login() {
  const { state, login } = useAuth();
  const location = useLocation();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<ApiError | NetworkError | null>(null);
  const [busy, setBusy] = useState(false);

  if (state.status === 'authenticated') {
    const from = (location.state as LocationState | null)?.from;
    return <Navigate to={from ?? '/'} replace />;
  }

  async function submit(event: SyntheticEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (caught) {
      setError(
        caught instanceof ApiError || caught instanceof NetworkError
          ? caught
          : new NetworkError(caught),
      );
    } finally {
      setBusy(false);
    }
  }

  const isConfigurationProblem = error instanceof ApiError && error.code === 'auth_not_configured';
  const fieldError =
    error instanceof ApiError && error.code === 'validation_error' ? error : undefined;

  return (
    <div className={styles.page}>
      <div className={styles.panel}>
        <header className={styles.head}>
          <p className="eyebrow">Metric</p>
          <h1>Connexion</h1>
        </header>

        <Card>
          <form className={styles.form} onSubmit={(event) => void submit(event)} noValidate>
            {state.status === 'anonymous' && state.reason !== undefined && error === null && (
              <p className={styles.notice}>{state.reason}</p>
            )}

            {error !== null && (
              <p className={styles.error} role="alert">
                {error.message}
              </p>
            )}

            <Field
              label="Identifiant"
              name="username"
              autoComplete="username"
              autoFocus
              required
              value={username}
              error={fieldError?.messageFor('username')}
              onChange={(event) => {
                setUsername(event.target.value);
              }}
            />

            <Field
              label="Mot de passe"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              error={fieldError?.messageFor('password')}
              onChange={(event) => {
                setPassword(event.target.value);
              }}
            />

            <Button
              type="submit"
              variant="primary"
              busy={busy}
              disabled={isConfigurationProblem || username === '' || password === ''}
            >
              {busy ? 'Vérification…' : 'Ouvrir la session'}
            </Button>
          </form>
        </Card>

        <p className={styles.footer}>
          {isConfigurationProblem
            ? 'Lance « make hash-password » puis renseigne .env'
            : 'Session de 7 jours · un seul compte'}
        </p>
      </div>
    </div>
  );
}
