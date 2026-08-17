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
 * * l'écran vide reste un état — une ligne, sans question toute faite ni avertissement.
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
      resolved: null,
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
  actions: [],
  remember: [
    {
      id: 0,
      token: 'jeton-note',
      memory_id: 'n1',
      created: '2026-08-06',
      topic: 'sommeil',
      note: 'Je dors mal les soirs de séance tardive',
      source: 'ai',
      resolved: null,
    },
  ],
  context: [
    'Nous sommes le jeudi 06/08/2026',
    'Séances par semaine : 1,8 séances (moyenne des 4 dernières semaines complètes)',
  ],
};

/** Deux fils : un seul ne dirait pas si l'armement porte sur la bonne ligne. */
const THREADS = {
  threads: [
    { thread_id: 'fil-1', title: 'Où j’en suis cette semaine', messages: 4 },
    { thread_id: 'fil-2', title: 'Pourquoi je stagne', messages: 2 },
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

function stub(
  options: {
    memory?: AssistantView;
    reply?: ChatReply;
    aiEnabled?: boolean;
    chatFails?: boolean;
    threads?: { threads: { thread_id: string; title: string; messages: number }[] };
    /** Réponse sur mesure, consultée avant tout le reste. */
    custom?: (url: string, init?: RequestInit) => Response | undefined;
  } = {},
) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    // `request` n'envoie que des chaînes : le typage de `fetch` est plus large que
    // l'usage, et `String(objet)` rendrait « [object Object] » sans le dire.
    const url = input as string;
    calls.push({ url, init });

    const override = options.custom?.(url, init);
    if (override) return Promise.resolve(override);

    if (url.includes('/api/ai/status')) {
      return Promise.resolve(
        json(200, { enabled: options.aiEnabled ?? true, message: 'aucune clé configurée' }),
      );
    }
    if (url.includes('/api/assistant/chat')) {
      if (options.chatFails === true) {
        return Promise.resolve(
          json(503, { code: 'ai_unavailable', message: 'Modèle injoignable.' }),
        );
      }
      return Promise.resolve(json(200, options.reply ?? REPLY));
    }
    if (url.includes('/api/assistant/threads')) {
      return Promise.resolve(json(200, options.threads ?? THREADS));
    }
    if (url.includes('/api/assistant/actions/confirm')) {
      return Promise.resolve(
        json(200, { ...PENDING, status: 'done', summary: 'Pesée supprimée.' }),
      );
    }
    return Promise.resolve(json(200, options.memory ?? MEMORY));
  });

  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderScreen(at = '/assistant') {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[at]}>
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

/**
 * L'écriture est-elle la conversation elle-même ?
 *
 * Deux adresses la portent : `/chat/stream`, que l'écran tente en premier pour suivre
 * l'avancement, et `/chat`, son repli quand le flux ne passe pas. Dans la doublure, la
 * réponse simulée n'a pas de corps lisible en flux : les deux partent donc, et c'est
 * exactement le repli qu'on veut voir fonctionner.
 */
function isConversation(call: Call): boolean {
  return call.url.endsWith('/chat') || call.url.endsWith('/chat/stream');
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
  await user.click(screen.getByRole('button', { name: 'Envoyer' }));
}

/** Ouvre la feuille du carnet — il ne vit plus sous le fil. */
async function openMemory(): Promise<void> {
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Mémoire' }));
}

/** Ouvre la feuille des discussions. */
async function openThreads(): Promise<void> {
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Discussions' }));
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── L'écran épuré (C04) ───────────────────────────────

describe('écran épuré', () => {
  it('n’affiche plus la mention médicale', async () => {
    // `IA-12` a été levé sur décision explicite : la mention permanente en tête de fil
    // est retirée. Le test la garde pour ce qu'elle est devenue — une absence voulue,
    // et non un oubli qu'un lot suivant remettrait sans s'en apercevoir.
    stub();
    renderScreen();

    await screen.findByPlaceholderText('Écris ta question…');

    expect(screen.queryByText(/n’est pas médecin/)).toBeNull();
    expect(screen.queryByText(/professionnel de santé/)).toBeNull();
  });

  it('n’offre plus de question toute faite', async () => {
    stub();
    renderScreen();

    await screen.findByPlaceholderText('Écris ta question…');

    expect(screen.queryByRole('button', { name: 'Pourquoi je stagne ?' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Où j’en suis/ })).toBeNull();
  });

  it('retire l’état vide dès qu’une question part', async () => {
    // Vu en capture : « le fil commence ici » restait affiché **au-dessus** de la
    // question qu'on venait d'envoyer. L'état vide décrivait un écran que l'utilisateur
    // n'avait plus sous les yeux.
    const user = userEvent.setup();
    stub();
    renderScreen();

    await user.type(await screen.findByLabelText('Ta question'), 'Pourquoi je stagne ?');
    await user.click(screen.getByRole('button', { name: 'Envoyer' }));

    expect(screen.queryByText(/le fil commence ici/)).toBeNull();
  });

  it('garde un état vide, en une ligne', async () => {
    // Quatre états par écran, jamais trois : un fil neuf ne peut pas être une page
    // blanche. Mais il n'a plus besoin d'un paragraphe pour le dire.
    stub();
    renderScreen();

    expect(await screen.findByText(/le fil commence ici/)).toBeInTheDocument();
  });
});

/** Un corps `text/event-stream` lisible en flux, pour la route diffusée. */
function sseBody(blocks: string[]): Response {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: () =>
          Promise.resolve(
            index < blocks.length
              ? { done: false, value: encoder.encode(blocks[index++]) }
              : { done: true, value: undefined },
          ),
      }),
    },
  } as unknown as Response;
}

// ── L'avancement pendant l'attente (C04-1) ────────────

describe('avancement', () => {
  it('affiche les étapes que le serveur annonce, dans l’ordre', async () => {
    // Elles ne sont pas devinées : une suite d'étapes affichée sur une minuterie serait
    // une valeur inventée à l'écran, exactement comme un chiffre.
    stub({
      custom: (url) =>
        url.includes('/chat/stream')
          ? sseBody([
              'event: step\ndata: {"step": "je relis tes chiffres"}\n\n',
              'event: step\ndata: {"step": "je demande au modèle"}\n\n',
              `event: reply\ndata: ${JSON.stringify(REPLY)}\n\n`,
            ])
          : undefined,
    });
    renderScreen();
    await askSomething();

    expect(await screen.findByText(REPLY.reply)).toBeInTheDocument();
    // Le flux a bien servi : l'appel de repli n'est jamais parti.
    expect(writes().some((call) => call.url.endsWith('/chat'))).toBe(false);
  });

  it('écrit la réponse pendant qu’elle arrive, morceau par morceau', async () => {
    // Ce n'est pas une cinquième façon de dire « proposé » : c'est le même `reply`, plus
    // tôt. Le serveur ne diffuse que ce qu'il a prouvé final, donc rien de ce qui
    // s'affiche ici n'aura à être effacé.
    stub({
      custom: (url) =>
        url.includes('/chat/stream')
          ? sseBody([
              'event: step\ndata: {"step": "je demande au modèle"}\n\n',
              'event: delta\ndata: {"text": "Tu tournes à "}\n\n',
              'event: delta\ndata: {"text": "1,8 séance."}\n\n',
              `event: reply\ndata: ${JSON.stringify({ ...REPLY, reply: 'Tu tournes à 1,8 séance.' })}\n\n`,
            ])
          : undefined,
    });
    renderScreen();
    await askSomething();

    expect(await screen.findByText('Tu tournes à 1,8 séance.')).toBeInTheDocument();
    expect(writes().some((call) => call.url.endsWith('/chat'))).toBe(false);
  });

  it('oublie ce qu’un modèle avait commencé quand il tombe en route', async () => {
    // Le seul endroit du dessin où du texte disparaît. Sans `reset`, la réponse du modèle
    // suivant se collerait au début abandonné du premier, formant un texte que personne
    // n'a rédigé.
    stub({
      custom: (url) =>
        url.includes('/chat/stream')
          ? sseBody([
              'event: delta\ndata: {"text": "Début abandonné"}\n\n',
              'event: reset\ndata: {}\n\n',
              'event: delta\ndata: {"text": "Réponse du suivant."}\n\n',
              `event: reply\ndata: ${JSON.stringify({ ...REPLY, reply: 'Réponse du suivant.' })}\n\n`,
            ])
          : undefined,
    });
    renderScreen();
    await askSomething();

    expect(await screen.findByText('Réponse du suivant.')).toBeInTheDocument();
    expect(screen.queryByText(/Début abandonné/)).not.toBeInTheDocument();
  });

  it('remonte une erreur venue du flux, avec son message', async () => {
    // Les en-têtes sont partis depuis longtemps quand un modèle renonce : l'erreur ne
    // peut plus être un statut HTTP, elle voyage dans le flux.
    stub({
      custom: (url) =>
        url.includes('/chat/stream')
          ? sseBody([
              'event: step\ndata: {"step": "je demande au modèle"}\n\n',
              'event: error\ndata: {"code": "ai_quota", "message": "Quota épuisé."}\n\n',
            ])
          : undefined,
    });
    renderScreen();
    await askSomething();

    expect(await screen.findByRole('alert')).toHaveTextContent('Quota épuisé.');
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeInTheDocument();
  });

  it('retombe sur l’appel ordinaire quand le flux ne passe pas', async () => {
    // `IA-07` dans son esprit : l'agrément tombe, la fonction reste. C'est le chemin que
    // prennent tous les autres tests de ce fichier, la doublure ne servant pas de flux.
    stub();
    renderScreen();
    await askSomething();

    expect(await screen.findByText(REPLY.reply)).toBeInTheDocument();
    expect(writes().some((call) => call.url.endsWith('/chat'))).toBe(true);
  });
});

// ── Ce qui accompagne une réponse (C04) ───────────────

describe('autour d’une réponse', () => {
  it('affiche la mise en forme du modèle plutôt que ses astérisques', async () => {
    stub({
      reply: {
        ...REPLY,
        reply: 'Trois causes :\n- **le sommeil**\n- la charge\n- le déficit',
      },
    });
    renderScreen();
    await askSomething();

    // Le gras est une balise, pas des astérisques à l'écran.
    const bubble = (await screen.findByText('le sommeil')).closest('div');
    expect(bubble).not.toBeNull();
    // Le gras est une balise, pas des astérisques à l'écran.
    expect(within(bubble as HTMLElement).getByRole('list')).toBeInTheDocument();
    expect(screen.queryByText(/\*\*/)).toBeNull();
  });

  it('copie une réponse dans le presse-papier', async () => {
    stub();
    renderScreen();
    await askSomething();

    // Le doublon se pose **après** `askSomething`, qui appelle `userEvent.setup()` :
    // celui-ci installe son propre presse-papier et écraserait le nôtre.
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Copier la réponse' }));

    expect(writeText).toHaveBeenCalledWith(REPLY.reply);
  });

  it('garde le condensé sur son propre tour', async () => {
    // Il vivait dans un état d'écran : il n'existait que sur le dernier échange et
    // disparaissait au suivant. C'est justement en relisant une vieille réponse qu'on
    // veut savoir sur quoi elle s'appuyait.
    stub();
    renderScreen();
    await askSomething();
    await screen.findByText(REPLY.reply);

    await userEvent.type(await screen.findByLabelText('Ta question'), 'Et maintenant ?');
    await userEvent.click(screen.getByRole('button', { name: 'Envoyer' }));

    await waitFor(() => {
      expect(screen.getAllByText(/Ce qui a été envoyé/)).toHaveLength(2);
    });
  });
});

// ── La feuille des discussions (C04) ──────────────────

describe('feuille des discussions', () => {
  it('demande deux appuis pour supprimer une discussion', async () => {
    // C'était la seule surface destructrice du projet à partir d'un appui unique, à
    // côté du bouton qui sert à ouvrir le fil. Rien ne défait une suppression.
    stub();
    renderScreen();
    await openThreads();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Supprimer « Pourquoi je stagne »' }),
    );

    expect(writes().some((call) => call.init?.method === 'DELETE')).toBe(false);

    await userEvent.click(
      screen.getByRole('button', { name: /Supprimer « Pourquoi je stagne » — confirmer/ }),
    );

    await waitFor(() => {
      const deletions = writes().filter((call) => call.init?.method === 'DELETE');
      expect(deletions[0]?.url).toContain('fil-2');
    });
  });

  it('renomme une discussion sans la faire remonter', async () => {
    // Le modèle nomme le fil à son ouverture et se trompe ; la seule issue était de le
    // supprimer, donc d'emporter la conversation avec son mauvais titre.
    stub();
    renderScreen();
    await openThreads();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Renommer « Pourquoi je stagne »' }),
    );
    await userEvent.clear(screen.getByLabelText('Titre de la discussion'));
    await userEvent.type(screen.getByLabelText('Titre de la discussion'), 'Reprise du genou');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer' }));

    await waitFor(() => {
      const patch = writes().find((call) => call.init?.method === 'PATCH');
      expect(patch?.url).toContain('/threads/fil-2');
      expect(JSON.parse(patch?.init?.body as string)).toEqual({ title: 'Reprise du genou' });
    });
  });

  it('s’ouvre directement depuis une adresse', async () => {
    // Le tableau de bord y mène : une feuille qu'on atteint depuis un autre écran doit
    // être adressable, sinon le lien ouvre la conversation et laisse un appui de plus à
    // faire, sans dire lequel.
    stub();
    renderScreen('/assistant?ouvre=discussions');

    expect(await screen.findByText('Tes discussions')).toBeInTheDocument();
  });

  it('n’arme qu’une ligne à la fois', async () => {
    stub();
    renderScreen();
    await openThreads();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Supprimer « Pourquoi je stagne »' }),
    );

    // L'autre ligne reste au repos : un appui de confirmation destiné à l'une ne doit
    // jamais pouvoir tomber sur l'autre.
    expect(
      screen.getByRole('button', { name: 'Supprimer « Où j’en suis cette semaine »' }),
    ).toBeInTheDocument();
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
    await user.click(screen.getByRole('button', { name: 'Envoyer' }));

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
    expect(screen.getByRole('button', { name: 'Envoyer' })).toBeDisabled();
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
    expect(screen.getByText(/Je retiens/)).toBeInTheDocument();
  });

  it('n’écrit rien de plus : la note l’a été par la conversation', async () => {
    stub();
    renderScreen();
    await askSomething();

    await screen.findByText(proposedNote().note);

    // Aucune écriture en dehors de la conversation : c'est elle qui a écrit la note
    // côté serveur, l'écran n'a rien ajouté.
    expect(writes().every(isConversation)).toBe(true);
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

// ── Ce que l'assistant fait (`IA-15`) ─────────────────

const ADDED = {
  name: 'weight.add',
  level: 'add' as const,
  status: 'done' as const,
  summary: 'Pesée de 82,4 kg notée le 08/08/2026.',
  args: { date: '2026-08-08', weight_kg: 82.4 },
  undo: { domain: 'body/weight', row_id: 0, token: 'jeton-pesee' },
};

const PENDING = {
  name: 'weight.delete',
  level: 'change' as const,
  status: 'pending' as const,
  summary: 'Supprimer une pesée',
  args: { row_id: 0, token: 'jeton-pesee' },
  undo: null,
};

describe('actions', () => {
  it('annonce ce qui a été écrit, en français', async () => {
    stub({ reply: { ...REPLY, actions: [ADDED] } });
    renderScreen();
    await askSomething();

    expect(await screen.findByText(ADDED.summary)).toBeInTheDocument();
  });

  it('« Annuler » appelle la route du domaine, pas une route d’assistant', async () => {
    // L'annulation est le geste que l'utilisateur ferait lui-même depuis l'écran Corps.
    // Aucune machinerie d'annulation n'a été inventée, et ce test le verrouille.
    const user = userEvent.setup();
    stub({ reply: { ...REPLY, actions: [ADDED] } });
    renderScreen();
    await askSomething();

    await user.click(await screen.findByRole('button', { name: 'Annuler' }));

    await waitFor(() => {
      const deletions = writes().filter((call) => call.init?.method === 'DELETE');
      expect(deletions[0]?.url).toContain('/api/body/weight/0');
    });
  });

  it('une action en attente n’écrit rien tant qu’on n’a pas confirmé', async () => {
    stub({ reply: { ...REPLY, actions: [PENDING] } });
    renderScreen();
    await askSomething();

    expect(await screen.findByRole('button', { name: 'Confirmer' })).toBeInTheDocument();
    // La seule écriture est la question elle-même.
    expect(writes().every(isConversation)).toBe(true);
  });

  it('« Confirmer » repasse par la revalidation du serveur', async () => {
    const user = userEvent.setup();
    stub({ reply: { ...REPLY, actions: [PENDING] } });
    renderScreen();
    await askSomething();

    await user.click(await screen.findByRole('button', { name: 'Confirmer' }));

    await waitFor(() => {
      expect(bodyOf('/actions/confirm')).toMatchObject({
        name: 'weight.delete',
        args: PENDING.args,
      });
    });
  });

  it('« Non » écarte l’action sans rien appeler', async () => {
    const user = userEvent.setup();
    stub({ reply: { ...REPLY, actions: [PENDING] } });
    renderScreen();
    await askSomething();

    await user.click(await screen.findByRole('button', { name: 'Non' }));

    expect(screen.queryByText(PENDING.summary)).not.toBeInTheDocument();
    expect(writes().every(isConversation)).toBe(true);
  });

  it('un refus s’affiche et ne propose aucun geste', async () => {
    const refused = {
      ...ADDED,
      status: 'refused' as const,
      summary: 'Il me manque de quoi le faire : date.',
      undo: null,
    };
    stub({ reply: { ...REPLY, actions: [refused] } });
    renderScreen();
    await askSomething();

    expect(await screen.findByText(refused.summary)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Annuler' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirmer' })).not.toBeInTheDocument();
  });
});

// ── Le carnet (`IA-11`) ───────────────────────────────

describe('carnet', () => {
  it('affiche les notes retenues et leur provenance', async () => {
    stub();
    renderScreen();
    await openMemory();

    const item = itemOf(await screen.findByText(storedNote()));

    // « retenue seule » et non « proposée » : plus rien ne propose, le carnet se remplit
    // pendant la conversation et se corrige après.
    expect(within(item).getByText('retenue seule')).toBeInTheDocument();
    expect(within(item).getByText('blessure')).toBeInTheDocument();
  });

  it('écrit une note tapée à la main sur la route qui la marque `manual`', async () => {
    const user = userEvent.setup();
    stub({ memory: EMPTY_MEMORY });
    renderScreen();
    await openMemory();

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
    await openMemory();

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
    await openMemory();

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

  it('marque une note résolue sans demander confirmation', async () => {
    // Résoudre n'est pas détruire : le même bouton défait ce qu'il vient de faire. Armer
    // puis confirmer un geste réversible finirait par faire ignorer la confirmation là où
    // elle compte — sur l'oubli, juste à côté, que rien ne rattrape.
    const user = userEvent.setup();
    stub();
    renderScreen();
    await openMemory();

    await user.click(
      await screen.findByRole('button', { name: `Marquer résolu : ${storedNote()}` }),
    );

    await waitFor(() => {
      const call = writes().find((item) => (item.init?.method ?? '') === 'PATCH');
      expect(JSON.parse(call?.init?.body as string)).toMatchObject({ resolved: true });
      expect(call?.init?.headers).toMatchObject({ 'If-Match': 'jeton-note' });
    });
  });

  it('affiche une note résolue au lieu de la faire disparaître', async () => {
    // Une blessure guérie reste une information : elle dit ce qui a déjà lâché, donc ce
    // qu'un coach surveille. La retirer du carnet perdrait exactement cela.
    const first = MEMORY.memories[0];
    if (!first) throw new Error('ce carnet de référence porte une note');
    stub({ memory: { ...MEMORY, memories: [{ ...first, resolved: '2026-08-01' }] } });
    renderScreen();
    await openMemory();

    expect(await screen.findByText(storedNote())).toBeInTheDocument();
    expect(screen.getByText(/résolu le/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: `Réactiver : ${storedNote()}` })).toBeInTheDocument();
  });
});

// ── Sans clé, le carnet reste entier (`IA-07`) ────────

describe('sans clé API', () => {
  it('ne propose aucune conversation mais garde le carnet utilisable', async () => {
    // `IA-07` : l'IA est un confort, le carnet est un carnet. Sans clé, la saisie est
    // fermée — mais la mémoire se lit et s'écrit, dans sa feuille, sans rien demander.
    stub({ aiEnabled: false });
    renderScreen();

    expect(await screen.findByText('Assistance indisponible')).toBeInTheDocument();
    expect(await screen.findByLabelText('Ta question')).toBeDisabled();

    await openMemory();

    expect(await screen.findByText(storedNote())).toBeInTheDocument();
    expect(screen.getByLabelText('La note')).toBeInTheDocument();
  });
});

// ── L'attente (`IA-09`) ───────────────────────────────

describe('attente', () => {
  it('affiche la question tout de suite, sans attendre la réponse', async () => {
    // Dans une messagerie, ce qu'on envoie apparaît immédiatement : attendre la réponse
    // pour afficher sa propre phrase donne l'impression d'un envoi qui n'est pas parti.
    const user = userEvent.setup();
    stub();
    renderScreen();

    await user.type(await screen.findByLabelText('Ta question'), 'Pourquoi je stagne ?');
    await user.click(screen.getByRole('button', { name: 'Envoyer' }));

    expect(await screen.findByText('Pourquoi je stagne ?')).toBeInTheDocument();
  });

  it('retire les trois points dès que la réponse est là', async () => {
    // Ils étaient pilotés par `isPending` de la mutation et restaient affichés après
    // l'arrivée de la réponse. L'état est maintenant à nous, remis à zéro dans
    // `onSettled` — donc au succès comme à l'échec.
    stub();
    renderScreen();
    await askSomething();

    await screen.findByText(REPLY.reply);

    expect(screen.queryByLabelText('L’assistant réfléchit')).not.toBeInTheDocument();
  });

  it('vide le champ à l’envoi, et garde la question échouée dans le fil', async () => {
    /*
     * **La question ne revient plus dans le champ**, et c'est un changement voulu.
     *
     * Elle y revenait, ce qui obligeait à la renvoyer à la main — et la perdait si l'on
     * avait commencé à taper autre chose entre-temps. Elle reste maintenant à sa place
     * dans la conversation, avec le message du serveur et de quoi la rejouer.
     */
    const user = userEvent.setup();
    stub({ chatFails: true });
    renderScreen();

    const field = await screen.findByLabelText('Ta question');
    await user.type(field, 'Pourquoi je stagne ?');
    await user.click(screen.getByRole('button', { name: 'Envoyer' }));

    await waitFor(() => {
      expect(screen.queryByLabelText('L’assistant réfléchit')).not.toBeInTheDocument();
    });

    expect(field).toHaveValue('');
    expect(screen.getByText('Pourquoi je stagne ?')).toBeInTheDocument();
    expect(within(screen.getByRole('alert')).getByText(/Modèle injoignable/)).toBeInTheDocument();
  });

  it('rejoue une question échouée sans la retaper', async () => {
    const user = userEvent.setup();
    stub({ chatFails: true });
    renderScreen();

    await user.type(await screen.findByLabelText('Ta question'), 'Pourquoi je stagne ?');
    await user.click(screen.getByRole('button', { name: 'Envoyer' }));
    await screen.findByRole('button', { name: 'Réessayer' });

    // La seconde tentative aboutit : la doublure ne refuse que le premier appel.
    stub();
    await user.click(screen.getByRole('button', { name: 'Réessayer' }));

    expect(await screen.findByText(REPLY.reply)).toBeInTheDocument();
    // Le tour raté a laissé la place au tour réussi, il n'en reste pas deux.
    expect(screen.queryByRole('button', { name: 'Réessayer' })).toBeNull();
  });
});
