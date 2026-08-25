/**
 * Les confettis (`lib/confetti.ts`).
 *
 * Trois garanties, et aucune ne porte sur l'apparence — elle se regarde. Ce qui se teste,
 * c'est qu'une célébration ne casse rien : ni la préférence de l'utilisateur, ni son doigt,
 * ni le geste qu'elle célèbre.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { celebrate } from './confetti';

/** Déclare ce que `matchMedia` répond, que jsdom ne fournit pas. */
function reducedMotion(reduce: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: reduce, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
}

function overlay(): HTMLCanvasElement | null {
  return document.querySelector('canvas[aria-hidden="true"]');
}

/**
 * Un contexte 2D minimal — jsdom n'en fournit aucun.
 *
 * Sans lui, `celebrate` retire sa surface aussitôt : c'est le comportement voulu, mais il
 * empêche d'observer quoi que ce soit. On double le moteur de rendu, pas la logique.
 */
function withCanvas() {
  const stub = {
    setTransform: vi.fn(),
    clearRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    translate: vi.fn(),
    rotate: vi.fn(),
    fillRect: vi.fn(),
    globalAlpha: 1,
    fillStyle: '',
  };
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    stub as unknown as CanvasRenderingContext2D,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  overlay()?.remove();
});

describe('célébration', () => {
  it('ne fait rien quand l’appareil demande moins de mouvement', () => {
    // Une animation décorative est la première qui doit se plier à cette préférence.
    // Pas une version lente : rien.
    reducedMotion(true);

    celebrate();

    expect(overlay()).toBeNull();
  });

  it('pose une surface qui n’intercepte ni le doigt ni la synthèse vocale', () => {
    reducedMotion(false);
    withCanvas();

    celebrate();

    const canvas = overlay();
    expect(canvas).not.toBeNull();
    expect(canvas?.style.pointerEvents).toBe('none');
    expect(canvas?.getAttribute('aria-hidden')).toBe('true');
  });

  it('n’empile pas deux surfaces quand on célèbre deux fois de suite', () => {
    // Deux séances consignées coup sur coup relancent la même, sans quoi le document
    // finirait avec autant de canevas que de gestes.
    reducedMotion(false);
    withCanvas();

    celebrate();
    celebrate();

    expect(document.querySelectorAll('canvas[aria-hidden="true"]')).toHaveLength(1);
  });

  it('ne lève pas quand le canevas ne rend aucun contexte', () => {
    // C'est une célébration : elle n'a aucun droit de faire échouer le geste qu'elle
    // célèbre. Un environnement sans canevas 2D — jsdom par défaut — repart en silence.
    reducedMotion(false);
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);

    expect(() => {
      celebrate();
    }).not.toThrow();
    expect(overlay()).toBeNull();
  });
});
