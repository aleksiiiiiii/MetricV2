import { NavLink, Outlet } from 'react-router';

import { Button } from '@/components/ui';
import { useAuth } from '@/lib/auth';
import { cx } from '@/lib/cx';

import styles from './Shell.module.css';

/**
 * Coquille applicative (`L03-09`).
 *
 * Les entrées de navigation suivent les domaines du backlog. Elles pointent vers des
 * écrans construits lot par lot ; celles qui n'ont pas encore d'écran ne sont pas
 * affichées, plutôt que de mener à une page vide.
 */
const NAV = [
  { to: '/', label: 'Tableau de bord', end: true },
  { to: '/corps', label: 'Corps', end: false },
  { to: '/activite', label: 'Activité', end: false },
  { to: '/routine', label: 'Routine', end: false },
  { to: '/nutrition', label: 'Nutrition', end: false },
  { to: '/reglages', label: 'Réglages', end: false },
  { to: '/_kitchen-sink', label: 'Charte', end: false },
] as const;

export function Shell() {
  const { state, logout } = useAuth();

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <NavLink to="/" className={cx(styles.brand)}>
            Metric
          </NavLink>

          <nav className={styles.nav} aria-label="Navigation principale">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => cx(styles.navLink, isActive && styles.navActive)}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <span className={styles.spacer} />

          <div className={styles.user}>
            {state.status === 'authenticated' && (
              <span className={styles.username}>{state.username}</span>
            )}
            <Button
              variant="quiet"
              onClick={() => {
                void logout();
              }}
            >
              Déconnexion
            </Button>
          </div>
        </div>
      </header>

      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}

/** Écran d'attente pendant la validation du jeton au démarrage. */
export function SessionLoading() {
  return <div className={styles.loading}>Vérification de la session…</div>;
}
