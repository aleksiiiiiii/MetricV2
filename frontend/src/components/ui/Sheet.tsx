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

  useEffect(() => {
    if (!open) return;

    restore.current = document.activeElement as HTMLElement | null;
    panel.current?.focus();

    // La page derrière ne défile plus : sans cela, un doigt qui dépasse la feuille fait
    // glisser le tableau de bord et on perd sa place en revenant.
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    function onKey(event: KeyboardEvent): void {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);

    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
      restore.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
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
    </div>
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
}: {
  icon?: ReactNode | undefined;
  label?: string | undefined;
  hint?: ReactNode | undefined;
  onClick?: (() => void) | undefined;
  href?: string | undefined;
  tone?: 'recover' | undefined;
  children?: ReactNode | undefined;
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
      <a className={classes} href={href}>
        {inner}
      </a>
    );
  }

  return (
    <button type="button" className={classes} onClick={onClick}>
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
