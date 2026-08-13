/**
 * La règle de cache, vérifiée sans monter de service worker (`L15-02`, `L15-06`).
 *
 * C'est tout l'intérêt d'avoir écrit la décision dans une fonction pure : ces tests
 * tournent dans `make check`, à chaque exécution, là où un service worker demanderait un
 * navigateur, un contexte sécurisé et une installation.
 *
 * **Le test qui compte est le premier.** Les autres décrivent le confort ; celui-là garde
 * l'invariant — une mesure ne se met jamais en cache.
 */

import { describe, expect, it } from 'vitest';

import { isApi, strategyFor, type RequestShape } from './strategy';

const ORIGINE = 'https://metric.example';

const shape = (extra: Partial<RequestShape> = {}): RequestShape => ({
  appOrigin: ORIGINE,
  navigation: false,
  method: 'GET',
  ...extra,
});

const pour = (chemin: string, extra: Partial<RequestShape> = {}) =>
  strategyFor(new URL(chemin, ORIGINE), shape(extra));

describe('une mesure ne se met jamais en cache', () => {
  /**
   * La liste est celle des domaines qui servent des chiffres. Elle n'a pas besoin d'être
   * exhaustive — la règle porte sur le préfixe — mais l'écrire en clair fait que le jour
   * où quelqu'un ajoutera une exception « juste pour le tableau de bord », un test la
   * nommera.
   */
  const MESURES = [
    '/api/aggregates/dashboard',
    '/api/body/weight',
    '/api/activity/workouts',
    '/api/heatmap?tracks=eau',
    '/api/nutrition/meals',
    '/api/settings',
    '/api/notifications',
    '/api/assistant/threads',
  ];

  for (const chemin of MESURES) {
    it(`${chemin} passe par le réseau`, () => {
      expect(pour(chemin)).toBe('network');
    });
  }

  it("l'API l'emporte même sur une navigation", () => {
    // Une navigation vers `/api/...` n'arrive pas en usage normal — mais si elle
    // arrivait, la servir depuis la coquille rendrait du HTML pour du JSON.
    expect(pour('/api/body/weight', { navigation: true })).toBe('network');
  });

  it('aucune écriture ne passe par le cache', () => {
    for (const method of ['POST', 'PATCH', 'PUT', 'DELETE']) {
      expect(pour('/api/body/weight', { method })).toBe('network');
      // Y compris sur une adresse qui serait mise en cache en lecture : rejouer un
      // `POST` depuis un cache écrirait deux fois, et le projet n'a aucune annulation.
      expect(pour('/assets/app-a1b2c3.js', { method })).toBe('network');
    }
  });

  it('ne confond pas `/api` avec un chemin qui commence pareil', () => {
    expect(isApi('/api')).toBe(true);
    expect(isApi('/api/')).toBe(true);
    expect(isApi('/api/settings')).toBe(true);
    expect(isApi('/apiary')).toBe(false);
    expect(isApi('/apparence')).toBe(false);
  });
});

describe('la coquille', () => {
  it("sert les douze adresses de l'application", () => {
    for (const chemin of [
      '/',
      '/corps',
      '/activite',
      '/planning',
      '/objectif',
      '/assistant',
      '/routine',
      '/nutrition',
      '/assiduite',
      '/reglages',
      '/connexion',
      '/_kitchen-sink',
    ]) {
      expect(pour(chemin, { navigation: true }), chemin).toBe('shell');
    }
  });

  it("ne s'applique qu'aux navigations", () => {
    // La même adresse demandée en `fetch` — un préchargement de route, par exemple —
    // n'est pas un document et n'a pas à recevoir la coquille.
    expect(pour('/corps')).toBe('network');
  });
});

describe('les ressources immuables', () => {
  it('sont mises en cache', () => {
    expect(pour('/assets/index-4f3a2b.js')).toBe('asset');
    expect(pour('/assets/index-9c8d7e.css')).toBe('asset');
    expect(pour('/fonts/SpaceGrotesk-Bold.woff2')).toBe('asset');
    expect(pour('/icons/icon-192.png')).toBe('asset');
    expect(pour('/manifest.webmanifest')).toBe('asset');
  });
});

describe('ce qui est refusé par défaut', () => {
  it('ne met jamais en cache une autre origine', () => {
    // Un service push, une police distante, une image d'ailleurs : on ne conserve rien
    // qu'on ne sait pas invalider.
    for (const absolue of [
      'https://fcm.googleapis.com/fcm/send/abc',
      'https://fonts.gstatic.com/s/x.woff2',
      'http://localhost:8000/api/health',
    ]) {
      expect(strategyFor(new URL(absolue), shape()), absolue).toBe('network');
    }
  });

  it('laisse passer par le réseau ce qui n’a pas été nommé', () => {
    // Le défaut est de **ne pas** mettre en cache : une ressource ajoutée demain et
    // oubliée dans la liste coûte une requête, jamais un chiffre faux.
    expect(pour('/sw.js')).toBe('network');
    expect(pour('/quelque-chose-de-neuf.json')).toBe('network');
  });
});
