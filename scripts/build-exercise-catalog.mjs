#!/usr/bin/env node
/**
 * Fige le catalogue d'exercices de Cadence Tabata dans le dépôt (**C5**).
 *
 * La source est `hasaneyldrm/exercises-dataset`, `data/exercises.json` — 17 Mo dont on ne
 * garde que quatre champs par exercice. Le résultat fait une centaine de kilo-octets et
 * vit dans `backend/app/domains/activity/exercise_catalog.json`.
 *
 * ## Ce qu'on ne reprend pas, et pourquoi
 *
 * Les images et les GIF appartiennent à **Gym visual** et ne sont redistribuables que sous
 * leurs conditions ; le champ qui les nomme (`media_id`) reste donc dehors. Les données —
 * noms, zones du corps, matériel, cibles — sont sous licence MIT, et ce sont les seules
 * qu'on fige. Le fichier produit porte une clé `license` qui le dit, réécrite à chaque
 * génération : un fichier de données sans provenance devient introuvable en six mois.
 *
 * ## Pourquoi figer plutôt qu'appeler Cadence
 *
 * Cadence sert le même catalogue à `<base>/exercise-db/catalog.json`. L'appeler ferait
 * dépendre la saisie d'un circuit de la disponibilité d'une autre application, et
 * ajouterait un état « catalogue injoignable » à un écran qui n'en a pas besoin. Le prix
 * admis : ce fichier vieillit si le jeu de données grandit, et c'est cette commande qui
 * le rattrape.
 *
 *     node scripts/build-exercise-catalog.mjs
 */

import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SOURCE =
  'https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/HEAD/data/exercises.json';

const LICENSE =
  'Exercise data from github.com/hasaneyldrm/exercises-dataset, MIT License, ' +
  'Copyright (c) 2026 Hasan Emir Yıldırım. Media excluded (© Gym visual).';

const OUT = join(
  dirname(fileURLToPath(import.meta.url)),
  '..',
  'backend',
  'app',
  'domains',
  'activity',
  'exercise_catalog.json',
);

/** Les valeurs distinctes d'un champ, triées — l'ordre décide des indices, il doit être stable. */
function index(values) {
  return [...new Set(values)].sort();
}

const response = await fetch(SOURCE);
if (!response.ok) throw new Error(`source injoignable : HTTP ${response.status}`);
const source = await response.json();

const bodyParts = index(source.map((item) => item.body_part));
const equipment = index(source.map((item) => item.equipment));
const targets = index(source.map((item) => item.target));

// Trié par nom, et pas laissé dans l'ordre de la source : le fichier est relu par un
// humain quand une correspondance surprend, et une liste de 1324 lignes non triée ne se
// relit pas. Le tri rend aussi le diff lisible d'une génération à l'autre.
const exercises = source
  .map((item) => ({
    n: item.name,
    b: bodyParts.indexOf(item.body_part),
    e: equipment.indexOf(item.equipment),
    t: targets.indexOf(item.target),
  }))
  .sort((left, right) => left.n.localeCompare(right.n, 'en'));

const catalog = {
  license: LICENSE,
  source: SOURCE,
  count: exercises.length,
  bodyParts,
  equipment,
  targets,
  exercises,
};

writeFileSync(OUT, `${JSON.stringify(catalog)}\n`, 'utf8');
console.log(`${exercises.length} exercices → ${OUT}`);
