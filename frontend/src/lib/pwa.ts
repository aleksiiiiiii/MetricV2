/**
 * Enregistrement du service worker (`L15-02`).
 *
 * **Uniquement dans le build de production.** En développement, Vite sert les modules un
 * par un et remplace à chaud : un worker qui s'interpose sur `/assets` y servirait des
 * fichiers périmés, et l'on passerait la journée à se demander pourquoi une modification
 * ne se voit pas. La contrepartie est réelle et notée dans
 * `docs/verifications-manuelles.md` — le worker ne s'éprouve qu'après `npm run build`.
 */

/** Vrai si le navigateur peut porter un service worker **dans ce contexte**. */
export function swSupported(): boolean {
  // `isSecureContext` couvre le vrai motif d'échec : `https://` et `localhost` passent,
  // une adresse IP de réseau local non. C'est exactement le cas de `make dev-lan`, et le
  // dire ainsi vaut mieux qu'un `serviceWorker in navigator` qui serait vrai sans
  // qu'aucun enregistrement n'aboutisse.
  return 'serviceWorker' in navigator && window.isSecureContext;
}

/**
 * Enregistre le worker, ou ne fait rien.
 *
 * Ne lève jamais : l'application entière fonctionne sans worker — il n'apporte que
 * l'ouverture hors ligne de la coquille et la réception des rappels. C'est `IA-07`
 * appliqué à autre chose que l'IA : un confort n'est jamais un prérequis.
 */
export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!import.meta.env.PROD || !swSupported()) return null;

  try {
    return await navigator.serviceWorker.register('/sw.js', { scope: '/' });
  } catch {
    return null;
  }
}
