/**
 * Quelles étiquettes d'axe dessiner, et par quel bord chacune s'aligne.
 *
 * Module **pur** : il ne rend rien, ne lit aucun style, ne connaît pas React. C'est le
 * même parti pris que [sw/strategy.ts](../../sw/strategy.ts) — ce qui décide se teste sur
 * des valeurs fixes, ce qui dessine se regarde.
 *
 * ## Pourquoi ce calcul a quitté les écrans
 *
 * Il y vivait sous la forme d'un `labelEvery={Math.ceil(points.length / 8)}` — deux
 * écrans, deux estimations, et **aucun des deux ne connaît la géométrie du graphique**.
 * Sur treize points, le tableau de bord demandait une étiquette sur deux : la première,
 * ancrée à gauche, occupait les unités 78 à 166 du `viewBox`, et la troisième, centrée sur
 * 183, commençait à 139. « 28/05 » se peignait par-dessus « 11/06 ».
 *
 * **Aucune mesure ne pouvait l'attraper** : le SVG rendait exactement ce qu'on lui
 * demandait, chaque `<text>` était bien placé, et une sonde du DOM lit des rectangles
 * corrects. Le défaut était dans le choix des index, et il ne se voyait qu'en regardant.
 *
 * Le pas se déduit maintenant de ce qui le décide vraiment : la largeur d'une étiquette
 * contre l'écart entre deux points.
 *
 * ## Les deux bornes, et celle qui saute
 *
 * La première et la dernière disent la plage lue, et une plage dont on ne voit pas la fin
 * ne se lit pas. La dernière s'aligne par sa droite, et c'est **l'avant-dernière retenue
 * qui saute** si elle la recouvre — jamais la borne.
 */

/**
 * Taille du texte d'axe, en unités du `viewBox`.
 *
 * Le `font-size` d'un `<text>` SVG s'exprime dans le système de coordonnées du `viewBox` :
 * les 26 px que pose `Chart.module.css` sont donc 26 unités ici, quelle que soit la
 * largeur à laquelle le graphique est rendu.
 *
 * On prend la **plus grande** des trois tailles de la feuille — celle du téléphone —, qui
 * est le cas le plus serré. Au-delà de 600 px la police descend à 18 et il y aurait la
 * place pour deux ou trois dates de plus ; les compter demanderait d'observer la largeur
 * réelle du SVG, donc un `ResizeObserver` et un état, pour un gain qui ne se voit que sur
 * un écran large — celui qui manque le moins de place.
 */
const AXIS_SIZE = 26;

/** Chasse de JetBrains Mono, et l'interlettrage que `.axis` lui ajoute. */
const MONO_ADVANCE = 0.6;
const AXIS_TRACKING = 0.08;

/** Blanc minimal entre deux étiquettes. En deçà, elles se touchent sans se recouvrir. */
const LABEL_GAP = 14;

export type AxisAnchor = 'start' | 'middle' | 'end';

export interface AxisLabel {
  index: number;
  anchor: AxisAnchor;
}

/** Largeur d'une étiquette d'axe, en unités du `viewBox`. */
export function axisWidth(label: string): number {
  return label.length * AXIS_SIZE * (MONO_ADVANCE + AXIS_TRACKING);
}

/**
 * Les étiquettes à dessiner.
 *
 * `x` rend l'abscisse d'un point dans le `viewBox` : c'est elle qui porte la géométrie,
 * et ce module n'a donc aucune constante de mise en page à connaître.
 *
 * `floor` est un **plancher** du pas, jamais un plafond. Un appelant peut en vouloir
 * moins ; il ne peut pas en vouloir plus sans risquer le chevauchement, puisqu'il ne
 * connaît ni la largeur d'une étiquette ni l'écart entre deux points.
 */
export function axisLabels(
  labels: readonly string[],
  count: number,
  x: (index: number) => number,
  floor = 1,
): AxisLabel[] {
  if (count < 1) return [];
  if (count < 2) return [{ index: 0, anchor: 'start' }];

  const last = count - 1;

  /** L'espace horizontal qu'occupe une étiquette, bord gauche et bord droit. */
  const span = (index: number): readonly [number, number] => {
    const width = axisWidth(labels[index] ?? '');
    const centre = x(index);
    if (index === 0) return [centre, centre + width];
    if (index === last) return [centre - width, centre];
    return [centre - width / 2, centre + width / 2];
  };

  const spacing = (x(last) - x(0)) / last;
  const widest = Math.max(...labels.slice(0, count).map(axisWidth), 1);

  // Un pas **uniforme** plutôt qu'un remplissage glouton de gauche à droite : des dates
  // espacées irrégulièrement se lisent comme une échelle qui ment sur ses intervalles.
  //
  // Le pas se calibre sur la **première** paire, qui est la plus serrée : l'étiquette
  // d'origine est ancrée par sa gauche, donc elle s'étend d'une largeur entière vers la
  // droite, là où une étiquette centrée n'en occupe qu'une demie. Il faut donc `1,5 ×
  // largeur` entre les deux premiers points, contre `1 × largeur` entre deux suivants.
  //
  // Calibrer sur `1 × largeur` — ce que faisait la première version — donnait un pas trop
  // court : la deuxième étiquette était rejetée par la garde de recouvrement, et l'axe se
  // retrouvait avec un premier intervalle **double** des autres. Correct, mais laid, et
  // c'est exactement l'échelle irrégulière qu'on cherche à éviter.
  const needed = spacing > 0 ? Math.ceil((1.5 * widest + LABEL_GAP) / spacing) : count;
  const stride = Math.max(Math.max(1, Math.floor(floor)), needed);

  const kept: AxisLabel[] = [{ index: 0, anchor: 'start' }];
  const lastSpan = span(last);

  for (let index = stride; index < last; index += stride) {
    const [left, right] = span(index);
    const previous = span(kept[kept.length - 1]?.index ?? 0)[1];
    if (left < previous + LABEL_GAP) continue;
    if (right + LABEL_GAP > lastSpan[0]) continue;
    kept.push({ index, anchor: 'middle' });
  }

  // La borne de droite ne se dessine que si la place existe encore. Sur deux points très
  // rapprochés, mieux vaut une date lisible que deux qui se chevauchent.
  const keptRight = span(kept[kept.length - 1]?.index ?? 0)[1];
  if (lastSpan[0] >= keptRight + LABEL_GAP) kept.push({ index: last, anchor: 'end' });

  return kept;
}
