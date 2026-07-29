/**
 * Glissement horizontal au doigt (`L17-07`).
 *
 * Une seule implémentation pour tous les gestes de l'application : bande de séances,
 * ligne qu'on tire pour révéler une action, passage d'une séance à la suivante. Écrire
 * le suivi du pointeur deux fois, c'est se garantir deux seuils différents et deux
 * comportements différents au premier cas limite.
 *
 * Trois décisions valent d'être connues avant de s'en servir.
 *
 * **Pointer Events, pas Touch Events.** La même API couvre le doigt, le stylet et la
 * souris ; un geste testé à la souris est donc le geste réel, pas une approximation.
 *
 * **Un geste plus vertical qu'horizontal appartient à la page.** Sans cette garde, faire
 * défiler une liste avec le pouce déclencherait une action à chaque petit écart latéral —
 * et sur une liste d'activités, cette action est une suppression.
 *
 * **Le seuil est une distance, pas une vitesse.** Un geste lent et franc doit compter
 * autant qu'un geste vif : c'est le même utilisateur, avec les mains moites après une
 * série.
 */

import { useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';

/** Distance à parcourir avant qu'un glissement compte. Doit suivre `--swipe-threshold`. */
export const SWIPE_THRESHOLD = 56;

/**
 * Écart vertical toléré avant d'abandonner le geste au défilement de la page.
 * Sous cette valeur, un doigt qui part de travers reste un glissement horizontal.
 */
const VERTICAL_SLACK = 10;

export interface SwipeOptions {
  onLeft?: (() => void) | undefined;
  onRight?: (() => void) | undefined;
  threshold?: number | undefined;
  /** Renvoie l'écart courant pour suivre le doigt. Faux : le geste ne se voit qu'à la fin. */
  track?: boolean | undefined;
  /**
   * N'accepte que le doigt et le stylet.
   *
   * À poser dès que la zone contient du texte ou un champ : à la souris, tirer pour
   * sélectionner du texte est un geste courant et légitime, qui déclencherait sinon une
   * navigation — ou une suppression.
   */
  touchOnly?: boolean | undefined;
}

export interface SwipeHandlers {
  onPointerDown: (event: ReactPointerEvent) => void;
  onPointerMove: (event: ReactPointerEvent) => void;
  onPointerUp: (event: ReactPointerEvent) => void;
  onPointerCancel: () => void;
}

export interface Swipe {
  /** Écart horizontal courant en pixels, `0` hors geste. Nul si `track` est faux. */
  offset: number;
  handlers: SwipeHandlers;
}

export function useHorizontalSwipe({
  onLeft,
  onRight,
  threshold = SWIPE_THRESHOLD,
  track = false,
  touchOnly = false,
}: SwipeOptions): Swipe {
  const origin = useRef<{ x: number; y: number; id: number } | null>(null);
  const [offset, setOffset] = useState(0);

  function reset(): void {
    origin.current = null;
    setOffset(0);
  }

  return {
    offset,
    handlers: {
      onPointerDown(event) {
        if (touchOnly && event.pointerType === 'mouse') return;
        // Un clic droit ou un clic du milieu n'est pas un glissement.
        if (event.pointerType === 'mouse' && event.button !== 0) return;
        origin.current = { x: event.clientX, y: event.clientY, id: event.pointerId };
        try {
          // Capturer garde le geste vivant quand le doigt sort de l'élément — sinon
          // tirer une ligne un peu trop haut annulerait le geste en cours de route.
          event.currentTarget.setPointerCapture(event.pointerId);
        } catch {
          // jsdom ne l'implémente pas, et un navigateur peut le refuser. Le geste
          // fonctionne sans, il est seulement moins tolérant.
        }
      },

      onPointerMove(event) {
        const from = origin.current;
        if (from === null || from.id !== event.pointerId) return;

        const dx = event.clientX - from.x;
        const dy = event.clientY - from.y;
        if (Math.abs(dy) > VERTICAL_SLACK && Math.abs(dy) > Math.abs(dx)) {
          reset();
          return;
        }
        if (track) setOffset(dx);
      },

      onPointerUp(event) {
        const from = origin.current;
        reset();
        if (from === null || from.id !== event.pointerId) return;

        const dx = event.clientX - from.x;
        if (dx <= -threshold) onLeft?.();
        else if (dx >= threshold) onRight?.();
      },

      onPointerCancel: reset,
    },
  };
}
