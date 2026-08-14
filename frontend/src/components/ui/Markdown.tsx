/**
 * Affiche ce qu'un modèle a écrit, avec sa mise en forme.
 *
 * **Aucun HTML n'est injecté.** Le texte vient d'un service tiers, et l'application lui
 * envoie par ailleurs des descriptions écrites par l'utilisateur : un rendu qui passe par
 * `dangerouslySetInnerHTML` ouvrirait une surface d'injection dans les deux sens. Ici, la
 * structure vient de [lib/markdown.ts](../../lib/markdown.ts) — une fonction pure, testée
 * à part — et ce composant ne fait qu'en construire des nœuds React.
 *
 * Il rend un fragment et non un conteneur : la bulle qui l'accueille garde sa propre mise
 * en page, et le composant ne décide rien de ce qui l'entoure.
 */

import type { ReactNode } from 'react';

import { parseMarkdown, type Span } from '@/lib/markdown';

import styles from './Markdown.module.css';

function spans(list: Span[]): ReactNode[] {
  return list.map((span, index) => {
    const key = `${String(index)}-${span.text.slice(0, 12)}`;
    if (span.code) {
      return (
        <code className={styles.code} key={key}>
          {span.text}
        </code>
      );
    }
    if (span.bold) return <strong key={key}>{span.text}</strong>;
    if (span.italic) return <em key={key}>{span.text}</em>;
    return <span key={key}>{span.text}</span>;
  });
}

export function Markdown({ children }: { children: string }) {
  const blocks = parseMarkdown(children);

  return (
    <>
      {blocks.map((block, index) => {
        const key = String(index);

        if (block.kind === 'heading') {
          // Un seul niveau visuel pour `#`, `##` et `###` : dans une bulle de discussion,
          // trois tailles de titre feraient une hiérarchie que la réponse n'a pas.
          return (
            <p className={styles.heading} key={key}>
              {spans(block.spans)}
            </p>
          );
        }

        if (block.kind === 'list') {
          const items = block.items.map((item, position) => (
            <li key={`${key}-${String(position)}`}>{spans(item)}</li>
          ));
          return block.ordered ? (
            <ol className={styles.list} key={key}>
              {items}
            </ol>
          ) : (
            <ul className={styles.list} key={key}>
              {items}
            </ul>
          );
        }

        return (
          <p className={styles.paragraph} key={key}>
            {spans(block.spans)}
          </p>
        );
      })}
    </>
  );
}
