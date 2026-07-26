/**
 * Sonde de santé (`API-04`).
 *
 * Client volontairement rudimentaire : le client API complet — jeton, décodage des
 * codes d'erreur `API-07`, invalidations TanStack Query — est construit au lot L03.
 * Cette sonde ne sert qu'à prouver que le proxy Vite atteint bien uvicorn.
 */

export interface Health {
  status: 'ok';
  version: string;
  environment: string;
  time: string;
  timezone: string;
  storage_configured: boolean;
  ai_enabled: boolean;
}

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch('/api/health', signal ? { signal } : undefined);
  if (!response.ok) {
    throw new Error(`L'API a répondu ${response.status}`);
  }
  return (await response.json()) as Health;
}
