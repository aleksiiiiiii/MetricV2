/**
 * L'abonnement push, côté navigateur (`NOT-01`).
 *
 * Ce module ne parle **pas** à l'API de Metric : il parle au navigateur. Les appels
 * serveur vivent dans `features/notifications/api.ts`, et le partage suit celui du reste
 * du front — un `features/<domaine>/api.ts` ne contient que des types et des appels.
 *
 * ── Ce qu'il faut savoir sur iOS ──────────────────────────────────────────
 *
 * Safari n'expose `pushManager` **qu'une fois l'application ajoutée à l'écran d'accueil**.
 * Dans l'onglet, `Notification` existe, `serviceWorker` existe, et l'abonnement échoue.
 * D'où `pushSupport()`, qui distingue trois états au lieu d'un booléen : ce n'est pas la
 * même chose de dire « ton navigateur ne sait pas faire » et « ajoute Metric à ton écran
 * d'accueil, puis reviens ».
 */

/** Ce que le navigateur permet, ici et maintenant. */
export type PushSupport =
  /** Tout est là : on peut demander l'autorisation. */
  | 'ok'
  /** Le contexte n'est pas sécurisé — `http://` sur une IP de réseau local. */
  | 'insecure'
  /** iOS dans un onglet : il faut d'abord ajouter à l'écran d'accueil. */
  | 'needs-install'
  /** Ce navigateur ne sait pas recevoir de notifications push. */
  | 'unsupported';

export function pushSupport(): PushSupport {
  if (!('serviceWorker' in navigator) || !('Notification' in window)) return 'unsupported';
  // Un service worker exige un contexte sécurisé. `localhost` en est un, `172.20.10.10`
  // non — c'est exactement le cas de `make dev-lan`, et le dire évite de chercher
  // longtemps.
  if (!window.isSecureContext) return 'insecure';
  // `typeof` et non `'PushManager' in window` : le second est vrai *au type* — lib.dom
  // déclare `PushManager` sur `Window` —, si bien que TypeScript réduit la branche
  // négative à `never`. Ce qu'on veut savoir est ce que le navigateur expose à
  // l'exécution, et Safari iOS ne l'expose qu'une fois l'application installée.
  if (typeof window.PushManager === 'undefined') {
    // Sur un navigateur qui ne le porte tout simplement pas, `standalone` est indéfini :
    // on distingue « ajoute Metric à ton écran d'accueil » de « ce navigateur ne sait
    // pas faire ». Ce ne sont pas les mêmes conduites à tenir.
    const installed =
      window.matchMedia('(display-mode: standalone)').matches ||
      (navigator as { standalone?: boolean }).standalone === true;
    return installed ? 'unsupported' : 'needs-install';
  }
  return 'ok';
}

/**
 * Convertit une clé publique base64url en octets.
 *
 * `applicationServerKey` n'accepte pas la chaîne : il lui faut les 65 octets bruts du
 * point non compressé. Le remplissage `=` et l'alphabet URL sont ce qui distingue le
 * base64url du base64 — les traduire est le seul « calcul » de ce fichier.
 */
function decodeKey(base64url: string): Uint8Array {
  const padded = base64url.padEnd(base64url.length + ((4 - (base64url.length % 4)) % 4), '=');
  const binary = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

/** L'abonnement de cet appareil, sous la forme que l'API attend. */
export interface BrowserSubscription {
  endpoint: string;
  p256dh: string;
  auth: string;
  user_agent: string;
}

function encodeKey(buffer: ArrayBuffer | null): string {
  if (!buffer) return '';
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function shape(subscription: PushSubscription): BrowserSubscription {
  return {
    endpoint: subscription.endpoint,
    p256dh: encodeKey(subscription.getKey('p256dh')),
    auth: encodeKey(subscription.getKey('auth')),
    user_agent: navigator.userAgent.slice(0, 255),
  };
}

/**
 * Demande l'autorisation et abonne cet appareil.
 *
 * Rend `null` si l'utilisateur refuse — **et c'est une réponse, pas une erreur**. Un refus
 * de notifications ne doit rien casser : c'est le même régime que `IA-07`, un confort
 * n'est jamais un prérequis.
 *
 * Lève si le navigateur ou le service push refuse pour une autre raison : là, l'écran a
 * quelque chose à dire.
 */
export async function subscribeThisDevice(publicKey: string): Promise<BrowserSubscription | null> {
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return null;

  const registration = await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  // Un abonnement déjà en place est réemployé tel quel : le serveur est idempotent par
  // `endpoint`, et en créer un second laisserait le premier vivant côté service push.
  if (existing) return shape(existing);

  const created = await registration.pushManager.subscribe({
    // Exigé par Chrome, et de toute façon le seul usage honnête : chaque notification de
    // Metric porte un texte. Une notification silencieuse n'aurait rien à dire.
    userVisibleOnly: true,
    applicationServerKey: decodeKey(publicKey) as BufferSource,
  });
  return shape(created);
}

/**
 * Désabonne cet appareil auprès du navigateur.
 *
 * Rend l'`endpoint` retiré, pour que l'appelant sache **quelle** ligne effacer côté
 * serveur ; `null` s'il n'y avait pas d'abonnement.
 */
export async function unsubscribeThisDevice(): Promise<string | null> {
  if (pushSupport() !== 'ok') return null;

  const registration = await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  if (!existing) return null;

  const { endpoint } = existing;
  await existing.unsubscribe();
  return endpoint;
}

/** L'`endpoint` de cet appareil, s'il est abonné. Sert à savoir quoi afficher. */
export async function currentEndpoint(): Promise<string | null> {
  if (pushSupport() !== 'ok') return null;
  try {
    const registration = await navigator.serviceWorker.ready;
    return (await registration.pushManager.getSubscription())?.endpoint ?? null;
  } catch {
    return null;
  }
}
