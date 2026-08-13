/**
 * Ce que le service worker a le droit de mettre en cache (`L15-02`).
 *
 * **Ce module est pur.** Il ne connaît ni `caches`, ni `fetch`, ni `self` : on lui donne
 * une URL et la forme de la requête, il rend une stratégie. C'est le même parti pris que
 * `heatmap/engine.py` côté serveur — ce qui juge ne lit rien — et il est ici pour la même
 * raison : la règle qui décide se vérifie sans monter l'appareil qui l'applique.
 *
 * ── La règle, et ce qu'elle protège ────────────────────────────────────────
 *
 * Un écran servi depuis le cache avec les chiffres d'hier est une **valeur inventée à
 * l'écran**, au sens le plus littéral de l'invariant. Et c'est le pire cas possible : il
 * n'y a ni tiret, ni « chargement… », ni message d'erreur — il y a un poids, et il est
 * faux. Rien à l'écran ne permet de s'en apercevoir.
 *
 * D'où la frontière, qui n'a qu'un seul endroit où être écrite :
 *
 * | Ce qui est demandé          | Stratégie | Pourquoi                                |
 * |-----------------------------|-----------|------------------------------------------|
 * | tout ce qui commence par `/api` | `network` | c'est une **mesure**                 |
 * | une navigation              | `shell`   | la coquille ne porte aucun chiffre       |
 * | `/assets`, polices, icônes  | `asset`   | noms empreintés, donc immuables          |
 * | une autre origine           | `network` | ce n'est pas à nous                      |
 * | tout le reste               | `network` | on ne met en cache que ce qu'on a nommé  |
 *
 * La dernière ligne est délibérée : **le défaut est de ne pas mettre en cache.** Une
 * ressource ajoutée demain et oubliée ici passera par le réseau — ce qui coûte une
 * requête, là où l'oubli inverse coûterait un chiffre faux.
 */

/** Les trois seules réponses possibles. */
export type Strategy =
  /** Réseau, sans repli et sans écriture en cache. */
  | 'network'
  /** Coquille en cache, rafraîchie derrière. Le document ne porte aucune donnée. */
  | 'shell'
  /** Cache d'abord, réseau au premier passage. Réservé à l'immuable. */
  | 'asset';

/** Ce que le worker sait d'une requête, réduit à ce qui décide. */
export interface RequestShape {
  /** Origine de l'application — `self.location.origin` dans le worker. */
  readonly appOrigin: string;
  /** Vrai pour une requête de document (`request.mode === 'navigate'`). */
  readonly navigation: boolean;
  /** Verbe HTTP. Une écriture n'est jamais servie ni conservée. */
  readonly method: string;
}

/**
 * Préfixes mis en cache, et **rien d'autre**.
 *
 * `/assets` porte les fichiers empreintés produits par Vite : leur nom change à chaque
 * contenu, donc un cache d'abord ne peut pas servir une version périmée. `/fonts` et
 * `/icons` sont des fichiers versionnés du dépôt, et le manifeste est lu par le système
 * au moment de l'installation, parfois hors ligne.
 */
const CACHEABLE = ['/assets/', '/fonts/', '/icons/'] as const;

/** Fichiers isolés, à leur adresse exacte. */
const CACHEABLE_EXACT = ['/manifest.webmanifest', '/favicon.ico'] as const;

/**
 * Vrai si le chemin est celui de l'API.
 *
 * Comparaison sur le **segment** et non sur le préfixe : `startsWith('/api')` accepterait
 * `/apiary`, qui n'est pas l'API et se retrouverait traité comme elle. Ici l'erreur irait
 * dans le sens sûr — pas de cache —, mais une frontière qui ne dit pas exactement ce
 * qu'elle croit dire finit par se tromper dans l'autre sens.
 */
export function isApi(pathname: string): boolean {
  return pathname === '/api' || pathname.startsWith('/api/');
}

/**
 * La stratégie à appliquer.
 *
 * L'ordre des tests est la règle elle-même, et il se lit de haut en bas :
 * l'API l'emporte sur tout, y compris sur une navigation.
 */
export function strategyFor(url: URL, request: RequestShape): Strategy {
  // Une écriture ne se met jamais en cache, et ne se sert jamais depuis le cache.
  // Rejouer un `POST` depuis un cache écrirait deux fois.
  if (request.method !== 'GET') return 'network';

  // Ce qui n'est pas à nous ne rentre pas : une police tierce, une image distante, un
  // service push. On ne conserve rien qu'on ne sait pas invalider.
  if (url.origin !== request.appOrigin) return 'network';

  // La mesure, avant tout le reste.
  if (isApi(url.pathname)) return 'network';

  if (request.navigation) return 'shell';

  if (CACHEABLE.some((prefix) => url.pathname.startsWith(prefix))) return 'asset';
  if (CACHEABLE_EXACT.includes(url.pathname as (typeof CACHEABLE_EXACT)[number])) return 'asset';

  return 'network';
}
