import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach } from 'vitest';

/**
 * jsdom 29 n'expose plus `localStorage`. On en pose un minimal plutôt que de laisser les
 * tests emprunter le chemin de repli en mémoire : ils doivent exercer le même code que
 * le navigateur.
 */
if (typeof globalThis.localStorage === 'undefined') {
  const entries = new Map<string, string>();

  const polyfill: Storage = {
    get length() {
      return entries.size;
    },
    key: (index) => [...entries.keys()][index] ?? null,
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => {
      entries.set(key, value);
    },
    removeItem: (key) => {
      entries.delete(key);
    },
    clear: () => {
      entries.clear();
    },
  };

  Object.defineProperty(globalThis, 'localStorage', { value: polyfill, configurable: true });
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
});
