import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
// `vitest/config` et non `vite` : c'est ce qui rend la clé `test` typée.
import { defineConfig } from 'vitest/config';

/**
 * Le frontend ne connaît que `/api` : l'URL du backend n'est jamais compilée dans le
 * bundle. En développement le proxy l'envoie sur uvicorn, en production le
 * reverse-proxy s'en charge (`OPS-01`).
 *
 * Le port de l'API est lu dans l'environnement : la console de développement
 * (`make console`) bascule sur un autre port si 8000 est occupé, et le proxy doit
 * suivre. Valeur de repli identique au défaut d'uvicorn.
 */
const API_PORT = process.env.METRIC_API_PORT ?? '8000';

/**
 * Le même relais pour le serveur de développement et pour `vite preview`.
 *
 * `preview` sert le **build de production**, et c'est le seul endroit où le service
 * worker existe (`L15-02`) : sans ce relais, la vérification du lot L15 se ferait sur une
 * application dont chaque appel `/api` rendrait un `404` du serveur de fichiers. Le
 * manque n'était pas visible avant le L15, parce que rien n'obligeait à passer par le
 * build pour regarder un écran.
 */
const proxy = {
  '/api': {
    target: `http://127.0.0.1:${API_PORT}`,
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy,
  },
  preview: {
    port: 4173,
    proxy,
    // Un tunnel HTTPS présente l'application sous un nom qui n'est pas le nôtre —
    // `xxx.trycloudflare.com`. Sans cette autorisation, Vite refuse la requête avec un
    // « Blocked request », et l'on cherche longtemps du côté du tunnel.
    allowedHosts: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
});
