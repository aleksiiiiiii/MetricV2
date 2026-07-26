import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from '@/App';
import { AuthProvider } from '@/app/AuthProvider';
import { Toaster } from '@/components/ui';
import { tokenStore } from '@/lib/api';
import { createQueryClient } from '@/lib/query';

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

function renderApp(route = '/') {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <Toaster>
          <AuthProvider>
            <App />
          </AuthProvider>
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  tokenStore.clear();
});

describe('parcours de connexion', () => {
  it('renvoie un visiteur sans jeton vers la connexion', async () => {
    vi.stubGlobal('fetch', vi.fn());

    renderApp('/');

    expect(await screen.findByRole('heading', { name: 'Connexion' })).toBeInTheDocument();
  });

  it('affiche le message du serveur sur un refus, sans le réécrire', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        json(401, {
          code: 'invalid_credentials',
          message: 'Identifiant ou mot de passe incorrect.',
        }),
      ),
    );
    renderApp('/');

    await userEvent.type(await screen.findByLabelText('Identifiant'), 'aleksi');
    await userEvent.type(screen.getByLabelText('Mot de passe'), 'faux');
    await userEvent.click(screen.getByRole('button', { name: 'Ouvrir la session' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Identifiant ou mot de passe incorrect.',
    );
  });

  it("désactive la saisie et oriente vers la configuration quand l'auth n'est pas configurée", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        json(503, {
          code: 'auth_not_configured',
          message:
            "L'authentification n'est pas configurée : génère un hash avec « make hash-password ».",
        }),
      ),
    );
    renderApp('/');

    await userEvent.type(await screen.findByLabelText('Identifiant'), 'aleksi');
    await userEvent.type(screen.getByLabelText('Mot de passe'), 'peu importe');
    await userEvent.click(screen.getByRole('button', { name: 'Ouvrir la session' }));

    // Rien à ressaisir : c'est le serveur qu'il faut configurer.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Ouvrir la session' })).toBeDisabled();
    });
    expect(screen.getAllByText(/make hash-password/).length).toBeGreaterThan(0);
  });

  it('ouvre la session, mémorise le jeton et affiche la coquille', async () => {
    // Le mock ne reçoit que des chaînes : le client construit ses URL lui-même.
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = input as string;
      if (url.includes('/auth/login')) {
        return Promise.resolve(
          json(200, {
            access_token: 'jeton-frais',
            token_type: 'bearer',
            expires_at: '2026-08-02T12:00:00+02:00',
            username: 'aleksi',
          }),
        );
      }
      if (url.includes('/health')) {
        return Promise.resolve(
          json(200, {
            status: 'ok',
            version: '0.4.0',
            environment: 'test',
            time: '2026-07-26T12:00:00+02:00',
            timezone: 'Europe/Paris',
            storage_configured: false,
            auth_configured: true,
            ai_enabled: false,
          }),
        );
      }
      return Promise.resolve(json(200, {}));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderApp('/');

    await userEvent.type(await screen.findByLabelText('Identifiant'), 'aleksi');
    await userEvent.type(screen.getByLabelText('Mot de passe'), 'le bon');
    await userEvent.click(screen.getByRole('button', { name: 'Ouvrir la session' }));

    expect(await screen.findByRole('heading', { name: 'Tableau de bord' })).toBeInTheDocument();
    // `AUTH-03` : la session doit survivre à la fermeture de l'app.
    expect(tokenStore.read()).toBe('jeton-frais');
  });

  it('valide le jeton auprès du serveur au démarrage plutôt que de le croire', async () => {
    // Sans cela, un jeton expiré pendant que l'app était fermée afficherait
    // l'application puis ferait échouer chaque écran l'un après l'autre.
    tokenStore.write('jeton-perime');
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          json(401, { code: 'session_expired', message: 'Session expirée. Reconnecte-toi.' }),
        ),
    );

    renderApp('/');

    expect(await screen.findByRole('heading', { name: 'Connexion' })).toBeInTheDocument();
    expect(tokenStore.read()).toBeNull();
  });
});
