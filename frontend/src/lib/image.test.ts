import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Ce que les champs fichier acceptent — et le défaut que ce test empêche de revenir.
 *
 * Une photo de repas prise sur iPhone n'apparaissait ni en aperçu ni en vignette. Rien
 * n'échouait : l'envoi rendait `201`, le fichier était rangé, servi en `200` avec le bon
 * type. Tout marchait, rien ne s'affichait.
 *
 * La cause tenait dans un attribut. **iOS transcode une photo HEIC en JPEG au moment du
 * choix — sauf si « accept » annonce accepter le HEIC**, auquel cas il livre l'original.
 * Or aucun navigateur hors Safari ne sait décoder du HEIC, ni pour le canevas d'aperçu ni
 * pour un `<img>`.
 *
 * Trois des quatre champs fichier de l'application l'omettaient déjà. Le quatrième avait
 * dérivé, et rien ne le signalait.
 */

const SOURCE = join(process.cwd(), 'src');

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return tsxFiles(full);
    return full.endsWith('.tsx') && !full.includes('.test.') ? [full] : [];
  });
}

describe('champs fichier', () => {
  it('n’annonce jamais accepter le HEIC', () => {
    const fautifs = tsxFiles(SOURCE).filter((file) => {
      const source = readFileSync(file, 'utf8');
      return /accept="[^"]*heic/i.test(source);
    });

    expect(fautifs).toEqual([]);
  });

  it('accepte au moins JPEG partout où une image se choisit', () => {
    // Le pendant du test précédent : retirer le HEIC ne doit pas se faire en retirant
    // tout, ce qui laisserait le sélecteur sans filtre.
    const champs = tsxFiles(SOURCE).flatMap((file) => {
      const source = readFileSync(file, 'utf8');
      return [...source.matchAll(/accept="(image\/[^"]*)"/g)].map((match) => match[1]);
    });

    expect(champs.length).toBeGreaterThan(0);
    for (const accept of champs) {
      expect(accept).toContain('image/jpeg');
    }
  });
});
