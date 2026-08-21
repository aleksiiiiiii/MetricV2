/**
 * Le choix des étiquettes d'axe.
 *
 * Ce fichier existe pour un défaut qu'aucune mesure ne pouvait attraper : le SVG rendait
 * exactement ce qu'on lui demandait, chaque `<text>` était bien placé, et une sonde du DOM
 * lisait des rectangles corrects. Ce qui était faux, c'était le **choix des index** — et
 * ça ne se voyait qu'en regardant la page.
 *
 * On l'éprouve sur la géométrie réelle du composant, `LEFT = 78` et `RIGHT = 706` : des
 * bornes inventées vérifieraient une autre application que celle qu'on livre.
 */

import { describe, expect, it } from 'vitest';

import { axisLabels, axisWidth } from './chart-axis';

const LEFT = 78;
const RIGHT = 706;

/** L'abscisse d'un point, comme `Chart` la calcule. */
function scale(count: number) {
  return (index: number) => LEFT + (index * (RIGHT - LEFT)) / (count - 1);
}

/** Les bords de chaque étiquette retenue, dans l'ordre où elles sont dessinées. */
function spans(labels: string[], floor?: number) {
  const count = labels.length;
  const x = scale(count);
  return axisLabels(labels, count, x, floor).map(({ index, anchor }) => {
    const width = axisWidth(labels[index] ?? '');
    const centre = x(index);
    if (anchor === 'start') return [centre, centre + width] as const;
    if (anchor === 'end') return [centre - width, centre] as const;
    return [centre - width / 2, centre + width / 2] as const;
  });
}

const dates = (count: number) =>
  Array.from(
    { length: count },
    (_item, index) => `${String((index % 28) + 1).padStart(2, '0')}/07`,
  );

describe('axisLabels', () => {
  it('ne laisse jamais deux étiquettes se recouvrir', () => {
    // Le cas exact du défaut : treize points de série hebdomadaire sur le tableau de bord.
    // L'écran demandait une étiquette sur deux, et « 28/05 » se peignait par-dessus
    // « 11/06 » — la première, ancrée à gauche, occupait 78 à 166, et la troisième,
    // centrée sur 183, commençait à 139.
    for (const count of [2, 3, 5, 8, 13, 21, 34, 90, 365]) {
      const bornes = spans(dates(count));
      for (let position = 1; position < bornes.length; position += 1) {
        const gauche = bornes[position]?.[0] ?? 0;
        const droite = bornes[position - 1]?.[1] ?? 0;
        expect(gauche, `${String(count)} points, étiquette ${String(position)}`).toBeGreaterThan(
          droite,
        );
      }
    }
  });

  it('ne déborde jamais du cadre', () => {
    // La première s'aligne par sa gauche et la dernière par sa droite : centrées, elles
    // sortaient d'un côté sur les graduations verticales et de l'autre hors du cadre.
    for (const count of [2, 5, 13, 90]) {
      const bornes = spans(dates(count));
      expect(bornes[0]?.[0]).toBeGreaterThanOrEqual(LEFT);
      expect(bornes[bornes.length - 1]?.[1]).toBeLessThanOrEqual(RIGHT);
    }
  });

  it('borne la plage des deux côtés dès que la place existe', () => {
    // Une plage dont on ne voit pas la fin ne se lit pas.
    const choisies = axisLabels(dates(13), 13, scale(13));

    expect(choisies[0]?.index).toBe(0);
    expect(choisies[0]?.anchor).toBe('start');
    expect(choisies[choisies.length - 1]?.index).toBe(12);
    expect(choisies[choisies.length - 1]?.anchor).toBe('end');
  });

  it('espace les étiquettes régulièrement', () => {
    // Un pas uniforme, et non un remplissage glouton : des dates espacées irrégulièrement
    // se lisent comme une échelle qui ment sur ses intervalles.
    //
    // **Un seul écart peut être plus grand, et c'est celui d'avant la fin** : la borne de
    // droite tombe où la série finit, pas sur un multiple du pas, et l'étiquette qui la
    // toucherait saute. Un trou avant la dernière date se lit ; une date sous une autre,
    // non.
    const choisies = axisLabels(dates(90), 90, scale(90));
    const pas = choisies
      .slice(1)
      .map((label, position) => label.index - (choisies[position]?.index ?? 0));
    const courants = pas.slice(0, -1);

    expect(new Set(courants).size).toBe(1);
    expect(pas[pas.length - 1]).toBeGreaterThanOrEqual(courants[0] ?? 0);
  });

  it('respecte un plancher demandé par l’écran', () => {
    // `floor` peut demander **moins** d'étiquettes…
    const serrées = axisLabels(dates(90), 90, scale(90));
    const clairsemées = axisLabels(dates(90), 90, scale(90), 40);

    expect(clairsemées.length).toBeLessThan(serrées.length);
  });

  it('n’obéit pas à un plancher qui ferait se chevaucher', () => {
    // …mais jamais **plus** : un appelant ne connaît ni la largeur d'une étiquette ni
    // l'écart entre deux points. C'est exactement ce que faisaient les deux écrans.
    const forcé = axisLabels(dates(13), 13, scale(13), 1);
    const bornes = spans(dates(13), 1);

    expect(forcé.length).toBeLessThan(13);
    for (let position = 1; position < bornes.length; position += 1) {
      expect(bornes[position]?.[0] ?? 0).toBeGreaterThan(bornes[position - 1]?.[1] ?? 0);
    }
  });

  it('tient les cas dégénérés sans rien inventer', () => {
    expect(axisLabels([], 0, scale(2))).toEqual([]);
    expect(axisLabels(['26/07'], 1, scale(2))).toEqual([{ index: 0, anchor: 'start' }]);
  });

  it('laisse tomber la borne de droite plutôt que de la superposer', () => {
    // Deux points et des étiquettes plus larges que la moitié du cadre : elles ne tiennent
    // pas toutes les deux. C'est la seconde qui saute, jamais l'origine de la plage — sans
    // quoi le graphique commencerait à une date qu'on ne voit pas.
    //
    // 628 unités entre les deux bornes : au-delà de ~18 caractères, il n'y a plus la place
    // pour deux.
    const larges = ['lundi 1 juillet 2026', 'mardi 2 juillet 2026'];
    const choisies = axisLabels(larges, 2, scale(2));

    expect(choisies).toHaveLength(1);
    expect(choisies[0]?.index).toBe(0);
  });
});
