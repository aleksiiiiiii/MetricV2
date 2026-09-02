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
  // Les deux boutons « Nouvelle séance » et « Nouvelle course » ont laissé la place à un
  // assistant qui demande la nature à sa première étape (`C06`). C'est cette première
  // étape qu'on mesure ici ; les suivantes demandent de remplir des champs, ce que ce
  // script s'interdit — il ouvre et il mesure, il ne saisit rien.
  ['/activite', 'Enregistrer une activité', 'assistant d’activité'],
  // Le catalogue avait deux lignes ici. Il n'est plus une feuille mais une page
  // (`/activite/catalogue`), donc il est mesuré par `audit-mobile.mjs` comme les autres :
  // le laisser ici rendait « bouton introuvable » sur trois largeurs, ce qui est un
  // constat exact et une ligne de rapport inutile.
  ['/assistant', 'Mémoire', 'carnet de l’assistant'],
  ['/assistant', 'Discussions', 'fil de l’assistant'],
  // La feuille d'ajout d'un repas et ses quatre modes (C05). Elle s'ajoute ici le jour
  // où elle est écrite, pas le jour où un défaut s'y découvre.
  ['/nutrition', 'Ajouter un repas', 'modes de saisie d’un repas'],
  // Le détail d'une charge — courbe et ligne de trente points. Le nom du bouton est celui
  // de l'exercice, donc il dépend des données : `Butterfly` est celui de la base réelle.
  // Sur une base où il n'existe pas, la ligne rend « bouton introuvable », ce qui est un
  // constat exact — on remplace alors le nom par un exercice réellement présent.
  ['/activite/charges', 'Butterfly', 'détail d’une charge'],
];

/** Le panneau d'une feuille. C'est lui qu'on mesure, pas l'écran resté derrière. */
const PANNEAU = 'document.querySelector(\'[role="dialog"]\')';

/**
 * **Qui peint le bas de l'écran ?** — la mesure qui manquait.
 *
 * Les feuilles déclaraient `z-index: 60` contre 30 pour la barre d'onglets, et se
 * faisaient pourtant recouvrir sur leurs 56 derniers pixels : rendues dans `<main>`,
 * dont le fondu d'entrée crée un contexte d'empilement, leur 60 y était enfermé. Trois
 * feuilles sur quatre étaient dans ce cas, et aucune mesure de taille de cible ne le
 * voyait — la cible existait, faisait ses 44 px, et n'était pas atteignable.
 *
 * `elementFromPoint` répond ce que le **doigt** touche, ce qu'aucune lecture de
 * `z-index` ne dit. Trois points, parce qu'une barre haute de 56 px se rate en n'en
 * sondant qu'un.
 */
const RECOUVREMENT = `(() => {
  const panneau = ${'document.querySelector(\'[role="dialog"]\')'};
  if (!panneau) return { recouvert: null };
  const h = window.innerHeight;
  const x = window.innerWidth / 2;
  const dehors = [4, 28, 56].filter((marge) => {
    const el = document.elementFromPoint(x, h - marge);
    return el !== null && !panneau.contains(el);
  });
  return { recouvert: dehors.length };
})()`;

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

      lignes.push({
        appareil,
        nom,
        largeur,
        ...(await cdp.eval(probe(PANNEAU))),
        ...(await cdp.eval(RECOUVREMENT)),
      });
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
    console.log('surface                       cibles<44  zoom  min-px  déborde  recouvert');
    console.log('─'.repeat(77));

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
      // Un panneau dont un point bas rend autre chose que lui est recouvert : le doigt
      // n'atteint pas ce qui s'y trouve, quelle que soit la taille de la cible.
      const couvert = (l.recouvert ?? 0) > 0;
      const mauvais = l.tapsTotal > 0 || l.zoome.length > 0 || petit || l.deborde || couvert;
      if (mauvais) defauts++;

      console.log(
        l.nom.padEnd(30) +
          String(l.tapsTotal).padStart(9) +
          String(l.zoome.length).padStart(6) +
          String(l.minTexte ?? '—').padStart(8) +
          (l.deborde ? '  OUI' : '   ok') +
          (couvert ? '        OUI' : '         ok'),
      );

      for (const t of l.taps) console.log(`   ↳ cible ${t.l}×${t.h} — « ${t.texte} »`);
      if (l.tapsTotal > l.taps.length) {
        console.log(`   ↳ … et ${l.tapsTotal - l.taps.length} autres cibles`);
      }
      for (const z of l.zoome) console.log(`   ↳ champ < 16 px, iOS zoomera : ${z}`);
      if (couvert) {
        console.log(
          `   ↳ ${l.recouvert} des 3 points bas rendent autre chose que la feuille — ` +
            'elle est recouverte, très probablement par la barre d’onglets',
        );
      }
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
