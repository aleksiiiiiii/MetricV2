import { NavLink, Outlet } from 'react-router';

import { Button } from '@/components/ui';
import { useAuth } from '@/lib/auth';
import { cx } from '@/lib/cx';

import styles from './Shell.module.css';
import { TabBar } from './TabBar';

/**
 * Coquille applicative (`L03-09`).
 *
 * **Deux navigations, un seul jeu d'écrans.** Sous 960 px, c'est [`TabBar`](./TabBar.tsx)
 * qui gouverne : cinq cibles en bas de l'écran, là où le pouce est déjà. Au-delà, la barre
 * horizontale ci-dessous reprend la main — une souris n'a pas de zone difficile à
 * atteindre, et un écran large a la place d'afficher neuf entrées d'un coup.
 *
 * La barre du haut demandait **806 px pour 695 disponibles**, mesurés entrée par entrée au
 * lot L14. « Tableau de bord » pesait à lui seul le sixième du total : le raccourcir en
 * « Accueil » rend ~80 px et ramène la demande à ~726, ce que le dégradé de bord couvre
 * sans qu'on lise un défaut d'affichage. C'était le premier levier identifié, et il ne
 * coûte qu'un mot.
 *
 * L'assistant n'a toujours pas d'entrée **ici** — il en a une sur mobile, dans la feuille
 * « Plus ». Sur ordinateur on y entre par la carte du tableau de bord et le lien de
 * l'écran Objectif, comme depuis le lot L14b : ajouter une dixième entrée reporterait la
 * demande à ~816 px et rendrait le débordement à nouveau visible.
 */
const NAV = [
  { to: '/', label: 'Accueil', end: true },
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

      <TabBar />
    </div>
  );
}

/** Écran d'attente pendant la validation du jeton au démarrage. */
export function SessionLoading() {
  return <div className={styles.loading}>Vérification de la session…</div>;
}
