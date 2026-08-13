import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import { createQueryClient } from '@/lib/query';
import { NOTIFICATIONS, NOTIFICATIONS_READY } from '@/test/fixtures';

import { Reminders } from './Reminders';

/**
 * La section « Rappels » de `/reglages` (`NOT-01`, `NOT-03`, `L15-06`).
 *
 * Deux choses comptent ici, et une seule est visible :
 *
 * * **l'écran n'invente aucun horaire.** C'est l'invariant du lot appliqué au formulaire :
 *   un créneau proposé d'office serait un rappel que personne n'a demandé, et un rappel
 *   qui arrive au mauvais moment se désinstalle en un geste ;
 * * **il annonce ce qu'un rappel dira** avant qu'on choisisse une heure. Quelqu'un qui
 *   attend « tu n'as pas bu » et reçoit « rien de noté » trouve le rappel mou, alors
 *   qu'il est simplement honnête.
 *
 * `pushSupport()` rend `unsupported` sous jsdom — pas de `PushManager`, pas de
 * `matchMedia` en mode autonome. C'est l'état réel d'un navigateur de test, et les tests
 * qui portent sur l'abonnement le disent plutôt que de le simuler.
 */

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

function stub(view: unknown = NOTIFICATIONS, override?: (url: string) => Response | undefined) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = input as string;
      calls.push({ url, init });
      return Promise.resolve(override?.(url) ?? json(200, view));
    }),
  );
}

function renderSection() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <Toaster>
        <Reminders />
      </Toaster>
    </QueryClientProvider>,
  );
}

const written = () => calls.find((call) => call.init?.method === 'PATCH');

/**
 * Le champ d'un rappel, désigné par son nom.
 *
 * `champs[1]` obligeait à connaître l'ordre de `REMINDERS` pour relire le test, et une
 * insertion dans cette table aurait déplacé silencieusement ce que chaque test croit
 * modifier.
 */
function champ(rang: number): HTMLElement {
  const champs = screen.getAllByLabelText('Heure du rappel');
  const trouve = champs[rang];
  if (!trouve) throw new Error(`aucun champ de rappel au rang ${rang}`);
  return trouve;
}

/** Ordre de la table `REMINDERS`, écrit une fois. */
const RANG = { supplements: 0, hydration: 1, meals: 2, workout: 3 } as const;
const body = (call: Call | undefined) =>
  JSON.parse(call?.init?.body as string) as Record<string, unknown>;

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('section Rappels', () => {
  it('n’invente aucun horaire : tout est éteint par défaut', async () => {
    // Le défaut est le **silence**. Un créneau proposé d'office serait un rappel que
    // personne n'a demandé — et c'est la fonctionnalité la plus facile à rendre nuisible.
    stub();
    renderSection();

    expect(await screen.findByText('Notifications')).toBeInTheDocument();
    expect(screen.getAllByText('éteint')).toHaveLength(4);

    for (const champ of screen.getAllByLabelText('Heure du rappel')) {
      expect(champ).toHaveValue('');
    }
  });

  it('dit ce qu’un rappel dira, avant qu’on choisisse une heure', async () => {
    stub();
    renderSection();

    // La phrase est coupée par un `<strong>` : un matcher sur un nœud de texte unique
    // ne la verrait pas. On interroge le paragraphe entier, qui est ce que l'œil lit.
    const phrase = await screen.findByText(
      (_, element) =>
        element?.tagName === 'P' && (element.textContent ?? '').includes('jamais ce qui'),
    );
    expect(phrase.textContent).toContain('pas noté');
    expect(phrase.textContent).toContain('jamais ce qui n’a pas été fait');
  });

  it('affiche le message du serveur tel quel', async () => {
    // Le client décide sur `configured`, jamais sur le texte : le message vient du
    // serveur, en français, et s'affiche en l'état (`API-07`).
    stub();
    renderSection();

    expect(await screen.findByText(NOTIFICATIONS.push.message)).toBeInTheDocument();
    expect(screen.getByText('non configurées')).toBeInTheDocument();
  });

  it('ne propose pas de s’abonner quand le serveur n’a pas de clé', async () => {
    stub();
    renderSection();

    await screen.findByText('Notifications');
    expect(screen.queryByRole('button', { name: /Recevoir les rappels/ })).not.toBeInTheDocument();
  });

  it('affiche un créneau réglé sans répéter son heure, et sans promettre qu’il partira', async () => {
    // Deux formulations écartées en regardant la page : « 20:00 », qui répétait le champ
    // trente pixels plus bas, et « actif », qui **mentait** sans clé VAPID — un créneau
    // réglé n'y déclenche rien.
    stub(NOTIFICATIONS_READY);
    renderSection();

    expect(await screen.findByText('réglé')).toBeInTheDocument();
    expect(screen.getAllByText('éteint')).toHaveLength(3);
    // L'heure n'est écrite qu'une fois : dans le champ.
    expect(screen.queryAllByText('20:00')).toHaveLength(0);
  });

  it('ne dit jamais « actif » quand aucune clé n’est configurée', async () => {
    // Le cas qui a motivé le changement : sans clé, rien ne partira jamais. Un badge qui
    // annoncerait le contraire serait une affirmation fausse à l'écran.
    stub({ ...NOTIFICATIONS, reminders: { ...NOTIFICATIONS.reminders, supplements: '20:00' } });
    renderSection();

    expect(await screen.findByText('réglé')).toBeInTheDocument();
    expect(screen.queryByText('actif')).not.toBeInTheDocument();
  });

  it('n’envoie que le créneau qui a changé', async () => {
    // Envoyer les quatre à chaque enregistrement écrirait quatre cellules là où une seule
    // a bougé, et rendrait conflictuelle toute écriture concurrente pour rien.
    stub(NOTIFICATIONS_READY);
    renderSection();

    await screen.findAllByLabelText('Heure du rappel');
    await userEvent.clear(champ(RANG.hydration));
    await userEvent.type(champ(RANG.hydration), '19:30');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer les rappels' }));

    await waitFor(() => {
      expect(body(written())).toEqual({ hydration: '19:30' });
    });
  });

  it('vider un champ éteint le rappel, et l’envoie à null', async () => {
    // La distinction qui compte : `null` veut dire **éteint**, pas « non fourni ». Sans
    // elle, on ne saurait pas exprimer « arrête ce rappel ».
    stub(NOTIFICATIONS_READY);
    renderSection();

    await screen.findAllByLabelText('Heure du rappel');
    await userEvent.clear(champ(RANG.supplements));
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer les rappels' }));

    await waitFor(() => {
      expect(body(written())).toEqual({ supplements: null });
    });
  });

  it('renvoie le jeton du fichier de réglages en If-Match', async () => {
    // Les créneaux vivent dans `settings.csv` (`NOT-03`) : la garde est celle du fichier
    // entier, et un `If-Match` absent est un conflit (`STO-05`).
    stub(NOTIFICATIONS_READY);
    renderSection();

    await screen.findAllByLabelText('Heure du rappel');
    await userEvent.clear(champ(RANG.meals));
    await userEvent.type(champ(RANG.meals), '12:30');
    await userEvent.click(screen.getByRole('button', { name: 'Enregistrer les rappels' }));

    await waitFor(() => {
      const headers = written()?.init?.headers as Record<string, string>;
      expect(headers['If-Match']).toBe('jeton-reglages');
    });
  });

  it('n’écrit rien tant qu’on n’a rien changé', async () => {
    stub(NOTIFICATIONS_READY);
    renderSection();

    const bouton = await screen.findByRole('button', { name: 'Enregistrer les rappels' });
    expect(bouton).toBeDisabled();
    expect(written()).toBeUndefined();
  });

  it('affiche les appareils abonnés sans publier leur adresse', async () => {
    // Qui détient l'`endpoint` peut envoyer une notification à cet appareil : l'écran
    // n'en reçoit et n'en affiche que les derniers caractères.
    stub(NOTIFICATIONS_READY);
    renderSection();

    expect(await screen.findByText('iPhone')).toBeInTheDocument();
    expect(screen.getByText('…ppareil-1')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('https://');
  });

  it('dit pourquoi l’abonnement n’est pas proposé sur ce navigateur', async () => {
    // Sous jsdom, `PushManager` n'existe pas et rien n'annonce le mode autonome : c'est
    // le cas « ajoute Metric à ton écran d'accueil ». Une section qui se contenterait de
    // masquer le bouton laisserait quelqu'un chercher longtemps.
    stub(NOTIFICATIONS_READY);
    renderSection();

    await screen.findByText('disponibles');
    expect(
      screen.getByText(/écran d’accueil|ne sait pas recevoir|contexte sécurisé/),
    ).toBeInTheDocument();
  });

  it('affiche l’état d’erreur sans rien inventer', async () => {
    stub(NOTIFICATIONS, () =>
      json(503, { code: 'storage_unavailable', message: 'Stockage injoignable.' }),
    );
    renderSection();

    // Le délai est large **à dessein** : `storage_unavailable` est une panne passagère,
    // que le client rejoue deux fois avant d'abandonner (`L03-07`, `STO-08`). Un délai
    // court ferait échouer ce test sur un comportement voulu.
    expect(
      await screen.findByText('Rappels indisponibles', {}, { timeout: 5000 }),
    ).toBeInTheDocument();
    // Surtout : aucun créneau affiché. Sur une erreur, l'écran ne montre pas quatre
    // rappels « éteints » qu'il n'a jamais lus — ce serait une valeur inventée.
    expect(screen.queryByText('éteint')).not.toBeInTheDocument();
  });
});
