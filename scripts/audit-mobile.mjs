/**
 * Audit mobile des écrans (`L17-07`).
 *
 * Un test vérifie ce qu'on a pensé à vérifier. Sur les quatre lots précédant la refonte,
 * huit défauts sont sortis en regardant la page et zéro de la batterie — ce script est ce
 * qui rend « regarder la page » rejouable après chaque phase, au lieu d'être un geste
 * qu'on refait de mémoire.
 *
 * Sans dépendance : Chrome piloté en CDP depuis le `WebSocket` natif de Node. Ni
 * Playwright, ni `ws`, ni Puppeteer — trois façons de plus d'avoir une version qui dérive.
 *
 * ── Emploi ─────────────────────────────────────────────────────────────────────────
 *
 *   # 1. l'application, dans un terminal — VÉRIFIER le port annoncé, 5173 est souvent pris
 *   make dev
 *
 *   # 2. Chrome, dans un autre — tué ensuite PAR SON --user-data-dir, jamais par pkill -f
 *   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
 *     --headless=new --remote-debugging-port=9222 \
 *     --no-first-run --user-data-dir=/tmp/metric-audit
 *
 *   # 3. l'audit
 *   node scripts/audit-mobile.mjs --base http://localhost:5174 --token "$JETON"
 *
 *   # …et le même dans l'autre thème, captures rangées à part
 *   node scripts/audit-mobile.mjs --base http://localhost:5174 --token "$JETON" \
 *     --theme light --shots audit-shots-clair
 *
 * `--theme light|dark` force le thème comme le ferait un choix dans `/reglages`. Sans
 * lui, le thème suit la préférence de Chrome — le sombre en headless : un audit qui ne
 * le passe pas ne regarde qu'une moitié de l'application.
 *
 * Sans `--token`, seules les pages publiques sont visitées : `/connexion` et
 * `/_kitchen-sink`. C'est déjà de quoi vérifier toute la charte — mais aucun des douze
 * écrans, qui sont derrière la session.
 *
 * ── Ce qu'il mesure ────────────────────────────────────────────────────────────────
 *
 * Les quatre mesures de `docs/front.md` §5, plus deux que la refonte a values :
 *
 * * **La plus petite taille de texte rendue.** Plancher 12 px.
 * * **Le texte d'un SVG mis à l'échelle** — la seule taille qui ment. `font-size: 9px`
 *   dans un `viewBox` de 720 unités rendu à 336 px arrive à l'écran en 4,2 px, et
 *   `getComputedStyle` lit 9 sans broncher. Il faut diviser par la largeur rendue.
 * * **La hauteur avant le premier chiffre** : ce qu'il faut faire défiler avant de lire
 *   une donnée. C'est la mesure de « est-ce que ça donne envie ».
 */

import { mkdir, writeFile } from 'node:fs/promises';
import { argv } from 'node:process';

// ── L'appareil ───────────────────────────────────────

/** iPhone 16 Pro, portrait : 2622 × 1206 physiques à DPR 3. */
const DEVICE = { width: 402, height: 874, deviceScaleFactor: 3, mobile: true };

/** Le plancher de lisibilité décidé en phase A. Rien ne descend en dessous. */
export const MIN_TEXT = 12;

/** Le plancher tactile (`--tap`). Un doigt ne vise pas au pixel. */
export const MIN_TAP = 44;

const PUBLIC_ROUTES = [
  ['/connexion', 'connexion'],
  ['/_kitchen-sink', 'kitchen-sink'],
];

const PRIVATE_ROUTES = [
  ['/', 'accueil'],
  ['/corps', 'corps'],
  ['/activite', 'activite'],
  // Les deux sous-pages d'Activité. Même règle que la table `SURFACES` de
  // `audit-surfaces.mjs` : une page qui s'ajoute à l'application s'ajoute ici, sans quoi
  // elle rejoint l'angle mort dont le lot vient de la sortir.
  ['/activite/catalogue', 'activite-catalogue'],
  ['/activite/statistiques', 'activite-statistiques'],
  ['/activite/seances', 'activite-seances'],
  ['/activite/charges', 'activite-charges'],
  // La composition assistée. Elle est mesurée **vide** : sa proposition demande un
  // appel à un modèle, et un audit qui en déclenche un à chaque passage taperait un
  // service externe pour une mesure de gabarit. L'état vide est aussi le premier que
  // l'écran montre, donc celui qui se regarde le plus.
  ['/activite/creer', 'activite-creer'],
  ['/planning', 'planning'],
  ['/objectif', 'objectif'],
  ['/assistant', 'assistant'],
  ['/routine', 'routine'],
  ['/nutrition', 'nutrition'],
  ['/assiduite', 'assiduite'],
  ['/reglages', 'reglages'],
];

// ── Pilotage CDP ─────────────────────────────────────

export function arg(name, fallback) {
  const index = argv.indexOf(`--${name}`);
  return index === -1 ? fallback : argv[index + 1];
}

export class Cdp {
  #socket;
  #next = 1;
  #pending = new Map();

  static async attach(url) {
    const cdp = new Cdp();
    cdp.#socket = new WebSocket(url);
    cdp.#socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      const waiter = cdp.#pending.get(message.id);
      if (waiter === undefined) return;
      cdp.#pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message));
      else waiter.resolve(message.result);
    });
    await new Promise((resolve, reject) => {
      cdp.#socket.addEventListener('open', resolve, { once: true });
      cdp.#socket.addEventListener('error', reject, { once: true });
    });
    return cdp;
  }

  send(method, params = {}) {
    const id = this.#next++;
    return new Promise((resolve, reject) => {
      this.#pending.set(id, { resolve, reject });
      this.#socket.send(JSON.stringify({ id, method, params }));
    });
  }

  /** Évalue dans la page et rend la valeur, en propageant une exception plutôt qu'un `undefined`. */
  async eval(expression) {
    const { result, exceptionDetails } = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (exceptionDetails) throw new Error(exceptionDetails.exception?.description ?? 'échec');
    return result.value;
  }

  close() {
    this.#socket.close();
  }
}

// ── La sonde, exécutée dans la page ──────────────────

/**
 * Écrit comme une chaîne parce qu'elle est évaluée dans le contexte de la page, pas ici.
 * Elle ne renvoie que des nombres et des chaînes : tout ce qui traverse CDP est du JSON.
 */
export function probe(racine = 'document.documentElement') {
  return `(() => {
  const doc = ${racine};

  // 1. cibles sous le plancher tactile — un élément invisible n'est pas une cible
  const visible = (node) => {
    // « sr-only » masque un champ tout en le gardant dans le document : c'est le motif
    // d'un input[type=file] dont le vrai bouton est son label. Il mesure 1 x 1 px
    // et personne ne le vise — le compter comme cible sous plancher est un faux positif,
    // et un faux positif répété finit par faire ignorer le vrai.
    if (node.classList.contains('sr-only') || node.closest('.sr-only')) return false;
    const box = node.getBoundingClientRect();
    return box.width > 0 && box.height > 0 && getComputedStyle(node).visibility !== 'hidden';
  };
  // Une cellule de grille annuelle est exemptée, et c'est la seule exemption du script.
  // 53 semaines × 44 px feraient 2 332 px de large : le plancher tactile et une grille
  // d'un an sont géométriquement incompatibles. Ce que la grille doit garantir est
  // ailleurs — que l'information d'un jour soit atteignable autrement qu'en visant sa
  // cellule. Laisser ces 366 cellules dans le compte noierait tout le reste.
  const exempt = (node) => node.closest('[class*="grid"]') && node.matches('[class*="cell"]');

  const taps = [...doc.querySelectorAll('a,button,input,select,textarea,summary,[role="button"]')]
    .filter(visible)
    .filter((node) => !exempt(node))
    .map((node) => ({
      texte: (node.textContent || node.getAttribute('aria-label') || node.type || '').trim().slice(0, 40),
      h: Math.round(node.getBoundingClientRect().height),
      l: Math.round(node.getBoundingClientRect().width),
    }))
    .filter((m) => m.h < ${MIN_TAP} || m.l < ${MIN_TAP});

  // 2. débordement horizontal de la page elle-même
  const deborde = doc.scrollWidth > doc.clientWidth;

  // 3. champs qui feront zoomer iOS
  const zoome = [...doc.querySelectorAll('input,select,textarea')]
    .filter(visible)
    .filter((n) => parseFloat(getComputedStyle(n).fontSize) < 16)
    .map((n) => n.name || n.id || n.type);

  // 4. alignement du contenu sur l'en-tête
  const ancre = doc.querySelector('header a');
  const titre = doc.querySelector('main h1, main h2');
  const alignement =
    ancre && titre
      ? Math.round(ancre.getBoundingClientRect().left - titre.getBoundingClientRect().left)
      : null;

  // 5. plus petite taille de texte rendue — seuls les nœuds qui portent du texte
  let minTexte = Infinity;
  let minTexteOu = '';
  for (const node of doc.querySelectorAll('*')) {
    if (node.closest('svg')) continue;
    const propre = [...node.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim());
    if (!propre || !visible(node)) continue;
    const px = parseFloat(getComputedStyle(node).fontSize);
    if (px < minTexte) {
      minTexte = px;
      minTexteOu = node.className?.toString().slice(0, 30) || node.tagName;
    }
  }

  // 6. texte d'un SVG mis à l'échelle — la seule taille qui ment
  const svgs = [];
  for (const svg of doc.querySelectorAll('svg')) {
    const vb = svg.viewBox?.baseVal?.width;
    const rendu = svg.getBoundingClientRect().width;
    if (!vb || !rendu) continue;
    const facteur = rendu / vb;
    for (const texte of svg.querySelectorAll('text')) {
      const px = parseFloat(getComputedStyle(texte).fontSize) * facteur;
      if (px < ${MIN_TEXT}) svgs.push({ declare: parseFloat(getComputedStyle(texte).fontSize), rendu: Math.round(px * 10) / 10 });
    }
  }

  // 7. hauteur avant le premier chiffre : ce qu'il faut faire défiler pour lire une donnée
  const chiffre = [...doc.querySelectorAll('main .num, main [class*="statValue"], main [class*="tatValue"]')]
    .filter(visible)[0];
  const avant = chiffre ? Math.round(chiffre.getBoundingClientRect().top + window.scrollY) : null;

  // 8. le thème réellement peint, et le fond calculé qui en découle. Un --theme qui
  //    n'aurait pas pris rendrait douze captures d'un thème pour l'autre, sans que rien
  //    ne le signale. (Pas d'accent grave ici : la sonde vit dans un gabarit de chaîne.)
  const theme = doc.dataset.theme || '(absent)';
  const fond = getComputedStyle(document.body).backgroundColor;

  return {
    theme,
    fond,
    taps: taps.slice(0, 8),
    tapsTotal: taps.length,
    deborde,
    zoome,
    alignement,
    minTexte: minTexte === Infinity ? null : Math.round(minTexte * 10) / 10,
    minTexteOu,
    svgs: svgs.slice(0, 4),
    svgsTotal: svgs.length,
    avant,
    hauteur: Math.round(doc.scrollHeight),
  };
})()`;
}

// ── Le parcours ──────────────────────────────────────

async function main() {
  const base = arg('base', 'http://localhost:5174').replace(/\/$/, '');
  const token = arg('token', null);
  const port = arg('cdp', '9222');
  const shots = arg('shots', 'audit-shots');
  const theme = arg('theme', null);

  if (theme !== null && theme !== 'light' && theme !== 'dark') {
    throw new Error(`--theme attend « light » ou « dark », pas « ${theme} »`);
  }

  const routes = token ? [...PUBLIC_ROUTES, ...PRIVATE_ROUTES] : PUBLIC_ROUTES;
  await mkdir(shots, { recursive: true });

  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find((t) => t.type === 'page');
  if (!page) throw new Error('Aucun onglet. Chrome est-il lancé en --headless=new ?');

  const cdp = await Cdp.attach(page.webSocketDebuggerUrl);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', DEVICE);
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });

  // La session et le thème se posent sur l'origine de l'application, pas avant de
  // l'avoir chargée. `/connexion` est publique : elle sert d'origine même sans jeton.
  if (token || theme !== null) {
    await goto(cdp, `${base}/connexion`);
    if (token) {
      await cdp.eval(`localStorage.setItem('metric.token', ${JSON.stringify(token)})`);
    }
    if (theme !== null) {
      // La même clé que `/reglages` écrit : l'audit exerce le chemin réel, il ne pose
      // pas l'attribut à la main.
      await cdp.eval(`localStorage.setItem('metric.theme', ${JSON.stringify(theme)})`);
    }
  }

  const lignes = [];

  for (const [route, nom] of routes) {
    await goto(cdp, `${base}${route}`);
    // Le temps que les requêtes du domaine reviennent et que l'écran quitte « chargement… ».
    await new Promise((r) => setTimeout(r, 1400));

    let mesure;
    try {
      mesure = await cdp.eval(probe());
    } catch (error) {
      lignes.push({ route, erreur: String(error.message).slice(0, 80) });
      continue;
    }

    const { data } = await cdp.send('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: true,
    });
    await writeFile(`${shots}/${nom}.png`, Buffer.from(data, 'base64'));

    lignes.push({ route, ...mesure });
  }

  cdp.close();
  rapport(lignes, theme);
}

export async function goto(cdp, url) {
  const arrive = new Promise((resolve) => {
    const onMessage = (event) => {
      if (JSON.parse(event.data).method === 'Page.loadEventFired') resolve();
    };
    cdp.send('Page.navigate', { url }).then(() => setTimeout(resolve, 4000));
    void onMessage;
  });
  await arrive;
  await new Promise((r) => setTimeout(r, 600));
}

// ── Le rapport ───────────────────────────────────────

function rapport(lignes, theme) {
  const ok = (bon) => (bon ? '  ok' : 'FAUX');
  const peint = [...new Set(lignes.map((l) => l.theme).filter(Boolean))];
  const demande = theme === null ? 'préférence du navigateur' : `--theme ${theme}`;
  console.log(`\nAudit mobile — ${DEVICE.width} × ${DEVICE.height}, DPR ${DEVICE.deviceScaleFactor}`);
  console.log(`Thème — demandé : ${demande} · peint : ${peint.join(', ') || '—'}`);
  if (theme !== null && (peint.length !== 1 || peint[0] !== theme)) {
    console.log('  ⚠ le thème peint ne suit pas celui demandé');
  }
  console.log('');
  console.log('écran          cibles<44  déborde  zoom  align  min-px  svg<12  1er chiffre  hauteur');
  console.log('─'.repeat(92));

  let defauts = 0;

  for (const l of lignes) {
    if (l.erreur) {
      console.log(`${l.route.padEnd(15)}ERREUR : ${l.erreur}`);
      defauts++;
      continue;
    }
    const petit = l.minTexte !== null && l.minTexte < MIN_TEXT;
    const mauvais =
      l.tapsTotal > 0 ||
      l.deborde ||
      l.zoome.length > 0 ||
      (l.alignement !== null && l.alignement !== 0) ||
      petit ||
      l.svgsTotal > 0;
    if (mauvais) defauts++;

    console.log(
      l.route.padEnd(15) +
        String(l.tapsTotal).padStart(9) +
        ok(!l.deborde).padStart(9) +
        String(l.zoome.length).padStart(6) +
        String(l.alignement ?? '—').padStart(7) +
        String(l.minTexte ?? '—').padStart(8) +
        String(l.svgsTotal).padStart(8) +
        String(l.avant ?? '—').padStart(13) +
        String(l.hauteur).padStart(9),
    );
  }

  console.log('\nDétail des défauts\n' + '─'.repeat(92));
  for (const l of lignes) {
    if (l.erreur) continue;
    const petit = l.minTexte !== null && l.minTexte < MIN_TEXT;
    if (
      l.tapsTotal === 0 &&
      !l.deborde &&
      l.zoome.length === 0 &&
      l.svgsTotal === 0 &&
      !petit &&
      (l.alignement === null || l.alignement === 0)
    )
      continue;
    console.log(`\n${l.route}`);
    if (l.alignement !== 0 && l.alignement !== null)
      console.log(`  alignement en-tête / titre : ${l.alignement} px d'écart`);
    if (l.deborde) console.log(`  la page déborde horizontalement`);
    if (l.zoome.length) console.log(`  champs < 16 px (iOS zoomera) : ${l.zoome.join(', ')}`);
    if (l.minTexte !== null && l.minTexte < MIN_TEXT)
      console.log(`  texte à ${l.minTexte} px sur « ${l.minTexteOu} »`);
    for (const s of l.svgs)
      console.log(`  SVG : ${s.declare} px déclarés → ${s.rendu} px rendus`);
    if (l.svgsTotal > l.svgs.length) console.log(`  … et ${l.svgsTotal - l.svgs.length} autres textes SVG`);
    for (const t of l.taps) console.log(`  cible ${t.l}×${t.h} — « ${t.texte} »`);
    if (l.tapsTotal > l.taps.length) console.log(`  … et ${l.tapsTotal - l.taps.length} autres cibles`);
  }

  console.log(`\n${lignes.length - defauts}/${lignes.length} écrans sans défaut mesurable.`);
  console.log('Et maintenant, regarder les captures — c\'est ce qui trouve le reste.\n');
}

if (import.meta.main) await main();
