import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, NetworkError, onSessionExpired, request, tokenStore } from './api';

function respond(status: number, body: unknown): Response {
  return {
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  tokenStore.clear();
});

describe('jeton', () => {
  it("injecte le jeton dans l'en-tête Authorization", async () => {
    tokenStore.write('jeton-de-test');
    const fetchMock = vi.fn().mockResolvedValue(respond(200, { ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    await request('/api/quelque-chose');

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer jeton-de-test');
  });

  it("n'envoie pas le jeton sur une requête anonyme", async () => {
    tokenStore.write('jeton-de-test');
    const fetchMock = vi.fn().mockResolvedValue(respond(200, {}));
    vi.stubGlobal('fetch', fetchMock);

    await request('/api/auth/login', { method: 'POST', anonymous: true });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });
});

describe('décodage des erreurs', () => {
  it('expose le code machine plutôt que le texte', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          respond(409, { code: 'conflict', message: 'Cette donnée a été modifiée ailleurs.' }),
        ),
    );

    await expect(request('/api/body/weight')).rejects.toMatchObject({
      code: 'conflict',
      status: 409,
    });
  });

  it('expose le détail par champ pour surligner le formulaire', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        respond(422, {
          code: 'validation_error',
          message: 'Les données envoyées sont invalides.',
          fields: [{ field: 'body.weight_kg', message: 'Doit être inférieur ou égal à 500' }],
        }),
      ),
    );

    const error = await request('/api/body/weight').catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).messageFor('weight_kg')).toBe('Doit être inférieur ou égal à 500');
  });

  it('retombe sur un message générique si la réponse n’est pas du JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: () => Promise.reject(new Error('pas du JSON')),
      }),
    );

    await expect(request('/api/x')).rejects.toMatchObject({ code: 'http_error', status: 502 });
  });

  it('distingue une panne réseau d’un refus métier', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    await expect(request('/api/x')).rejects.toBeInstanceOf(NetworkError);
  });
});

describe('expiration de session (AUTH-06)', () => {
  it('purge le jeton et prévient les abonnés', async () => {
    tokenStore.write('jeton-perime');
    const seen: string[] = [];
    const unsubscribe = onSessionExpired((reason) => seen.push(reason));
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          respond(401, { code: 'session_expired', message: 'Session expirée. Reconnecte-toi.' }),
        ),
    );

    await expect(request('/api/auth/me')).rejects.toBeInstanceOf(ApiError);

    expect(tokenStore.read()).toBeNull();
    expect(seen).toEqual(['Session expirée. Reconnecte-toi.']);
    unsubscribe();
  });

  it("ne purge rien sur un refus d'identifiants à la connexion", async () => {
    tokenStore.write('jeton-valide');
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        respond(401, {
          code: 'invalid_credentials',
          message: 'Identifiant ou mot de passe incorrect.',
        }),
      ),
    );

    await expect(
      request('/api/auth/login', { method: 'POST', anonymous: true }),
    ).rejects.toBeInstanceOf(ApiError);

    expect(tokenStore.read()).toBe('jeton-valide');
  });
});

describe('classification des pannes', () => {
  it('juge rejouable ce qui est passager, pas ce qui est un refus', () => {
    const transient = new ApiError({ code: 'storage_unavailable', message: '' }, 503);
    const refusal = new ApiError({ code: 'conflict', message: '' }, 409);

    expect(transient.isTransient).toBe(true);
    expect(refusal.isTransient).toBe(false);
  });
});
