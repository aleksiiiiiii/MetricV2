import { fileURLToPath, URL } from 'node:url';

import { defineConfig } from 'vite';

/**
 * Bâtit le service worker, à part du reste (`L15-02`).
 *
 * Une seconde configuration plutôt qu'un `vite-plugin-pwa`, et c'est un **écart assumé**
 * au §0 du ROADMAP. Le plugin apporterait Workbox et sa propre grammaire de stratégies —
 * or la règle qui protège les mesures doit être une fonction pure et testée
 * (`src/sw/strategy.ts`). Écrite dans la configuration d'un plugin, elle ne serait vue
 * par aucun test, et son défaut caractéristique est invisible à l'écran : une page
 * normale, avec les chiffres d'hier.
 *
 * Le coût de l'écart est une trentaine de lignes de worker. Le bénéfice est seize
 * assertions dans `make check`.
 *
 * Deux réglages ne sont pas négociables :
 *
 * * **`iife` et non `es`.** Un worker en module demande `{ type: 'module' }` à
 *   l'enregistrement, que Safari n'accepte que depuis 16.4 — et iOS est la cible de ce
 *   lot. Le format classique marche partout.
 * * **`emptyOutDir: false`.** Ce build passe *après* le build principal, qui vient de
 *   remplir `dist/`. Le laisser à son défaut effacerait l'application.
 */
export default defineConfig({
  build: {
    outDir: 'dist',
    emptyOutDir: false,
    // Un service worker vit à une adresse stable, à la racine de sa portée : pas
    // d'empreinte dans le nom, sinon le navigateur ne retrouve pas celui qu'il a installé.
    lib: {
      entry: fileURLToPath(new URL('./src/sw/index.ts', import.meta.url)),
      formats: ['iife'],
      name: 'MetricServiceWorker',
      fileName: () => 'sw.js',
    },
    sourcemap: true,
  },
});
