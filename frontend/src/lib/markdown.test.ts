/**
 * Le markdown que les modèles écrivent réellement.
 *
 * Ce fichier ne teste pas « markdown » mais **ce que l'assistant produit** : des
 * paragraphes, des listes, du gras, et le reste laissé tel quel. La fonction est pure —
 * elle ne rend aucun HTML —, ce qui est précisément ce qui la rend testable ici sans
 * monter un écran.
 */

import { describe, expect, it } from 'vitest';

import { parseMarkdown, parseSpans } from './markdown';

describe('emphase', () => {
  it('reconnaît le gras, l’italique et le code', () => {
    expect(parseSpans('un **gras**, un *italique* et du `code`')).toEqual([
      { text: 'un ' },
      { text: 'gras', bold: true },
      { text: ', un ' },
      { text: 'italique', italic: true },
      { text: ' et du ' },
      { text: 'code', code: true },
    ]);
  });

  it('rend une ligne sans marque telle quelle', () => {
    // Le tableau ne doit jamais être vide : un paragraphe entier disparaîtrait.
    expect(parseSpans('rien de particulier')).toEqual([{ text: 'rien de particulier' }]);
  });

  it('laisse le code l’emporter sur l’emphase', () => {
    // Le seul cas d'imbrication que les modèles produisent.
    expect(parseSpans('`**a**`')).toEqual([{ text: '**a**', code: true }]);
  });
});

describe('blocs', () => {
  it('réunit les lignes d’un même paragraphe', () => {
    // Un modèle coupe ses phrases à 80 colonnes ; les rendre telles quelles donnerait des
    // retours à la ligne au milieu des phrases sur un téléphone.
    expect(parseMarkdown('Tu tournes à 1,8 séance\npar semaine.')).toEqual([
      { kind: 'paragraph', spans: [{ text: 'Tu tournes à 1,8 séance par semaine.' }] },
    ]);
  });

  it('sépare deux paragraphes sur une ligne vide', () => {
    expect(parseMarkdown('Premier.\n\nSecond.')).toHaveLength(2);
  });

  it('reconnaît une liste à puces, quel que soit son tiret', () => {
    const blocks = parseMarkdown('- un\n* deux\n• trois');

    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: 'list', ordered: false });
    expect(blocks[0]).toHaveProperty('items.length', 3);
  });

  it('reconnaît une liste numérotée', () => {
    const blocks = parseMarkdown('1. un\n2) deux');

    expect(blocks[0]).toMatchObject({ kind: 'list', ordered: true });
  });

  it('n’enchaîne pas deux listes de nature différente', () => {
    const blocks = parseMarkdown('- puce\n1. numéro');

    expect(blocks).toHaveLength(2);
  });

  it('ramène tous les titres à un seul niveau', () => {
    expect(parseMarkdown('# Un\n## Deux\n### Trois').every((b) => b.kind === 'heading')).toBe(true);
  });

  it('laisse tel quel ce qu’il ne reconnaît pas', () => {
    // Un tableau markdown reste du texte : c'est le comportement d'avant, et il vaut
    // mieux qu'un rendu à moitié juste.
    const blocks = parseMarkdown('| a | b |\n| - | - |');

    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: 'paragraph' });
  });

  it('ne rend rien sur une réponse vide', () => {
    expect(parseMarkdown('')).toEqual([]);
  });
});
