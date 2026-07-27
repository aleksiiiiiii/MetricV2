/**
 * Client API typé (`API-07`, `AUTH-03`, `AUTH-06`).
 *
 * Un seul point de passage vers le backend. Il fait trois choses que personne d'autre ne
 * doit refaire :
 *
 * * injecter le jeton de session ;
 * * décoder l'enveloppe d'erreur `{code, message, fields}` en une exception typée ;
 * * signaler une session expirée pour que l'application purge son jeton (`AUTH-06`).
 *
 * Le message du serveur est déjà en français et affichable en l'état : on ne le
 * réécrit pas. Le **code** est ce sur quoi le code applicatif décide — jamais le texte.
 */

/** Détail par champ d'une erreur de validation (`API-06`). */
export interface FieldError {
  field: string;
  message: string;
}

export interface ErrorBody {
  code: string;
  message: string;
  fields?: FieldError[];
}

/** Erreur métier renvoyée par l'API. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly fields: FieldError[];

  constructor(body: ErrorBody, status: number) {
    super(body.message);
    this.name = 'ApiError';
    this.code = body.code;
    this.status = status;
    this.fields = body.fields ?? [];
  }

  /** Message à afficher à côté d'un champ de formulaire donné. */
  messageFor(field: string): string | undefined {
    return this.fields.find((entry) => entry.field.endsWith(field))?.message;
  }

  get isSessionExpired(): boolean {
    return this.code === 'session_expired';
  }

  /** Vrai si réessayer a une chance d'aboutir : panne passagère, pas refus métier. */
  get isTransient(): boolean {
    return (
      this.status >= 500 || this.code === 'storage_unavailable' || this.code === 'too_many_attempts'
    );
  }
}

/** Panne réseau : le serveur n'a pas répondu du tout. */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super('Le serveur est injoignable. Vérifie ta connexion.');
    this.name = 'NetworkError';
    this.cause = cause;
  }
}

// ── Jeton de session ──────────────────────────────────

const TOKEN_KEY = 'metric.token';

/**
 * Le jeton vit dans `localStorage` et non en mémoire : `AUTH-03` demande que la session
 * survive à la fermeture de l'application et au redémarrage de l'appareil.
 *
 * Contrepartie connue : un script injecté dans la page pourrait le lire. La parade est
 * une politique de sécurité de contenu stricte, posée au lot L17 (`L17-03`) — pas un
 * stockage en mémoire, qui casserait la persistance exigée.
 *
 * **Repli en mémoire.** `localStorage` peut être absent ou verrouillé : navigation privée
 * sous Safari, cookies tiers bloqués, environnement de test. Avaler l'erreur en silence
 * ferait perdre la session au premier rechargement sans rien annoncer. Le repli garde
 * l'application utilisable pendant la visite, et `persistent` permet de le dire.
 */
const memory = new Map<string, string>();

function backend(): Storage | null {
  try {
    if (typeof localStorage === 'undefined') return null;
    // Un test d'écriture réel : sous Safari en navigation privée, l'objet existe mais
    // `setItem` lève au premier appel.
    const probe = '__metric_probe__';
    localStorage.setItem(probe, '1');
    localStorage.removeItem(probe);
    return localStorage;
  } catch {
    return null;
  }
}

export const tokenStore = {
  /** Faux quand le jeton ne survivra pas à un rechargement. */
  get persistent(): boolean {
    return backend() !== null;
  },

  read(): string | null {
    const store = backend();
    return store ? store.getItem(TOKEN_KEY) : (memory.get(TOKEN_KEY) ?? null);
  },

  write(token: string): void {
    const store = backend();
    if (store) store.setItem(TOKEN_KEY, token);
    else memory.set(TOKEN_KEY, token);
  },

  clear(): void {
    const store = backend();
    if (store) store.removeItem(TOKEN_KEY);
    memory.delete(TOKEN_KEY);
  },
};

/** Abonnés notifiés quand le serveur déclare la session terminée (`AUTH-06`). */
type ExpiryListener = (reason: string) => void;
const expiryListeners = new Set<ExpiryListener>();

export function onSessionExpired(listener: ExpiryListener): () => void {
  expiryListeners.add(listener);
  return () => expiryListeners.delete(listener);
}

// ── Requête ───────────────────────────────────────────

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
  /** Requête de connexion : un `401` y est un refus d'identifiants, pas une expiration. */
  anonymous?: boolean;
  query?: Record<string, string | number | undefined>;
  /** En-têtes additionnels — `If-Match` pour la garde anti-conflit (`STO-05`). */
  headers?: Record<string, string>;
  /**
   * Corps multipart, pour un téléversement de fichier (`NUT-01`).
   *
   * Le `Content-Type` est laissé au navigateur : lui-même y ajoute la frontière de
   * séparation, qu'on ne peut pas deviner.
   */
  form?: FormData;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const suffix = params.toString();
  return suffix ? `${path}?${suffix}` : path;
}

async function readError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as ErrorBody;
    if (typeof body.code === 'string' && typeof body.message === 'string') {
      return new ApiError(body, response.status);
    }
  } catch {
    /* réponse non-JSON : on retombe sur un message générique ci-dessous */
  }
  return new ApiError(
    { code: 'http_error', message: `Le serveur a répondu ${response.status}.` },
    response.status,
  );
}

/**
 * Appelle l'API et rend la réponse désérialisée.
 *
 * Lève `ApiError` sur refus métier, `NetworkError` si le serveur n'a pas répondu.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, form, signal, anonymous = false, query } = options;

  const headers: Record<string, string> = { ...options.headers };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const token = anonymous ? null : tokenStore.read();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      ...(form !== undefined ? { body: form } : {}),
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      ...(signal ? { signal } : {}),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new NetworkError(cause);
  }

  if (!response.ok) {
    const error = await readError(response);

    // Une session terminée purge le jeton et prévient l'application, une seule fois et
    // au même endroit : aucun écran n'a à s'en occuper (`AUTH-06`).
    if (error.isSessionExpired && !anonymous) {
      tokenStore.clear();
      for (const listener of expiryListeners) listener(error.message);
    }
    throw error;
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ── Ressources ────────────────────────────────────────

export interface Health {
  status: 'ok';
  version: string;
  environment: string;
  time: string;
  timezone: string;
  storage_configured: boolean;
  auth_configured: boolean;
  ai_enabled: boolean;
}

export interface SessionResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  username: string;
}

export const api = {
  health: (signal?: AbortSignal) =>
    request<Health>('/api/health', { anonymous: true, ...(signal ? { signal } : {}) }),

  login: (username: string, password: string) =>
    request<SessionResponse>('/api/auth/login', {
      method: 'POST',
      body: { username, password },
      anonymous: true,
    }),

  me: (signal?: AbortSignal) =>
    request<{ username: string }>('/api/auth/me', { ...(signal ? { signal } : {}) }),

  logout: () => request<undefined>('/api/auth/logout', { method: 'POST' }),
};
