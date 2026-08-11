import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  THEME_KEY,
  applyTheme,
  readMode,
  resolveTheme,
  storeMode,
  systemTheme,
  watchSystem,
} from './theme';

/** Doublure de `matchMedia` : jsdom ne fournit pas de préférence système. */
function preferSystem(light: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();

  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query.includes('light') ? light : !light,
      media: query,
      addEventListener: (_: string, fn: (event: MediaQueryListEvent) => void) => {
        listeners.add(fn);
      },
      removeEventListener: (_: string, fn: (event: MediaQueryListEvent) => void) => {
        listeners.delete(fn);
      },
    })),
  );

  return {
    /** Simule l'utilisateur qui bascule son appareil. */
    basculer: (versLeClair: boolean) => {
      for (const fn of listeners) fn({ matches: versLeClair } as MediaQueryListEvent);
    },
    get abonnes() {
      return listeners.size;
    },
  };
}

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('mode enregistré', () => {
  it('vaut « système » quand rien n’a été choisi', () => {
    expect(readMode()).toBe('system');
  });

  it('relit un choix explicite', () => {
    storeMode('light');
    expect(localStorage.getItem(THEME_KEY)).toBe('light');
    expect(readMode()).toBe('light');
  });

  it('efface la clé plutôt que d’écrire le défaut', () => {
    storeMode('dark');
    storeMode('system');
    expect(localStorage.getItem(THEME_KEY)).toBeNull();
    expect(readMode()).toBe('system');
  });

  it('ignore une valeur que l’application ne connaît pas', () => {
    // Une clé écrite par une version plus ancienne, ou à la main.
    localStorage.setItem(THEME_KEY, 'sepia');
    expect(readMode()).toBe('system');
  });
});

describe('résolution', () => {
  it('suit l’appareil en mode « système »', () => {
    preferSystem(true);
    expect(systemTheme()).toBe('light');
    expect(resolveTheme('system')).toBe('light');

    preferSystem(false);
    expect(resolveTheme('system')).toBe('dark');
  });

  it('le choix explicite l’emporte sur l’appareil', () => {
    preferSystem(true);
    expect(resolveTheme('dark')).toBe('dark');

    preferSystem(false);
    expect(resolveTheme('light')).toBe('light');
  });

  it('retombe sur le sombre quand `matchMedia` n’existe pas', () => {
    vi.stubGlobal('matchMedia', undefined);
    expect(systemTheme()).toBe('dark');
    expect(resolveTheme('system')).toBe('dark');
  });
});

describe('application', () => {
  it('pose l’attribut que lit `tokens.css`', () => {
    applyTheme('light');
    expect(document.documentElement.dataset.theme).toBe('light');

    applyTheme('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('fait suivre les deux balises que lit le système', () => {
    document.head.innerHTML =
      '<meta name="color-scheme" content="dark"><meta name="theme-color" content="#0B0F16">';

    applyTheme('light');
    expect(document.querySelector('meta[name="color-scheme"]')).toHaveAttribute('content', 'light');

    applyTheme('dark');
    expect(document.querySelector('meta[name="color-scheme"]')).toHaveAttribute('content', 'dark');
  });

  it('ne casse pas si les balises sont absentes', () => {
    document.head.innerHTML = '';
    expect(() => {
      applyTheme('light');
    }).not.toThrow();
  });
});

describe('abonnement au système', () => {
  it('rapporte les basculements, puis se désabonne', () => {
    const media = preferSystem(false);
    const vus: string[] = [];

    const desabonner = watchSystem((theme) => {
      vus.push(theme);
    });
    expect(media.abonnes).toBe(1);

    media.basculer(true);
    media.basculer(false);
    expect(vus).toEqual(['light', 'dark']);

    desabonner();
    expect(media.abonnes).toBe(0);
  });

  it('rend un désabonnement inoffensif quand `matchMedia` manque', () => {
    vi.stubGlobal('matchMedia', undefined);
    const desabonner = watchSystem(() => {});
    expect(() => {
      desabonner();
    }).not.toThrow();
  });
});
