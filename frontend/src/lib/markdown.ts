/**
 * Le markdown qu'un modèle écrit réellement, et rien de plus.
 *
 * Les réponses de l'assistant s'affichaient en **texte brut** : le `white-space: pre-wrap`
 * de la bulle rendait les retours à la ligne, et c'est tout. Une réponse qui énumère trois
 * causes de stagnation arrivait donc avec ses `- ` et ses `**` en clair, ce qui est
 * exactement le contraire de ce que le modèle voulait faire — souligner ce qui compte.
 *
 * ## Ce module rend une structure, pas du HTML
 *
 * `parseMarkdown` ne produit aucune chaîne de balises, et l'affichage n'emploie **jamais**
 * `dangerouslySetInnerHTML`. Ce n'est pas une précaution de principe : le texte vient d'un
 * service tiers, à qui l'on envoie par ailleurs des descriptions écrites par
 * l'utilisateur. Un rendu qui passe par du HTML expose une surface d'injection dans les
 * deux sens ; un rendu qui produit des nœuds React n'en a aucune, et il coûte le même
 * travail.
 *
 * ## Ce qui est reconnu, et pourquoi pas le reste
 *
 * Six formes, choisies sur ce que les modèles gratuits produisent quand on leur demande
 * une réponse en français à une question sur des chiffres :
 *
 * * les paragraphes, séparés par une ligne vide ;
 * * les listes à puces — `-`, `*` ou `•` ;
 * * les listes numérotées — `1.`, `2)` ;
 * * les titres `#` à `###`, ramenés à **un seul** niveau visuel ;
 * * `**gras**` et `*italique*` ;
 * * `` `code` ``, pour un nom de fichier ou une valeur.
 *
 * Le reste — tableaux, citations, liens, blocs de code — n'est pas reconnu et **s'affiche
 * tel quel**, ce qui est le comportement d'avant. Un parseur complet demanderait une
 * dépendance ; celle-ci tient en cent lignes et se teste.
 */

/** Un morceau de texte, avec la seule emphase qui le concerne. */
export interface Span {
  text: string;
  bold?: boolean;
  italic?: boolean;
  code?: boolean;
}

export type Block =
  | { kind: 'paragraph'; spans: Span[] }
  | { kind: 'heading'; spans: Span[] }
  | { kind: 'list'; ordered: boolean; items: Span[][] };

/** `- ceci`, `* cela`, `• autre chose`. */
const BULLET = /^\s{0,3}[-*•]\s+(.*)$/;

/** `1. ceci`, `2) cela`. */
const NUMBERED = /^\s{0,3}\d{1,2}[.)]\s+(.*)$/;

/** `# Titre`, jusqu'à trois dièses. */
const HEADING = /^\s{0,3}#{1,3}\s+(.*)$/;

/**
 * Découpe une ligne en morceaux emphasés.
 *
 * Un seul passage, gauche à droite, et **le code gagne** : dans `` `**a**` ``, les
 * astérisques appartiennent au code et ne sont pas de l'emphase. C'est le seul cas
 * d'imbrication que les modèles produisent, et le prendre dans le bon ordre suffit.
 */
export function parseSpans(line: string): Span[] {
  const spans: Span[] = [];
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)/g;
  let last = 0;

  for (const match of line.matchAll(pattern)) {
    const at = match.index;
    if (at > last) spans.push({ text: line.slice(last, at) });

    const [whole] = match;
    if (whole.startsWith('`')) {
      spans.push({ text: whole.slice(1, -1), code: true });
    } else if (whole.startsWith('**')) {
      spans.push({ text: whole.slice(2, -2), bold: true });
    } else {
      spans.push({ text: whole.slice(1, -1), italic: true });
    }
    last = at + whole.length;
  }

  if (last < line.length) spans.push({ text: line.slice(last) });
  // Une ligne sans aucune marque reste une ligne : le tableau ne doit jamais être vide,
  // sinon un paragraphe entier disparaîtrait de l'écran.
  return spans.length > 0 ? spans : [{ text: line }];
}

export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  // Les lignes d'un même paragraphe sont réunies par un espace, comme en markdown : un
  // modèle coupe souvent ses phrases à 80 colonnes, et les rendre telles quelles
  // donnerait des retours à la ligne au milieu des phrases sur un téléphone.
  let paragraph: string[] = [];

  function flush(): void {
    if (paragraph.length === 0) return;
    blocks.push({ kind: 'paragraph', spans: parseSpans(paragraph.join(' ')) });
    paragraph = [];
  }

  for (const raw of source.split('\n')) {
    const line = raw.trimEnd();

    if (line.trim() === '') {
      flush();
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      blocks.push({ kind: 'heading', spans: parseSpans(heading[1] ?? '') });
      continue;
    }

    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    const item = bullet ?? numbered;
    if (item) {
      flush();
      const ordered = numbered !== null;
      const previous = blocks[blocks.length - 1];
      // Une puce à la suite d'une liste de même nature la prolonge, au lieu d'ouvrir une
      // seconde liste — ce qui se verrait à l'écran comme deux blocs séparés.
      if (previous?.kind === 'list' && previous.ordered === ordered) {
        previous.items.push(parseSpans(item[1] ?? ''));
      } else {
        blocks.push({ kind: 'list', ordered, items: [parseSpans(item[1] ?? '')] });
      }
      continue;
    }

    paragraph.push(line.trim());
  }

  flush();
  return blocks;
}
