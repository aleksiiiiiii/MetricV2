/**
 * Les pictogrammes de la barre d'onglets.
 *
 * Dessinés à la main plutôt qu'importés : six traits ne valent pas une dépendance, et une
 * bibliothèque d'icônes arriverait avec son propre style de trait, sa propre grille et sa
 * propre idée du poids — trois choses que la charte décide déjà.
 *
 * Tous sur une grille de 24, trait de 1,6 px, extrémités rondes. Ils héritent de la
 * couleur du texte (`currentColor`) : c'est l'onglet qui décide s'il est actif, pas
 * l'icône.
 *
 * Aucun n'est annoncé aux lecteurs d'écran — le libellé sous l'icône dit déjà le mot.
 */

import type { ReactNode } from 'react';

interface IconProps {
  size?: number | undefined;
}

function Svg({ size = 22, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/** Accueil — le toit sous lequel tout est rassemblé. */
export function IconHome(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 10.4 12 4l8 6.4V19a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19z" />
      <path d="M9.5 20.5v-6h5v6" />
    </Svg>
  );
}

/** Activité — le tracé d'un effort, pas une chaussure ni un haltère. */
export function IconActivity(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3 12.5h3.5L9 6l4 12 2.5-5.5H21" />
    </Svg>
  );
}

/** Nutrition — un bol, et ce qui s'en échappe. */
export function IconNutrition(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3.5 12h17a8.5 8.5 0 0 1-17 0Z" />
      <path d="M6 20.5h12" />
      <path d="M9.5 8.5c0-1.4 1.2-1.8 1.2-3.2" />
      <path d="M14 8.5c0-1.4 1.2-1.8 1.2-3.2" />
    </Svg>
  );
}

/** Noter — l'action centrale : ajouter une mesure. */
export function IconPlus(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 5.5v13M5.5 12h13" />
    </Svg>
  );
}

/** Le reste de la navigation. */
export function IconMore(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="5.5" cy="12" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="18.5" cy="12" r="1.4" fill="currentColor" stroke="none" />
    </Svg>
  );
}

/** Corps — la balance. */
export function IconScale(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="3" />
      <path d="M9 9.5a3 3 0 0 1 6 0" />
      <path d="M12 9.5v3.5" />
    </Svg>
  );
}

/** Routine — le verre et la gélule, réunis sous une goutte. */
export function IconDroplet(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3.5c3.2 3.6 5.5 6.3 5.5 9.2a5.5 5.5 0 0 1-11 0c0-2.9 2.3-5.6 5.5-9.2Z" />
    </Svg>
  );
}

/** Planning — la grille des jours. */
export function IconCalendar(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3.5" y="5.5" width="17" height="15" rx="2.5" />
      <path d="M3.5 10h17M8.5 3.5v4M15.5 3.5v4" />
    </Svg>
  );
}

/** Objectif — la cible. */
export function IconTarget(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
    </Svg>
  );
}

/** Assiduité — la grille annuelle, en quatre cellules. */
export function IconGrid(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
    </Svg>
  );
}

/** Assistant — la question qu'on pose. */
export function IconChat(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M20.5 12.5c0 3.9-3.8 7-8.5 7a9.8 9.8 0 0 1-2.6-.35L4 20.5l1.5-3.7A6.6 6.6 0 0 1 3.5 12.5c0-3.9 3.8-7 8.5-7s8.5 3.1 8.5 7Z" />
    </Svg>
  );
}

/** Réglages — le curseur qu'on déplace. */
export function IconSliders(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 8h10M18 8h2M4 16h4M12 16h8" />
      <circle cx="16" cy="8" r="2.2" />
      <circle cx="10" cy="16" r="2.2" />
    </Svg>
  );
}

/** Déconnexion — la porte. */
export function IconExit(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M14.5 4.5h3a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-3" />
      <path d="M10 8.5 13.5 12 10 15.5M13.5 12h-9" />
    </Svg>
  );
}

/** Les discussions — une pile de fils. */
export function IconThreads(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 6.5h16M4 12h16M4 17.5h10" />
    </Svg>
  );
}

/** La mémoire — le carnet qu'on garde ouvert à côté. */
export function IconBook(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4.5 5.5a1.5 1.5 0 0 1 1.5-1.5h4a2.5 2.5 0 0 1 2.5 2.5v13a2 2 0 0 0-2-2H6a1.5 1.5 0 0 1-1.5-1.5Z" />
      <path d="M19.5 5.5A1.5 1.5 0 0 0 18 4h-4a2.5 2.5 0 0 0-2.5 2.5v13a2 2 0 0 1 2-2H18a1.5 1.5 0 0 0 1.5-1.5Z" />
    </Svg>
  );
}
