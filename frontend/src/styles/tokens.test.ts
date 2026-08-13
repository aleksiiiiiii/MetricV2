/**
 * Ce que `tokens.css` promet, vérifié sur le fichier lui-même.
 *
 * Ces tests ne rendent aucun composant : ils lisent la feuille de tokens comme une table
 * de valeurs et contrôlent les invariants qu'aucun `tsc` ne peut voir. Trois d'entre eux
 * gardent des défauts qui se sont réellement produits, ou qui coûteraient cher :
 *
 * 1. **Une composante RVB désaccordée de son hex.** Tout ce qui dérive une opacité —
 *    badges, bloc IA, `Stepper` proposé, les quatre niveaux de heatmap — lit `--x-rgb`,
 *    pendant que le texte lit `--x`. Les changer séparément donne un badge d'une couleur
 *    et son libellé d'une autre, sans que rien ne casse.
 * 2. **Un token de couleur oublié dans le thème clair.** Il resterait à sa valeur sombre
 *    et ne se verrait que sur l'écran qui l'emploie.
 * 3. **Les quatre niveaux de heatmap qui se délavent.** Ils ne sont que des opacités : le
 *    jeu qui sépare bien sur fond sombre écrase tout sur fond clair.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

/**
 * Les commentaires partent d'abord : ce fichier en contient beaucoup, et ils citent les
 * sélecteurs qu'on cherche — `indexOf(":root[data-theme='light']")` tombait sur la prose
 * du bandeau avant de tomber sur la règle.
 */
const TOKENS = read('./tokens.css').replace(/\/\*[\s\S]*?\*\//g, '');
const INDEX = read('../../index.html');

/** Extrait le corps d'un bloc, en équilibrant les accolades. */
function block(css: string, selector: string): string {
  const start = css.indexOf(selector);
  expect(start, `bloc « ${selector} » introuvable`).toBeGreaterThan(-1);

  let depth = 0;
  for (let i = css.indexOf('{', start); i < css.length; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}' && --depth === 0) {
      return css.slice(css.indexOf('{', start) + 1, i);
    }
  }
  throw new Error(`bloc « ${selector} » non refermé`);
}

/** Les déclarations d'un bloc. */
function tokensOf(body: string): Map<string, string> {
  const found = new Map<string, string>();
  for (const match of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    const [, name, value] = match;
    if (name === undefined || value === undefined) continue;
    found.set(name, value.trim());
  }
  return found;
}

const THEMES = {
  sombre: tokensOf(block(TOKENS, ':root {')),
  clair: tokensOf(block(TOKENS, ":root[data-theme='light']")),
};

// ── Colorimétrie ──────────────────────────────────────

type RGB = readonly [number, number, number];

const hex = (value: string): RGB => {
  const match = /^#([0-9a-f]{6})$/i.exec(value.trim());
  if (!match) throw new Error(`« ${value} » n'est pas un hex à six chiffres`);
  const digits = match[1] ?? '';
  return [0, 2, 4].map((i) => parseInt(digits.slice(i, i + 2), 16)) as unknown as RGB;
};

const triple = (value: string): RGB => {
  const parts = value.trim().split(/\s+/).map(Number);
  expect(parts, `« ${value} » n'est pas un triplet`).toHaveLength(3);
  return parts as unknown as RGB;
};

const channel = (c: number) => {
  const x = c / 255;
  return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
};

const luminance = ([r, g, b]: RGB) =>
  0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);

const contrast = (a: RGB, b: RGB) => {
  const [high, low] = luminance(a) >= luminance(b) ? [a, b] : [b, a];
  return (luminance(high) + 0.05) / (luminance(low) + 0.05);
};

/** Clarté perçue. C'est elle qui dit si l'œil sépare deux cellules voisines. */
const lstar = (rgb: RGB) => {
  const y = luminance(rgb);
  return y <= 216 / 24389 ? y * (24389 / 27) : Math.cbrt(y) * 116 - 16;
};

/** Composition alpha en sRGB — ce que fait le navigateur pour `rgb(x / a)`. */
const over = (fg: RGB, bg: RGB, alpha: number): RGB => [
  bg[0] + alpha * (fg[0] - bg[0]),
  bg[1] + alpha * (fg[1] - bg[1]),
  bg[2] + alpha * (fg[2] - bg[2]),
];

/** La valeur d'un token dans un thème, ou celle du sombre s'il ne la redéfinit pas. */
const valueOf = (theme: keyof typeof THEMES, name: string): string => {
  const value = THEMES[theme].get(name) ?? THEMES.sombre.get(name);
  if (value === undefined) throw new Error(`token ${name} absent des deux thèmes`);
  return value;
};

const colour = (theme: keyof typeof THEMES, name: string) => hex(valueOf(theme, name));

const alpha = (theme: keyof typeof THEMES, name: string) => Number(valueOf(theme, name));

const TONES = ['signal', 'effort', 'load', 'recover'] as const;

// ── 1. Les composantes RVB suivent leur hex ───────────

describe('composantes RVB', () => {
  for (const theme of Object.keys(THEMES) as (keyof typeof THEMES)[]) {
    it(`sont accordées à leur hex — thème ${theme}`, () => {
      const declared = [...THEMES[theme].keys()].filter((name) => name.endsWith('-rgb'));
      // Le thème clair redéclare les cinq triplets ; le sombre les porte tous.
      expect(declared.length).toBeGreaterThanOrEqual(5);

      for (const name of declared) {
        const value = valueOf(theme, name);
        // `--accent-rgb: var(--signal-rgb)` est une indirection, pas un triplet.
        if (value.startsWith('var(')) continue;

        const base = name.replace(/-rgb$/, '');
        expect(triple(value), `${name} doit valoir les composantes de ${base}`).toEqual(
          colour(theme, base),
        );
      }
    });
  }
});

// ── 2. Le thème clair n'oublie aucune couleur ─────────

describe('thème clair', () => {
  it('redéfinit chaque token de couleur du thème sombre', () => {
    // Tout ce qui porte un hex ou un `rgb(` littéral dépend de la clarté du fond.
    // Les indirections (`var(…)`) et les valeurs sans couleur ne sont pas concernées.
    const colourTokens = [...THEMES.sombre.entries()]
      .filter(([, value]) => /#[0-9a-f]{3,8}|rgb\(/i.test(value))
      .map(([name]) => name);

    expect(colourTokens.length).toBeGreaterThan(10);
    const missing = colourTokens.filter((name) => !THEMES.clair.has(name));
    expect(missing, 'tokens de couleur laissés à leur valeur sombre').toEqual([]);
  });

  it('redéfinit les composantes RVB et les opacités qui en dérivent', () => {
    for (const name of [
      '--signal-rgb',
      '--effort-rgb',
      '--load-rgb',
      '--recover-rgb',
      '--ink-rgb',
    ]) {
      expect(THEMES.clair.has(name), `${name} manque au thème clair`).toBe(true);
    }
    for (const name of ['--heat-a1', '--heat-a2', '--heat-a3', '--heat-a4']) {
      expect(THEMES.clair.has(name), `${name} manque au thème clair`).toBe(true);
    }
  });

  it('déclare son `color-scheme`, pour que les champs natifs suivent', () => {
    expect(THEMES.sombre.get('color-scheme')).toBeUndefined();
    expect(block(TOKENS, ':root {')).toContain('color-scheme: dark');
    expect(block(TOKENS, ":root[data-theme='light']")).toContain('color-scheme: light');
  });
});

// ── 3. La heatmap sépare ses quatre niveaux ───────────

describe('niveaux de heatmap', () => {
  /**
   * La grille est **toujours** posée dans une `Card` : l'opacité se compose sur
   * `--surface`, pas sur `--bg`. Et chaque piste choisit son accent — les quatre tons
   * doivent tenir, pas seulement le signal.
   *
   * Le seuil est celui que le thème sombre atteint aujourd'hui sur son ton le plus
   * serré (`recover`, ΔL* 6,6) : un thème n'a pas le droit d'être moins lisible que lui.
   */
  const PAS_MINIMAL = 6;

  for (const theme of Object.keys(THEMES) as (keyof typeof THEMES)[]) {
    for (const tone of TONES) {
      it(`${tone} — thème ${theme} : chaque palier se distingue du précédent`, () => {
        const surface = colour(theme, '--surface');
        const vide = lstar(colour(theme, '--surface-2'));
        const paliers = [1, 2, 3, 4].map((n) =>
          lstar(over(colour(theme, `--${tone}`), surface, alpha(theme, `--heat-a${n}`))),
        );

        let precedent = vide;
        paliers.forEach((niveau, index) => {
          const ecart = Math.abs(niveau - precedent);
          expect(
            ecart,
            `niveau ${index + 1} trop proche du ${index === 0 ? 'vide' : `niveau ${index}`}`,
          ).toBeGreaterThanOrEqual(PAS_MINIMAL);
          precedent = niveau;
        });
      });
    }
  }
});

// ── 4. Le contraste ───────────────────────────────────

describe('contraste', () => {
  /**
   * Deux écarts connus de la charte sombre, portés par `GuidelinesUI.html` et hors du
   * périmètre de ce lot : les corriger reviendrait à modifier la charte. Ils sont nommés
   * ici avec leur valeur actuelle pour plancher — ils ne peuvent plus empirer sans que
   * la batterie le dise, et le thème clair, lui, n'y a pas droit.
   */
  const TOLERE: Record<string, number> = {
    'sombre --ink-low / --bg': 3.3,
    'sombre --ink-low / --surface': 3,
    'sombre badge recover': 4.1,
  };

  const attendre = (nom: string, mesure: number, minimum: number) => {
    expect(mesure, nom).toBeGreaterThanOrEqual(TOLERE[nom] ?? minimum);
  };

  for (const theme of Object.keys(THEMES) as (keyof typeof THEMES)[]) {
    it(`texte à 4,5:1 — thème ${theme}`, () => {
      for (const fond of ['--bg', '--surface'] as const) {
        for (const encre of ['--ink', '--ink-mid', '--ink-low'] as const) {
          attendre(
            `${theme} ${encre} / ${fond}`,
            contrast(colour(theme, encre), colour(theme, fond)),
            4.5,
          );
        }
      }
    });

    it(`libellé des remplissages pleins à 4,5:1 — thème ${theme}`, () => {
      // `.primary`, le disque `⊕` et la bulle de l'assistant écrivent en `--bg` sur un
      // aplat de ton. C'est le contraste le plus facile à casser en changeant un accent.
      for (const tone of ['signal', 'recover'] as const) {
        attendre(
          `${theme} --bg sur --${tone}`,
          contrast(colour(theme, '--bg'), colour(theme, `--${tone}`)),
          4.5,
        );
      }
    });

    it(`texte de badge sur son fond dérivé à 4,5:1 — thème ${theme}`, () => {
      const fond = colour(theme, '--surface');
      const opacite = alpha(theme, '--badge-bg-a');
      for (const tone of TONES) {
        const ton = colour(theme, `--${tone}`);
        attendre(`${theme} badge ${tone}`, contrast(ton, over(ton, fond, opacite)), 4.5);
      }
    });

    it(`éléments d'interface à 3:1 — thème ${theme}`, () => {
      // Jauges, traits de graphique, anneau de focus : ils portent du sens sans texte.
      for (const tone of TONES) {
        attendre(
          `${theme} --${tone} / --surface`,
          contrast(colour(theme, `--${tone}`), colour(theme, '--surface')),
          3,
        );
      }
      attendre(
        `${theme} --signal / --bg`,
        contrast(colour(theme, '--signal'), colour(theme, '--bg')),
        3,
      );
    });
  }
});

// ── 5. `index.html` ne dérive pas des tokens ──────────

describe('script de pré-peinture', () => {
  /**
   * Le script en tête d'`index.html` doit répéter les deux `--bg` : il tourne avant
   * qu'aucune feuille de style ne soit chargée, et sans lui la page clignote. C'est la
   * seule duplication de couleur du projet, et elle est gardée ici.
   */
  it('reprend exactement le `--bg` des deux thèmes', () => {
    const litteraux = (INDEX.match(/#[0-9a-fA-F]{6}/g) ?? []).map((c) => c.toLowerCase());

    for (const theme of ['clair', 'sombre'] as const) {
      expect(litteraux, `le --bg du thème ${theme} est absent d'index.html`).toContain(
        valueOf(theme, '--bg').toLowerCase(),
      );
    }
  });

  it('pose `data-theme` avant que React ne démarre', () => {
    expect(INDEX).toContain('metric.theme');
    expect(INDEX).toContain('prefers-color-scheme: light');
    expect(INDEX.indexOf('dataset.theme')).toBeLessThan(INDEX.indexOf('src/main.tsx'));
  });
});

// ── 6. Le manifeste ne contredit pas le script ────────

describe('manifeste PWA', () => {
  /**
   * Troisième endroit où une couleur de fond est écrite en littéral — après `tokens.css`
   * et le script de pré-peinture —, et le seul qui n'a **qu'une** valeur là où
   * l'application en a deux : un manifeste ne porte pas de thème.
   *
   * C'est le sombre, celui de `:root`, parce que c'est le thème de la charte. La balise
   * `theme-color` du script gagne à l'exécution ; le manifeste ne décide que de l'écran
   * de démarrage à l'installation. Les laisser diverger donnerait un démarrage qui
   * clignote dans une couleur que l'application n'emploie nulle part.
   */
  const MANIFEST = JSON.parse(read('../../public/manifest.webmanifest')) as {
    background_color: string;
    theme_color: string;
    display: string;
    start_url: string;
    icons: { src: string; sizes: string; purpose: string }[];
  };

  it('reprend le `--bg` du thème sombre pour ses deux couleurs', () => {
    const sombre = valueOf('sombre', '--bg').toLowerCase();
    expect(MANIFEST.background_color.toLowerCase()).toBe(sombre);
    expect(MANIFEST.theme_color.toLowerCase()).toBe(sombre);
  });

  it('déclare une icône maskable — sans elle, Android rogne dans le motif', () => {
    const maskable = MANIFEST.icons.filter((icon) => icon.purpose.includes('maskable'));
    expect(maskable, 'aucune icône maskable').toHaveLength(1);
    expect(maskable[0]?.sizes).toBe('512x512');
  });

  it("s'ouvre en autonome depuis la racine", () => {
    // `standalone` est ce qui retire la barre d'adresse — et, sur iOS, la condition pour
    // que Web Push soit seulement proposé.
    expect(MANIFEST.display).toBe('standalone');
    expect(MANIFEST.start_url).toBe('/');
  });

  it("est référencé par `index.html`, avec l'icône qu'iOS exige en plus", () => {
    expect(INDEX).toContain('rel="manifest"');
    // iOS ignore le manifeste pour l'icône : sans cette balise, l'écran d'accueil
    // affiche une capture de la page.
    expect(INDEX).toContain('apple-touch-icon');
  });
});
