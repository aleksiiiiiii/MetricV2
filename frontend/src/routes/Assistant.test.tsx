import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import type { AssistantView, ChatReply } from '@/features/assistant/api';
import { createQueryClient } from '@/lib/query';

import { Assistant } from './Assistant';

/**
 * Écran Assistant (`L14b-07`).
 *
 * Ces tests portent sur ce qu'un test d'API ne peut pas voir :
 *
 * * une note retenue par l'assistant est **écrite**, annoncée, et se retire (`IA-10`) —
 *   vérifié sur les requêtes réellement parties, pas sur l'intention du code ;
 * * le carnet reste entier **sans clé API**, alors que la conversation disparaît ;
 * * le condensé envoyé au modèle est affiché, ce qui rend `IA-09` vérifiable à l'écran ;
 * * le garde-fou médical est là **avant** la première question, et ne se ferme pas.
 */

const MEMORY: AssistantView = {
  memories: [
    {
      id: 0,
      token: 'jeton-note',
      memory_id: 'abc123',
      created: '2026-07-12',
      topic: 'blessure',
      note: 'Genou droit sensible depuis le 12 juillet',
      source: 'ai',
    },
  ],
  topics: ['blessure', 'sommeil', 'autre'],
  today: '2026-08-06',
};

const EMPTY_MEMORY: AssistantView = {
  memories: [],
  topics: ['blessure', 'autre'],
  today: '2026-08-06',
};

const REPLY: ChatReply = {
  thread_id: 'fil-1',
  title: 'Où j’en suis cette semaine',
  reply: 'Tu tournes à 1,8 séance par semaine, contre 2,4 le mois dernier.',
  remember: [
    {
      id: 0,
      token: 'jeton-note',
      memory_id: 'n1',
      created: '2026-08-06',
      topic: 'sommeil',
      note: 'Je dors mal les soirs de séance tardive',
      source: 'ai',
    },
  ],
  context: [
    'Nous sommes le jeudi 06/08/2026',
    'Séances par semaine : 1,8 séances (moyenne des 4 dernières semaines complètes)',
  ],
};

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

function stub(options: { memory?: AssistantView; reply?: ChatReply; aiEnabled?: boolean } = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    // `request` n'envoie que des chaînes : le typage de `fetch` est plus large que
    // l'usage, et `String(objet)` rendrait « [object Object] » sans le dire.
    const url = input as string;
    calls.push({ url, init });

    if (url.includes('/api/ai/status')) {
      return Promise.resolve(
        json(200, { enabled: options.aiEnabled ?? true, message: 'aucune clé configurée' }),
      );
    }
    if (url.includes('/api/assistant/chat')) {
      return Promise.resolve(json(200, options.reply ?? REPLY));
    }
    return Promise.resolve(json(200, options.memory ?? MEMORY));
  });

  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderScreen() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Toaster>
          <Assistant />
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function writes(): Call[] {
  return calls.filter((call) => (call.init?.method ?? 'GET') !== 'GET');
}

/** Corps d'une écriture, décodé. `null` si la requête n'est jamais partie. */
function bodyOf(fragment: string): Record<string, unknown> | null {
  const call = writes().find((item) => item.url.endsWith(fragment));
  if (!call) return null;
  return JSON.parse(call.init?.body as string) as Record<string, unknown>;
}

/** La note du carnet de référence, sans assertion de non-nullité. */
function storedNote(): string {
  const first = MEMORY.memories[0];
  if (!first) throw new Error('ce carnet de référence porte une note');
  return first.note;
}

/** La note que la réponse de référence propose de retenir. */
function proposedNote(): { topic: string; note: string } {
  const first = REPLY.remember[0];
  if (!first) throw new Error('cette réponse de référence propose une note');
  return first;
}

/** La ligne du carnet qui porte une note donnée. */
function itemOf(note: HTMLElement): HTMLElement {
  const item = note.closest('li');
  if (!item) throw new Error('la note est rendue dans une ligne de liste');
  return item;
}

async function askSomething(): Promise<void> {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText('Ta question'), 'Pourquoi je stagne ?');
  await user.click(screen.getByRole('button', { name: 'Demander' }));
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── Le garde-fou médical (`IA-12`) ────────────────────

describe('garde-fou médical', () => {
  it('est affiché avant même la première question', async () => {
    stub();
    renderScreen();

    expect(await screen.findByText(/n’est pas médecin/)).toBeInTheDocument();
    expect(screen.getByText(/professionnel de santé/)).toBeInTheDocument();
  });

  it("reste affiché quand l'assistance n'a pas de clé", async () => {
    stub({ aiEnabled: false });
    renderScreen();

    expect(await screen.findByText(/n’est pas médecin/)).toBeInTheDocument();
  });
});

// ── La conversation (`IA-09`) ─────────────────────────

describe('conversation', () => {
  it('affiche la réponse du serveur telle quelle', async () => {
    stub();
    renderScreen();
    await askSomething();

    expect(await screen.findByText(REPLY.reply)).toBeInTheDocument();
    expect(screen.getByText('Pourquoi je stagne ?')).toBeInTheDocument();
  });

  it('affiche le condensé réellement envoyé au modèle', async () => {
    stub();
    renderScreen();
    await askSomething();

    // `IA-09` vérifiable à l'écran plutôt que dans le code.
    expect(await screen.findByText(/1,8 séances/)).toBeInTheDocument();
    expect(screen.getByText(/aucun fichier/, { selector: 'summary' })).toBeInTheDocument();
  });

  it('poursuit le fil au tour suivant, au lieu de renvoyer le passé', async () => {
    // L'écran tenait l'historique et le rendait à chaque question. Il ne rend plus qu'un
    // identifiant : le passé vit dans le fil, côté serveur, et un client ne peut plus le
    // fabriquer — ce qui était sans portée tant que rien ne s'écrivait.
    const user = userEvent.setup();
    stub();
    renderScreen();
    await askSomething();

    await screen.findByText(REPLY.reply);
    await user.type(await screen.findByLabelText('Ta question'), 'Et la semaine prochaine ?');
    await user.click(screen.getByRole('button', { name: 'Demander' }));

    await waitFor(() => {
      const asked = writes().filter((call) => call.url.endsWith('/chat'));
      const first = JSON.parse(asked[0]?.init?.body as string) as Record<string, unknown>;
      const second = JSON.parse(asked[1]?.init?.body as string) as Record<string, unknown>;

      expect(first).not.toHaveProperty('thread_id');
      expect(second.thread_id).toBe(REPLY.thread_id);
      expect(second).not.toHaveProperty('history');
    });
  });

  it('ne part pas sur une question vide', async () => {
    stub();
    renderScreen();

    await screen.findByLabelText('Ta question');
    expect(screen.getByRole('button', { name: 'Demander' })).toBeDisabled();
  });
});

// ── Ce qui vient d'être retenu (`IA-10`) ──────────────

describe('mémoire automatique', () => {
  it('annonce ce que l’assistant vient de retenir', async () => {
    // Le carnet se remplit tout seul. L'écran ne demande plus « à retenir ? » : il dit ce
    // qui a été écrit, au moment où ça l'a été.
    stub();
    renderScreen();
    await askSomething();

    expect(await screen.findByText(proposedNote().note)).toBeInTheDocument();
    expect(screen.getByText('Je retiens')).toBeInTheDocument();
  });

  it('n’écrit rien de plus : la note l’a été par la conversation', async () => {
    stub();
    renderScreen();
    await askSomething();

    await screen.findByText(proposedNote().note);

    // Une seule écriture, vers `/chat` : c'est elle qui a écrit la note côté serveur.
    expect(writes().every((call) => call.url.endsWith('/chat'))).toBe(true);
  });

  it('« Oublier » retire la note par la route du carnet', async () => {
    // Le pendant exact de l'annulation d'un ajout : on est passé d'une validation *avant*
    // à une correction *après*.
    const user = userEvent.setup();
    stub();
    renderScreen();
    await askSomething();

    await user.click(await screen.findByRole('button', { name: `Oublier ${proposedNote().note}` }));

    await waitFor(() => {
      const deletions = writes().filter((call) => call.init?.method === 'DELETE');
      expect(deletions[0]?.url).toContain('/api/assistant/memory/0');
    });
  });

  it('la note oubliée disparaît du fil', async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();
    await askSomething();

    await user.click(await screen.findByRole('button', { name: `Oublier ${proposedNote().note}` }));

    await waitFor(() => {
      expect(screen.queryByText(proposedNote().note)).not.toBeInTheDocument();
    });
  });
});

// ── Le carnet (`IA-11`) ───────────────────────────────

describe('carnet', () => {
  it('affiche les notes retenues et leur provenance', async () => {
    stub();
    renderScreen();

    const item = itemOf(await screen.findByText(storedNote()));

    expect(within(item).getByText('proposée')).toBeInTheDocument();
    expect(within(item).getByText('blessure')).toBeInTheDocument();
  });

  it('écrit une note tapée à la main sur la route qui la marque `manual`', async () => {
    const user = userEvent.setup();
    stub({ memory: EMPTY_MEMORY });
    renderScreen();

    await user.type(await screen.findByLabelText('La note'), 'Je travaille de nuit en août');
    await user.click(screen.getByRole('button', { name: 'Noter' }));

    await waitFor(() => {
      expect(bodyOf('/api/assistant/memory')).toMatchObject({
        note: 'Je travaille de nuit en août',
      });
    });
  });

  it("n'oublie qu'au second appui", async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();

    const button = await screen.findByRole('button', {
      name: `Oublier ${storedNote()}`,
    });
    await user.click(button);

    expect(writes()).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: /confirmer/i }));

    await waitFor(() => {
      expect(writes().some((call) => (call.init?.method ?? '') === 'DELETE')).toBe(true);
    });
  });

  it('renvoie en `If-Match` le jeton qu’il a lu', async () => {
    const user = userEvent.setup();
    stub();
    renderScreen();

    await user.click(await screen.findByRole('button', { name: `Corriger ${storedNote()}` }));
    const field = screen.getByLabelText('La note');
    await user.clear(field);
    await user.type(field, 'Genou droit, ça va mieux');
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }));

    await waitFor(() => {
      const call = writes().find((item) => (item.init?.method ?? '') === 'PATCH');
      expect(call?.init?.headers).toMatchObject({ 'If-Match': 'jeton-note' });
    });
  });
});

// ── Sans clé, le carnet reste entier (`IA-07`) ────────

describe('sans clé API', () => {
  it('ne propose aucune conversation mais garde le carnet utilisable', async () => {
    stub({ aiEnabled: false });
    renderScreen();

    expect(await screen.findByText('Assistance indisponible')).toBeInTheDocument();
    expect(screen.queryByLabelText('Ta question')).not.toBeInTheDocument();

    // Le carnet, lui, est entier : la liste et le formulaire répondent.
    expect(screen.getByText(storedNote())).toBeInTheDocument();
    expect(screen.getByLabelText('La note')).toBeInTheDocument();
  });
});
