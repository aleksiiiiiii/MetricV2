/**
 * Récupère Space Grotesk et JetBrains Mono depuis Google Fonts et les installe
 * localement dans `public/fonts/`, puis génère `src/styles/fonts.css`.
 *
 * Pourquoi ne pas garder le `<link>` CDN des guidelines : une dépendance réseau à un
 * tiers sur le chemin critique du premier rendu, un point de fuite de données, et une
 * PWA (`L15`) qui ne peut pas fonctionner hors-ligne. Les fichiers sont versionnés dans
 * le dépôt — licence OFL, redistribution autorisée.
 *
 * Relancer avec `npm run fonts` uniquement si l'on change de graisse ou de famille.
 */

import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const FONT_DIR = resolve(HERE, '../public/fonts');
const CSS_OUT = resolve(HERE, '../src/styles/fonts.css');

/** Subsets conservés : le français a besoin de latin-ext pour « œ ». */
const KEEP_SUBSETS = new Set(['latin', 'latin-ext']);

const FAMILIES = [
  { name: 'Space Grotesk', slug: 'space-grotesk', weights: [400, 500, 600, 700] },
  { name: 'JetBrains Mono', slug: 'jetbrains-mono', weights: [400, 500, 700] },
];

// Sans user-agent moderne, Google renvoie du woff/ttf au lieu du woff2.
const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

/** Découpe la réponse Google en blocs `@font-face` étiquetés par subset. */
function parseFaces(css) {
  const faces = [];
  const blocks = css.matchAll(/\/\*\s*([^*]+?)\s*\*\/\s*(@font-face\s*\{[^}]+\})/g);

  for (const [, subset, block] of blocks) {
    if (!KEEP_SUBSETS.has(subset)) continue;

    const weight = block.match(/font-weight:\s*(\d+)/)?.[1];
    const url = block.match(/src:\s*url\(([^)]+)\)/)?.[1];
    const range = block.match(/unicode-range:\s*([^;]+);/)?.[1];
    if (!weight || !url || !range) continue;

    faces.push({ subset, weight: Number(weight), url, range: range.trim() });
  }
  return faces;
}

async function fetchOk(url, init) {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} — ${url}`);
  }
  return response;
}

async function main() {
  await mkdir(FONT_DIR, { recursive: true });
  await mkdir(dirname(CSS_OUT), { recursive: true });

  const rules = [];
  let downloaded = 0;

  for (const family of FAMILIES) {
    const query = `${family.name.replace(/ /g, '+')}:wght@${family.weights.join(';')}`;
    const css = await (
      await fetchOk(`https://fonts.googleapis.com/css2?family=${query}&display=swap`, {
        headers: { 'User-Agent': UA },
      })
    ).text();

    const faces = parseFaces(css);
    if (faces.length === 0) {
      throw new Error(`Aucun @font-face exploitable pour ${family.name}`);
    }

    for (const face of faces) {
      const file = `${family.slug}-${face.weight}-${face.subset}.woff2`;
      const bytes = Buffer.from(await (await fetchOk(face.url)).arrayBuffer());
      await writeFile(resolve(FONT_DIR, file), bytes);
      downloaded += 1;

      rules.push(
        [
          '@font-face {',
          `  font-family: '${family.name}';`,
          '  font-style: normal;',
          `  font-weight: ${face.weight};`,
          '  font-display: swap;',
          `  src: url('/fonts/${file}') format('woff2');`,
          `  unicode-range: ${face.range};`,
          '}',
        ].join('\n'),
      );
    }
  }

  const header = [
    '/* ═══════════════════════════════════════════════════',
    '   METRIC — Polices servies localement',
    '   Généré par `npm run fonts`. Ne pas éditer à la main.',
    '   Space Grotesk · JetBrains Mono — licence OFL.',
    '   ═══════════════════════════════════════════════════ */',
    '',
  ].join('\n');

  await writeFile(CSS_OUT, `${header}\n${rules.join('\n\n')}\n`);

  // Le fichier est versionné et passe sous `prettier --check` comme le reste de `src/`.
  // Sans ce passage, la génération laisse un `unicode-range` sur une seule ligne longue,
  // que prettier replie — et `make check` échoue sur un fichier que personne n'a édité.
  await new Promise((resolve, reject) => {
    const prettier = spawn('npx', ['prettier', '--write', CSS_OUT], { stdio: 'inherit' });
    prettier.on('error', reject);
    prettier.on('close', (code) =>
      code === 0 ? resolve() : reject(new Error(`prettier a rendu ${code}`)),
    );
  });

  console.log(`${downloaded} fichiers woff2 → public/fonts/, ${rules.length} règles → fonts.css`);
}

await main();
