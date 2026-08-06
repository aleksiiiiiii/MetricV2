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
 *
 * **La barre reste à neuf entrées, et c'est une décision.** Elle demandait déjà 790 px
 * pour 695 disponibles depuis que « Planning » l'a rejointe au lot L13, la largeur de
 * lecture étant plafonnée à `--wrap` ; une dixième entrée aurait aggravé un débordement
 * déjà relevé sur téléphone **et** sur ordinateur. « Objectif » prend donc la place de
 * « Charte ».
 *
 * Le compte ne bouge pas, la largeur si : **806 px**, mesurés dans le navigateur, parce
 * qu'« Objectif » est un mot plus long que « Charte » — seize pixels de plus. Le chiffre
 * est noté parce qu'il est le seul argument utilisable le jour où `L17-07` tranchera, et
 * qu'une décision de mise en page qui se croit neutre sans avoir été mesurée n'est qu'un
 * espoir.
 *
 * `/_kitchen-sink` n'en est pas fermée pour autant : elle reste publique et atteignable
 * par son adresse — c'est ce qui la rend consultable depuis n'importe quel appareil et
 * vérifiable par capture automatisée. Ce qu'elle perd est une place dans la navigation
 * **utilisateur**, où une référence de charte n'a jamais eu grand-chose à faire.
 */
const NAV = [
  { to: '/', label: 'Tableau de bord', end: true },
  { to: '/corps', label: 'Corps', end: false },
  { to: '/activite', label: 'Activité', end: false },
  { to: '/planning', label: 'Planning', end: false },
  { to: '/objectif', label: 'Objectif', end: false },
  { to: '/routine', label: 'Routine', end: false },
  { to: '/nutrition', label: 'Nutrition', end: false },
  { to: '/assiduite', label: 'Assiduité', end: false },
  { to: '/reglages', label: 'Réglages', end: false },
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
