import { useEffect, useState } from 'react';
import { Link } from 'react-router';

import { cx } from '@/lib/cx';
import { fetchHealth, type Health } from '@/lib/health';

import styles from './Home.module.css';

type Probe =
  { state: 'loading' } | { state: 'ok'; health: Health } | { state: 'down'; reason: string };

/**
 * Écran d'attente du lot L00. Il n'affiche aucune donnée métier : son seul rôle est de
 * prouver que le routage, les tokens, les polices locales et le proxy `/api` sont
 * câblés. Le tableau de bord réel est construit au lot L08.
 */
export function Home() {
  const [probe, setProbe] = useState<Probe>({ state: 'loading' });

  useEffect(() => {
    const controller = new AbortController();

    fetchHealth(controller.signal)
      .then((health) => {
        setProbe({ state: 'ok', health });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setProbe({
          state: 'down',
          reason: error instanceof Error ? error.message : 'raison inconnue',
        });
      });

    return () => {
      controller.abort();
    };
  }, []);

  return (
    <main className="wrap">
      <p className="eyebrow">Fondations · lot L00 · v0.1.0</p>
      <h1 style={{ marginTop: 10 }}>Metric</h1>
      <p className="lede" style={{ marginTop: 14 }}>
        Le journal instrumenté d'une vie. Chaque jour laisse une trace : une course, un sommeil, une
        heure de code. Metric relève, aligne, et rend la courbe lisible.
      </p>

      <div className="rule">
        <span>État du socle</span>
      </div>

      <div className={styles.probe}>
        <h3>Liaison avec l'API</h3>

        {probe.state === 'loading' && <p className={styles.muted}>Interrogation de /api/health…</p>}

        {probe.state === 'down' && (
          <>
            <p className={styles.muted}>
              <span className={cx(styles.badge, styles.down)}>API injoignable</span>
            </p>
            <p className={styles.muted}>
              {probe.reason}. Lancer le backend avec <code>make dev-api</code>.
            </p>
          </>
        )}

        {probe.state === 'ok' && (
          <dl className={styles.list}>
            <dt className={styles.key}>Service</dt>
            <dd className={styles.value}>
              <span className={cx(styles.badge, styles.ok)}>en ligne</span>
            </dd>

            <dt className={styles.key}>Version</dt>
            <dd className={styles.value}>{probe.health.version}</dd>

            <dt className={styles.key}>Environnement</dt>
            <dd className={styles.value}>{probe.health.environment}</dd>

            <dt className={styles.key}>Fuseau</dt>
            <dd className={styles.value}>{probe.health.timezone}</dd>

            <dt className={styles.key}>Heure serveur</dt>
            <dd className={styles.value}>{probe.health.time}</dd>

            <dt className={styles.key}>Nextcloud</dt>
            <dd className={styles.value}>
              {probe.health.storage_configured ? (
                <span className={cx(styles.badge, styles.ok)}>configuré</span>
              ) : (
                <span className={cx(styles.badge, styles.warn)}>non configuré</span>
              )}
            </dd>

            <dt className={styles.key}>IA</dt>
            <dd className={styles.value}>
              {probe.health.ai_enabled ? (
                <span className={cx(styles.badge, styles.ok)}>disponible</span>
              ) : (
                <span className={cx(styles.badge, styles.warn)}>saisie manuelle</span>
              )}
            </dd>
          </dl>
        )}

        <p className={styles.muted}>
          Sans clé IA ni Nextcloud, l'application démarre quand même : l'IA est un confort, jamais
          un prérequis.
        </p>
      </div>

      <nav className={styles.links}>
        <Link to="/_kitchen-sink">Référence visuelle →</Link>
        <a href="/api/docs">Documentation de l'API →</a>
      </nav>
    </main>
  );
}
