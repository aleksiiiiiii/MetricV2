/**
 * Confettis — deux gerbes tirées des coins bas vers le centre.
 *
 * ── Pourquoi c'est écrit à la main ────────────────────────────────────────
 *
 * Une bibliothèque de confettis pèse plus que ce fichier et arrive avec sa propre idée de
 * la physique, de la palette et du respect des préférences système. Deux cents lignes de
 * canevas ne valent pas une dépendance — c'est le raisonnement de `icons.tsx`, appliqué à
 * une animation.
 *
 * ── Trois choses qu'une fête ne doit pas casser ───────────────────────────
 *
 * * **`prefers-reduced-motion` est respecté.** Un utilisateur qui a demandé moins de
 *   mouvement ne reçoit rien du tout — pas une version lente, rien. C'est la règle du
 *   projet, posée en fin de `base.css`, et une animation décorative est la première qui
 *   doit s'y plier.
 * * **Rien n'intercepte le doigt.** Le canevas est en `pointer-events: none` et
 *   `aria-hidden` : il ne se met jamais entre l'utilisateur et le bouton qu'il vient
 *   d'appuyer, et il n'est pas annoncé — le message de confirmation, lui, l'est déjà.
 * * **Un seul canevas, retiré à la fin.** Deux séances consignées coup sur coup relancent
 *   la même surface au lieu d'en empiler deux, et l'animation terminée ne laisse rien dans
 *   le document.
 *
 * ── La palette vient des jetons ───────────────────────────────────────────
 *
 * `--confetti`, lue à l'exécution : les deux thèmes n'ont pas les mêmes teintes, et une
 * liste écrite ici serait la seule couleur en dur du dépôt.
 */

/** Durée de vie d'une gerbe, en millisecondes. Au-delà, la fête devient une attente. */
const LIFETIME = 2200;

/** Combien de morceaux par coin. Assez pour une gerbe, pas assez pour un écran plein. */
const PER_SIDE = 45;

/** Repli si le jeton est absent — un thème incomplet ne doit pas rendre la fête invisible. */
const FALLBACK: [string, ...string[]] = ['#7fa8b4', '#8aa37b', '#e2a659', '#a9748a'];

interface Piece {
  x: number;
  y: number;
  vx: number;
  vy: number;
  spin: number;
  angle: number;
  size: number;
  colour: string;
}

let canvas: HTMLCanvasElement | null = null;
let frame = 0;

function palette(): string[] {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--confetti');
  const parsed = raw
    .split(',')
    .map((colour) => colour.trim())
    .filter((colour) => colour !== '');
  return parsed.length > 0 ? parsed : FALLBACK;
}

/**
 * Une gerbe partant d'un coin bas vers le centre.
 *
 * `aim` est l'angle visé en radians, mesuré depuis l'horizontale et **vers le haut**. Les
 * deux coins tirent en miroir, avec une dispersion : sans elle, les morceaux partent en
 * ligne et ça ne ressemble à rien.
 */
function burst(from: 'left' | 'right', width: number, height: number, colours: string[]): Piece[] {
  const pieces: Piece[] = [];
  const x = from === 'left' ? 0 : width;
  const aim = from === 'left' ? -Math.PI / 3.4 : (-Math.PI * 2) / 3.1;

  for (let index = 0; index < PER_SIDE; index += 1) {
    const spread = (Math.random() - 0.5) * 0.7;
    const speed = 11 + Math.random() * 9;
    const angle = aim + spread;
    pieces.push({
      x,
      y: height,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      spin: (Math.random() - 0.5) * 0.3,
      angle: Math.random() * Math.PI,
      size: 5 + Math.random() * 5,
      colour: colours[index % colours.length] ?? FALLBACK[0],
    });
  }
  return pieces;
}

function surface(): HTMLCanvasElement {
  // `isConnected` et non `!== null` : garder une référence ne garantit pas que le nœud est
  // encore dans le document. Tout ce qui vide le corps de la page — un rendu de test, un
  // outil, un jour une navigation qui remplace la racine — laissait sinon la variable
  // pointer sur une surface détachée, et **plus aucune célébration ne s'affichait** sans
  // qu'une ligne de code puisse le dire. Trouvé au test, pas à l'œil.
  if (canvas !== null && canvas.isConnected) return canvas;

  const created = document.createElement('canvas');
  created.setAttribute('aria-hidden', 'true');
  // En ligne et non dans un module CSS : c'est une surface jetable créée par du script,
  // elle n'a pas de composant à qui appartenir. `--z-toast` n'existe pas ; la valeur est
  // au-dessus de la barre d'onglets (30) et des feuilles (60).
  created.style.cssText =
    'position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:90';
  document.body.appendChild(created);
  canvas = created;
  return created;
}

function clear(): void {
  cancelAnimationFrame(frame);
  canvas?.remove();
  canvas = null;
}

/**
 * Lance les confettis, sauf si l'appareil demande moins de mouvement.
 *
 * Ne lève jamais et ne rend rien : c'est une célébration, elle n'a aucun droit de faire
 * échouer le geste qu'elle célèbre. Un navigateur sans canevas 2D repart en silence.
 */
export function celebrate(): void {
  if (typeof document === 'undefined' || typeof requestAnimationFrame === 'undefined') return;
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;

  const element = surface();
  const context = element.getContext('2d');
  if (context === null) {
    clear();
    return;
  }

  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const width = window.innerWidth;
  const height = window.innerHeight;
  element.width = Math.round(width * ratio);
  element.height = Math.round(height * ratio);
  context.setTransform(ratio, 0, 0, ratio, 0, 0);

  const colours = palette();
  const pieces = [
    ...burst('left', width, height, colours),
    ...burst('right', width, height, colours),
  ];
  const started = performance.now();

  function draw(now: number): void {
    const elapsed = now - started;
    if (elapsed > LIFETIME || context === null) {
      clear();
      return;
    }

    context.clearRect(0, 0, width, height);
    // Les morceaux s'effacent sur le dernier tiers : disparaître d'un coup se remarque
    // plus que la chute elle-même.
    context.globalAlpha = Math.max(0, Math.min(1, (LIFETIME - elapsed) / (LIFETIME / 3)));

    for (const piece of pieces) {
      piece.x += piece.vx;
      piece.y += piece.vy;
      // Gravité et frottement. Les deux ensemble donnent une retombée ; la gravité seule
      // donne une parabole d'obus, qui se lit comme une erreur de calcul.
      piece.vy += 0.42;
      piece.vx *= 0.99;
      piece.angle += piece.spin;

      context.save();
      context.translate(piece.x, piece.y);
      context.rotate(piece.angle);
      context.fillStyle = piece.colour;
      // Un rectangle plus large que haut, tourné : c'est ce qui donne le scintillement
      // d'un morceau de papier qui se retourne en tombant.
      context.fillRect(-piece.size / 2, -piece.size / 4, piece.size, piece.size / 2);
      context.restore();
    }

    frame = requestAnimationFrame(draw);
  }

  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(draw);
}
