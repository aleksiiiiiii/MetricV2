/**
 * Feuille qui monte du bas.
 *
 * C'est le contenant du mobile : elle apparaît là où le pouce est déjà, elle n'efface pas
 * l'écran qu'on regardait, et elle se referme d'un geste vers le bas — trois choses qu'une
 * page de plus ne sait pas faire.
 *
 * Deux emplois dans l'application, et ils ont dicté sa forme : les entrées de navigation
 * qui ne tiennent pas dans la barre, et la saisie rapide. Dans les deux cas le contenu
 * est une liste de cibles qu'on touche sans regarder, d'où la hauteur libre et le
 * défilement interne plutôt qu'un panneau qui s'ajuste au contenu.
 *
 * **Quatre portes de sortie**, parce qu'une feuille dont on ne sait pas sortir est un
 * piège : le geste vers le bas, l'appui hors de la feuille, la touche Échap, et un bouton
 * nommé. Le geste est un raccourci — jamais la seule porte, c'est la règle du projet.
 */

import type { ReactNode } from 'react';
import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

import { cx } from '@/lib/cx';
import { useDownwardSwipe } from '@/lib/swipe';

import styles from './Sheet.module.css';

export function Sheet({
  open,
  onClose,
  title,
  /** Décrit ce que la feuille sert à faire, sous le titre. */
  lede,
  children,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  lede?: string | undefined;
  children: ReactNode;
  className?: string | undefined;
}) {
  const panel = useRef<HTMLDivElement>(null);
  // Ce qui avait le focus avant l'ouverture. Le rendre est ce qui distingue une feuille
  // d'une page : on revient exactement où on était.
  const restore = useRef<HTMLElement | null>(null);

  const swipe = useDownwardSwipe({ track: true, onDown: onClose });

  /**
   * La fermeture, **hors des dépendances de l'effet**.
   *
   * L'effet en dépendait, et `onClose` est presque toujours une lambda : son identité
   * change à chaque rendu de l'appelant. L'effet se rejouait donc à chaque rendu, et sa
   * séquence — nettoyage puis mise en place — rend le focus à l'élément d'avant
   * l'ouverture, puis le reprend sur le panneau.
   *
   * Tant que la feuille n'a porté que des formulaires dont l'état vivait dans un
   * **enfant**, rien ne s'est vu : l'appelant ne rendait pas à chaque frappe. La première
   * feuille dont le champ et le `onClose` vivent dans le même composant l'a fait sortir
   * — un seul caractère arrivait dans le champ, les suivants tombaient sur le panneau.
   *
   * Une référence plutôt qu'un `useCallback` chez chaque appelant : la correction tient
   * au composant, et aucun des six emplois n'a à connaître la règle.
   */
  const closing = useRef(onClose);
  // Tenue à jour dans un effet, et non pendant le rendu : une référence écrite pendant le
  // rendu casse le rendu concurrent, et `react-hooks/refs` le refuse à juste titre. Le
  // gestionnaire d'échappement la lit au moment de l'appui, donc bien après la validation.
  useEffect(() => {
    closing.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;

    restore.current = document.activeElement as HTMLElement | null;
    panel.current?.focus();

    // La page derrière ne défile plus : sans cela, un doigt qui dépasse la feuille fait
    // glisser le tableau de bord et on perd sa place en revenant.
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    function onKey(event: KeyboardEvent): void {
      if (event.key === 'Escape') closing.current();
    }
    document.addEventListener('keydown', onKey);

    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
      restore.current?.focus();
    };
  }, [open]);

  if (!open) return null;

  /*
   * **La feuille se peint sur `body`, et c'est ce qui la met vraiment au-dessus.**
   *
   * Elle déclarait `z-index: 60` contre 30 pour la barre d'onglets, et se faisait
   * pourtant recouvrir sur ses 56 derniers pixels. Mesuré à 360 px avec
   * `elementFromPoint` : au bas de la feuille des discussions, du carnet et de la feuille
   * de séance, le doigt touchait **la barre**. Seule celle du `⊕` gagnait — parce qu'elle
   * est montée par la barre elle-même.
   *
   * Un `z-index` ne franchit pas un contexte d'empilement. Les feuilles sont rendues dans
   * `<main>`, dont le fondu d'entrée de la phase E — une `animation` sur l'opacité — en
   * crée un : leur 60 était enfermé dedans, et c'est le contexte entier qui passait sous
   * le 30 de la barre.
   *
   * Le portail règle la classe entière du problème, pour les feuilles d'aujourd'hui comme
   * pour celles qu'on ajoutera. Le remplacer par un dégagement bas dans chaque écran
   * aurait demandé de ne jamais l'oublier — et l'audit ne mesure pas le recouvrement.
   */
  return createPortal(
    <div className={styles.layer}>
      <button
        type="button"
        className={styles.scrim}
        aria-label="Fermer"
        onClick={onClose}
        tabIndex={-1}
      />

      <div
        ref={panel}
        className={cx(styles.panel, className)}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        style={
          swipe.offset > 0 ? { transform: `translateY(${String(swipe.offset)}px)` } : undefined
        }
      >
        {/* La poignée porte le geste. Elle est aussi un bouton : là où il n'y a pas de
            doigt — ou pour qui navigue au clavier — elle referme d'un appui. */}
        <button
          type="button"
          className={styles.grip}
          aria-label={`Fermer « ${title} »`}
          onClick={onClose}
          {...swipe.handlers}
        >
          <span className={styles.gripBar} />
        </button>

        <div className={styles.head}>
          <h2 className={styles.title}>{title}</h2>
          {lede !== undefined && <p className={styles.lede}>{lede}</p>}
        </div>

        <div className={styles.body}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}

/**
 * Ligne d'une feuille : une cible pleine largeur, à `--tap-lg`.
 *
 * `href` la rend `<a>`, son absence la rend `<button>`. Ce n'est pas une commodité : une
 * navigation et une action ne s'annoncent pas pareil, ne s'ouvrent pas pareil dans un
 * nouvel onglet, et ne se lisent pas pareil à la synthèse vocale.
 */
export function SheetRow({
  icon,
  label,
  hint,
  onClick,
  href,
  tone,
  children,
  'aria-label': ariaLabel,
}: {
  icon?: ReactNode | undefined;
  label?: string | undefined;
  hint?: ReactNode | undefined;
  onClick?: (() => void) | undefined;
  href?: string | undefined;
  tone?: 'recover' | undefined;
  children?: ReactNode | undefined;
  /**
   * Nom accessible, quand l'indice ne fait pas partie de ce qu'il faut annoncer.
   *
   * Par défaut, le nom d'une ligne est son libellé **suivi de son indice** — « Course
   * 8,4 km », et c'est bien : l'indice est une donnée qui appartient à la ligne. Mais
   * quand l'indice explique le choix plutôt qu'il ne le décrit — « Photo, l'assiette
   * suffit » —, l'annoncer rallonge chaque entrée d'une phrase qu'on entend quatre fois.
   */
  'aria-label'?: string | undefined;
}) {
  const inner = children ?? (
    <>
      {icon !== undefined && <span className={styles.rowIcon}>{icon}</span>}
      <span className={styles.rowLabel}>{label}</span>
      {hint !== undefined && <span className={styles.rowHint}>{hint}</span>}
    </>
  );

  const classes = cx(styles.row, tone === 'recover' && styles.rowRecover);

  if (href !== undefined) {
    return (
      <a className={classes} href={href} aria-label={ariaLabel}>
        {inner}
      </a>
    );
  }

  return (
    <button type="button" className={classes} onClick={onClick} aria-label={ariaLabel}>
      {inner}
    </button>
  );
}

/** Regroupement titré à l'intérieur d'une feuille. */
export function SheetGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.group}>
      <p className={cx('eyebrow', styles.groupTitle)}>{title}</p>
      {children}
    </section>
  );
}
