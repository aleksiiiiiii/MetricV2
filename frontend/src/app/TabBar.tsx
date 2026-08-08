/**
 * Barre d'onglets basse (`L17-07`).
 *
 * Elle remplace, sous 960 px, la barre horizontale de l'en-tête — qui demandait **806 px
 * pour 695 disponibles** et se parcourait donc en deux gestes : faire défiler, puis viser.
 * Et elle était en haut de l'écran, c'est-à-dire hors de portée du pouce sur un téléphone
 * de 874 px de haut. Changer d'écran était le geste le plus fréquent de l'application et
 * le plus inconfortable.
 *
 * **Cinq places, neuf écrans, une action.** Le partage n'est pas alphabétique :
 *
 * * `Accueil`, `Activité` et `Nutrition` sont des **destinations** — on y va pour lire, ou
 *   pour remplir un formulaire que rien ne peut abréger.
 * * `Corps` et `Routine` étaient des destinations pour y faire un geste à un chiffre.
 *   Ils deviennent ce geste : le bouton central les couvre tous les deux, depuis n'importe
 *   quel écran. Ils restent atteignables entiers par la feuille « Plus » — un raccourci
 *   n'est jamais la seule porte.
 * * Le reste vit dans la feuille, y compris **l'assistant, qui gagne enfin une entrée** :
 *   le compromis du lot L14b — « on y entre par une carte du tableau de bord » — n'avait
 *   d'autre raison que les 806 px, et ils viennent de disparaître.
 *
 * Au-delà de 960 px, la barre s'efface et la navigation de l'en-tête reprend la main :
 * l'ordinateur ne perd rien.
 */

import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router';

import { Sheet, SheetGroup, SheetRow } from '@/components/ui';
import {
  IconActivity,
  IconCalendar,
  IconChat,
  IconDroplet,
  IconExit,
  IconGrid,
  IconHome,
  IconMore,
  IconNutrition,
  IconPlus,
  IconScale,
  IconSliders,
  IconTarget,
} from '@/components/ui/icons';
import { useAuth } from '@/lib/auth';
import { cx } from '@/lib/cx';

import { QuickLog } from './QuickLog';
import styles from './TabBar.module.css';

/**
 * Les trois destinations de la barre.
 *
 * **`Nutrition` a cédé sa place à `Assistant`** au lot L18. C'est le seul écran qu'on
 * ouvre pour *parler*, et depuis qu'il sait écrire dans les données il est aussi la porte
 * la plus courte vers la plupart des gestes — « note ma séance de ce matin » remplace une
 * navigation et un formulaire. Nutrition redescend dans la feuille : elle demande un
 * formulaire que rien n'abrège, et le `⊕` couvre déjà ce qui se saisit en un chiffre.
 */
const TABS = [
  { to: '/', label: 'Accueil', end: true, icon: IconHome },
  { to: '/activite', label: 'Activité', end: false, icon: IconActivity },
  { to: '/assistant', label: 'Assistant', end: false, icon: IconChat },
] as const;

/** Ce que la feuille « Plus » contient, groupé par ce à quoi ça sert. */
const MORE = [
  {
    title: 'Mesurer',
    entries: [
      { to: '/corps', label: 'Poids & mensurations', icon: IconScale },
      { to: '/routine', label: 'Hydratation & suppléments', icon: IconDroplet },
    ],
  },
  {
    title: 'Décider',
    entries: [
      { to: '/nutrition', label: 'Nutrition', icon: IconNutrition },
      { to: '/objectif', label: 'Objectif', icon: IconTarget },
      { to: '/planning', label: 'Planning', icon: IconCalendar },
    ],
  },
  {
    title: 'Regarder en arrière',
    entries: [{ to: '/assiduite', label: 'Assiduité', icon: IconGrid }],
  },
] as const;

export function TabBar() {
  const { state, logout } = useAuth();
  const navigate = useNavigate();
  const [more, setMore] = useState(false);
  const [quick, setQuick] = useState(false);

  function go(path: string): void {
    setMore(false);
    void navigate(path);
  }

  return (
    <>
      <nav className={styles.bar} aria-label="Navigation principale">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) => cx(styles.tab, isActive && styles.tabActive)}
          >
            <tab.icon />
            <span className={styles.label}>{tab.label}</span>
          </NavLink>
        ))}

        {/* Au centre, là où le pouce tombe : l'action, pas une destination. */}
        <button
          type="button"
          className={cx(styles.tab, styles.action)}
          aria-haspopup="dialog"
          aria-expanded={quick}
          onClick={() => {
            setQuick(true);
          }}
        >
          <span className={styles.actionDisc}>
            <IconPlus />
          </span>
          <span className={styles.label}>Noter</span>
        </button>

        <button
          type="button"
          className={cx(styles.tab, more && styles.tabActive)}
          aria-haspopup="dialog"
          aria-expanded={more}
          onClick={() => {
            setMore(true);
          }}
        >
          <IconMore />
          <span className={styles.label}>Plus</span>
        </button>
      </nav>

      <Sheet
        open={more}
        onClose={() => {
          setMore(false);
        }}
        title="Tout le reste"
        lede={state.status === 'authenticated' ? `Connecté comme ${state.username}.` : undefined}
      >
        {MORE.map((group) => (
          <SheetGroup key={group.title} title={group.title}>
            {group.entries.map((entry) => (
              <SheetRow
                key={entry.to}
                icon={<entry.icon size={20} />}
                label={entry.label}
                onClick={() => {
                  go(entry.to);
                }}
              />
            ))}
          </SheetGroup>
        ))}

        <SheetGroup title="Compte">
          <SheetRow
            icon={<IconSliders size={20} />}
            label="Réglages"
            onClick={() => {
              go('/reglages');
            }}
          />
          <SheetRow
            icon={<IconExit size={20} />}
            label="Déconnexion"
            tone="recover"
            onClick={() => {
              setMore(false);
              void logout();
            }}
          />
        </SheetGroup>
      </Sheet>

      <QuickLog
        open={quick}
        onClose={() => {
          setQuick(false);
        }}
      />
    </>
  );
}
