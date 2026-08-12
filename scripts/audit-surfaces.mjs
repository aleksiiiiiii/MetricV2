/**
 * Audit des surfaces qui n'existent qu'après un appui, et des largeurs sous la cible.
 *
 * `audit-mobile.mjs` parcourt les douze écrans à 402 px et **ne touche à rien**. C'est
 * délibéré — un script qui clique au hasard sur des données réelles finit par en
 * supprimer. Mais cela laisse deux angles morts, et ils ont chacun coûté quelque chose :
 *
 * **Les feuilles ne sont jamais mesurées.** Une cible qui n'entre dans le DOM qu'après un
 * appui n'est jamais dans le compte. C'est ainsi que la poignée de `Sheet` est restée à
 * 32 px — sous le plancher `--tap` — sur six surfaces, pendant que les douze écrans
 * affichaient `0 cible < 44 px`. Trouvé le 12 août 2026, en ouvrant les feuilles à la main.
 *
 * **Une seule largeur est mesurée.** Les feuilles de style s'écrivent pour 390 px, qui est
 * le plancher de la charte, et un petit Android fait 360. 402 est la cible, pas la borne.
 *
 * Ce script comble les deux. Il ne redéfinit **rien** : la sonde, le pilotage CDP et les
 * planchers viennent de `audit-mobile.mjs`. Deux définitions de « ce qu'est un défaut »
 * donneraient deux comptes pour la même page, et c'est exactement le genre d'écart qu'on
 * ne remarque qu'au moment où il compte.
 *
 * ── Emploi ─────────────────────────────────────────────────────────────────────────
 *
 *   # mêmes préalables que l'audit : l'application, puis Chrome en --headless=new
 *   node scripts/audit-surfaces.mjs --base http://localhost:5173 --token "$JETON"
 *
 *   # une autre série de largeurs, et l'autre thème
 *   node scripts/audit-surfaces.mjs --base http://localhost:5173 --token "$JETON" \
 *     --largeurs 402,390,360,320 --theme light
 *
 * ── Ce qu'il n'est pas ─────────────────────────────────────────────────────────────
 *
 * Ce n'est pas un test de bout en bout. Il **ouvre** une surface et la mesure ; il ne
 * remplit aucun champ, ne valide aucun formulaire et n'arme aucune destruction. Chaque
 * appui est déclaré dans `SURFACES` ci-dessous, nommément — rien n'est cliqué qui ne soit
 * écrit ici. C'est ce qui permet de le lancer sans craindre pour les données.
 *
 * Quand une feuille est ajoutée à l'application, elle s'ajoute à cette table. Sans quoi
 * elle rejoint l'angle mort d'où celle-ci vient de sortir.
 */

import { Cdp, MIN_TAP, MIN_TEXT, arg, goto, probe } from './audit-mobile.mjs';

// ── Ce qu'on mesure ──────────────────────────────────

/** Les largeurs par défaut : la cible, le plancher de la charte, un petit Android. */
const LARGEURS = [
  [402, 874, 'iPhone 16 Pro'],
  [390, 844, 'plancher charte'],
  [360, 780, 'petit Android'],
];

/**
 * Les surfaces à ouvrir, une par ligne.
 *
 * `ouvre` est le **nom accessible** du bouton — son `aria-label` s'il en a un, son texte
 * sinon. Viser le nom accessible et non une classe CSS n'est pas un détail : c'est ce que
 * l'utilisateur de synthèse vocale entend, donc ce qui doit rester stable.
 */
const SURFACES = [
  // Les deux premières appartiennent à la barre d'onglets, présente sur **tous** les
  // écrans sous 960 px : la route n'est qu'un véhicule, et on en prend une qui rend
  // toujours. Partir de `/` ferait dépendre la mesure de la santé du tableau de bord.
  ['/activite', 'Noter', 'saisie rapide'],
  ['/activite', 'Plus', 'navigation « Plus »'],
  ['/activite', 'Nouvelle séance', 'feuille séance'],
  ['/activite', 'Nouvelle course', 'feuille course'],
  ['/activite', 'Gérer le catalogue', 'feuille catalogue'],
  ['/activite', 'Déclarer un exercice', 'catalogue depuis le journal'],
  ['/assistant', 'Mémoire', 'carnet de l’assistant'],
  ['/assistant', 'Discussions', 'fil de l’assistant'],
];

/** Le panneau d'une feuille. C'est lui qu'on mesure, pas l'écran resté derrière. */
const PANNEAU = 'document.querySelector(\'[role="dialog"]\')';

// ── Le parcours ──────────────────────────────────────

/**
 * Appuie sur un bouton désigné par son nom accessible.
 *
 * Rend `null` si aucun bouton ne porte ce nom : une surface qui a disparu doit se voir
 * dans le rapport, pas passer pour mesurée.
 */
async function ouvrir(cdp, nom) {
  return cdp.eval(`(() => {
    const cible = [...document.querySelectorAll('button, [role="button"]')].find((n) => {
      const nom = (n.getAttribute('aria-label') || n.textContent || '').trim();
      return nom === ${JSON.stringify(nom)};
    });
    if (!cible) return null;
    cible.click();
    return true;
  })()`);
}

async function main() {
  const base = arg('base', 'http://localhost:5173').replace(/\/$/, '');
  const token = arg('token', null);
  const port = arg('cdp', '9222');
  const theme = arg('theme', null);
  const largeurs = arg('largeurs', null);

  if (!token) throw new Error('--token est requis : toutes les surfaces sont derrière la session.');
  if (theme !== null && theme !== 'light' && theme !== 'dark') {
    throw new Error(`--theme attend « light » ou « dark », pas « ${theme} »`);
  }

  const tailles =
    largeurs === null
      ? LARGEURS
      : largeurs.split(',').map((l) => [Number(l.trim()), 844, `${l.trim()} px`]);

  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find((t) => t.type === 'page');
  if (!page) throw new Error('Aucun onglet. Chrome est-il lancé en --headless=new ?');

  const cdp = await Cdp.attach(page.webSocketDebuggerUrl);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  const lignes = [];

  for (const [largeur, hauteur, appareil] of tailles) {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: largeur,
      height: hauteur,
      deviceScaleFactor: 3,
      mobile: true,
    });
    await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });

    // La session et le thème se posent sur l'origine de l'application.
    await goto(cdp, `${base}/connexion`);
    await cdp.eval(`localStorage.setItem('metric.token', ${JSON.stringify(token)})`);
    if (theme !== null) {
      await cdp.eval(`localStorage.setItem('metric.theme', ${JSON.stringify(theme)})`);
    }

    for (const [route, bouton, nom] of SURFACES) {
      // Recharger l'écran entre deux surfaces : une feuille laissée ouverte masquerait
      // le bouton de la suivante, et `body { overflow: hidden }` survivrait au geste.
      await goto(cdp, `${base}${route}`);
      await new Promise((r) => setTimeout(r, 1600));

      const trouve = await ouvrir(cdp, bouton);
      if (trouve === null) {
        lignes.push({ appareil, nom, absent: bouton });
        continue;
      }
      await new Promise((r) => setTimeout(r, 700));

      const ouverte = await cdp.eval(`${PANNEAU} !== null`);
      if (!ouverte) {
        lignes.push({ appareil, nom, muet: bouton });
        continue;
      }

      lignes.push({ appareil, nom, largeur, ...(await cdp.eval(probe(PANNEAU))) });
    }
  }

  cdp.close();
  rapport(lignes, tailles, theme);
}

// ── Le rapport ───────────────────────────────────────

function rapport(lignes, tailles, theme) {
  console.log(`\nAudit des surfaces — ${tailles.map(([l]) => `${l}`).join(' · ')} px, DPR 3`);
  console.log(`Thème — ${theme === null ? 'préférence du navigateur' : `--theme ${theme}`}`);

  let defauts = 0;

  for (const [, , appareil] of tailles) {
    console.log(`\n━━ ${appareil} ━━`);
    console.log('surface                       cibles<44  zoom  min-px  déborde');
    console.log('─'.repeat(66));

    for (const l of lignes.filter((x) => x.appareil === appareil)) {
      if (l.absent !== undefined) {
        console.log(`${l.nom.padEnd(30)}bouton « ${l.absent} » introuvable`);
        defauts++;
        continue;
      }
      if (l.muet !== undefined) {
        console.log(`${l.nom.padEnd(30)}« ${l.muet} » n'ouvre aucune feuille`);
        defauts++;
        continue;
      }

      const petit = l.minTexte !== null && l.minTexte < MIN_TEXT;
      const mauvais = l.tapsTotal > 0 || l.zoome.length > 0 || petit || l.deborde;
      if (mauvais) defauts++;

      console.log(
        l.nom.padEnd(30) +
          String(l.tapsTotal).padStart(9) +
          String(l.zoome.length).padStart(6) +
          String(l.minTexte ?? '—').padStart(8) +
          (l.deborde ? '  OUI' : '   ok'),
      );

      for (const t of l.taps) console.log(`   ↳ cible ${t.l}×${t.h} — « ${t.texte} »`);
      if (l.tapsTotal > l.taps.length) {
        console.log(`   ↳ … et ${l.tapsTotal - l.taps.length} autres cibles`);
      }
      for (const z of l.zoome) console.log(`   ↳ champ < 16 px, iOS zoomera : ${z}`);
      if (petit) console.log(`   ↳ texte à ${l.minTexte} px sur « ${l.minTexteOu} »`);
    }
  }

  const total = lignes.length;
  console.log(
    defauts === 0
      ? `\n${total}/${total} surfaces sans défaut mesurable — plancher ${MIN_TAP} px, texte ${MIN_TEXT} px.`
      : `\n${total - defauts}/${total} surfaces sans défaut mesurable.`,
  );
  console.log("Et là encore : regarder les captures trouve ce qu'aucune mesure n'attrape.\n");
}

if (import.meta.main) await main();
