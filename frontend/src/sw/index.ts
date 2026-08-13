/// <reference lib="webworker" />

/**
 * Le service worker (`L15-02`, `NOT-01`).
 *
 * Il ne décide rien : la règle de cache vit dans [`strategy.ts`](./strategy.ts), qui est
 * pur et testé. Ce fichier est la **plomberie** — ouvrir un cache, servir, poser une
 * notification. Toute règle écrite ici échapperait à la batterie, et son symptôme serait
 * un chiffre d'hier affiché comme celui d'aujourd'hui.
 *
 * Il est bâti à part (`vite.sw.config.ts`) vers `dist/sw.js`, **sans empreinte dans le
 * nom** : un service worker doit vivre à une adresse stable, à la racine de sa portée.
 */

import { strategyFor } from './strategy';

const worker = self as unknown as ServiceWorkerGlobalScope;

/**
 * Le nom du cache porte une version.
 *
 * C'est ce qui rend le remplacement atomique : la nouvelle version remplit son propre
 * cache, et `activate` supprime tous ceux qui ne portent pas ce nom. **À incrémenter
 * quand la forme de ce qui est conservé change**, pas à chaque déploiement — les fichiers
 * de `/assets` sont empreintés, ils ne se périment jamais.
 */
const CACHE = 'metric-v1';

/** L'adresse sous laquelle la coquille est conservée, quel que soit l'écran demandé. */
const SHELL = '/';

// ── Installation et remplacement ──────────────────────

worker.addEventListener('install', (event) => {
  // Seule la coquille est préchargée. Le reste — scripts, styles, polices — se remplit
  // au premier passage : ce sont précisément les fichiers que la page demande pour
  // s'afficher, ils sont donc en cache dès la première visite réussie.
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.add(SHELL))
      // Une installation ne doit pas échouer parce que le réseau a hoqueté : sans ce
      // rattrapage, le worker resterait absent et l'application perdrait ses
      // notifications, qui ne dépendent pourtant d'aucun cache.
      .catch(() => undefined)
      .then(() => worker.skipWaiting()),
  );
});

worker.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(names.filter((name) => name !== CACHE).map((n) => caches.delete(n))),
      )
      .then(() => worker.clients.claim()),
  );
});

// ── Service ───────────────────────────────────────────

/**
 * La coquille, servie du cache et rafraîchie derrière.
 *
 * Un `stale-while-revalidate` est **interdit sur une mesure** et parfaitement légitime
 * ici : le document ne porte aucun chiffre — il ne porte que le squelette et le script de
 * thème. C'est ce qui fait qu'un déploiement se voit au chargement suivant plutôt qu'au
 * troisième.
 */
async function serveShell(request: Request): Promise<Response> {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(SHELL);

  const fresh = fetch(request).then((response) => {
    if (response.ok) void cache.put(SHELL, response.clone());
    return response;
  });

  if (cached) {
    // Le refus du réseau est avalé **ici et pas ailleurs** : hors ligne, la coquille en
    // cache est la bonne réponse, et une promesse rejetée sans preneur ferait du bruit
    // dans la console à chaque navigation.
    void fresh.catch(() => undefined);
    return cached;
  }
  return fresh;
}

/** Une ressource immuable : le cache d'abord, le réseau au premier passage. */
async function serveAsset(request: Request): Promise<Response> {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;

  const response = await fetch(request);
  // Seules les réponses complètes sont conservées : un `206` partiel ou un `404` mis en
  // cache se resservirait indéfiniment.
  if (response.ok) void cache.put(request, response.clone());
  return response;
}

worker.addEventListener('fetch', (event) => {
  const { request } = event;
  const strategy = strategyFor(new URL(request.url), {
    appOrigin: worker.location.origin,
    navigation: request.mode === 'navigate',
    method: request.method,
  });

  // `network` ne rappelle même pas `event.respondWith` : la requête suit son cours
  // normal, sans que le worker s'interpose. C'est un chemin de moins où se tromper.
  if (strategy === 'network') return;

  event.respondWith(strategy === 'shell' ? serveShell(request) : serveAsset(request));
});

// ── Notifications (`NOT-01`) ──────────────────────────

/** Ce que le serveur envoie dans une notification. */
interface PushPayload {
  title?: string;
  body?: string;
  tag?: string;
  url?: string;
}

/**
 * Repli quand la charge utile est illisible.
 *
 * Ne rien afficher n'est pas une option : plusieurs navigateurs posent alors eux-mêmes un
 * « ce site a été mis à jour en arrière-plan », qui est à la fois faux et impossible à
 * corriger. On affiche donc le strict minimum — et **rien qui ressemble à une donnée** :
 * ni chiffre, ni affirmation sur ce que l'utilisateur a fait ou non.
 */
const REPLI = { title: 'Metric', body: 'Ouvre l’application.' } as const;

function read(data: PushEvent['data']): PushPayload {
  if (!data) return REPLI;
  try {
    const parsed: unknown = data.json();
    // Aucune assertion : les quatre champs de `PushPayload` étant facultatifs, un objet
    // quelconque lui est assignable — et chaque champ est relu avec son propre repli
    // plus bas. Une charge utile bancale donne donc le texte neutre, jamais une
    // exception dans un service worker, où personne ne la verrait.
    return typeof parsed === 'object' && parsed !== null ? parsed : REPLI;
  } catch {
    return REPLI;
  }
}

worker.addEventListener('push', (event) => {
  const payload = read(event.data);
  event.waitUntil(
    worker.registration.showNotification(payload.title ?? REPLI.title, {
      body: payload.body ?? REPLI.body,
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      // Le `tag` remplace une notification du même type au lieu de l'empiler : deux
      // rappels de suppléments à deux jours d'intervalle ne doivent pas laisser deux
      // lignes dans le centre de notifications.
      tag: payload.tag ?? 'metric',
      data: { url: payload.url ?? '/' },
    }),
  );
});

worker.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data as { url?: string } | undefined)?.url ?? '/';

  event.waitUntil(
    worker.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      // Une fenêtre déjà ouverte est reprise plutôt que doublée : sur iOS en mode
      // autonome, ouvrir une seconde fenêtre remplace l'application par elle-même et
      // perd ce qui était saisi.
      for (const client of clients) {
        if ('focus' in client) return client.focus().then((c) => c.navigate(target));
      }
      return worker.clients.openWindow(target);
    }),
  );
});
