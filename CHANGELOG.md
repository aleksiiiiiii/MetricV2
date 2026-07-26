# Journal des modifications

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Versionnement : une version mineure par lot de la [feuille de route](ROADMAP.md).

## [0.3.0] — 2026-07-26

Lot **L02 — Socle API + authentification**. L'API est désormais close : plus aucune route
de données n'est joignable sans jeton. 134 tests backend, 96 % de couverture.

### Ajouté

- **Connexion mono-utilisateur** (`AUTH-01` → `AUTH-03`) — Argon2id, JWT signé de 7 jours,
  `Authorization: Bearer`. La session survit à la fermeture de l'app et au redémarrage.
- **Anti-brute-force** (`AUTH-04`) — 5 échecs / 60 s / adresse, fenêtre glissante en
  mémoire, `429` annonçant le délai en corps et en en-tête `Retry-After`. Trois détails
  qui font la différence : Argon2 est exécuté **même sur identifiant inconnu** (sinon le
  temps de réponse dirait lequel des deux champs est faux), le quota est consulté **avant**
  de hacher (sinon l'attaque coûterait plus au serveur qu'à l'attaquant), et une réussite
  remet le compteur à zéro.
- **Protection des routes** (`AUTH-05`) — portée sur le groupe de routeurs de données, pas
  route par route : un endpoint ajouté par un lot ultérieur est protégé par construction.
  Un test structurel le vérifie à chaque exécution.
- **`make hash-password`** (`AUTH-08`) — saisie sans écho, jamais de mot de passe en clair
  sur disque ni en argument de commande, propose aussi un `JWT_SECRET`.
- **Catalogue d'erreurs** (`API-07`) — un module unique, codes machine stables, messages
  français. Quatre gestionnaires couvrent le métier, la validation, les erreurs de FastAPI
  et l'imprévu — aucun traceback ne sort jamais dans une réponse.
- **Socle de validation** (`API-06`) — 18 types bornés réutilisables, et une règle
  « jamais dans le futur » évaluée en **heure locale** : à 1 h du matin à Paris, `date.today()`
  en UTC serait encore la veille et refuserait une pesée légitime.
- **Découpage par domaine** (`API-01`) — 12 routeurs préfixés, prêts à recevoir leurs
  routes lot par lot.
- **Refus de démarrer en production** avec un secret de développement, un hash de mot de
  passe absent ou un stockage non configuré (`API-02`).
- `/api/health` annonce désormais aussi `auth_configured`.

### Modifié

- `StorageError` descend de `MetricError` : un seul gestionnaire traduit tout le catalogue.
- Les messages d'erreur de FastAPI sont traduits — un 404 de routage répondait
  « Not Found » en anglais alors que l'API est francophone.
- `DEV_JWT_SECRET` allongé à 50 caractères : PyJWT signale toute clé HMAC de moins de
  32 octets comme trop courte pour SHA-256 (RFC 7518 §3.2).

### Non vérifié

- `make check-storage` contre un vrai Nextcloud : `NEXTCLOUD_USERNAME` et
  `NEXTCLOUD_PASSWORD` sont encore vides dans `.env`.

## [0.2.0] — 2026-07-26

Lot **L01 — Couche stockage WebDAV + CSV**. La pièce la plus risquée du projet : tout le
reste s'appuie dessus. Aucune fonctionnalité visible, mais 79 tests backend et 95 % de
couverture sur la couche stockage.

### Ajouté

- **Client WebDAV** (`STO-01`, `STO-08`) — GET / PUT / DELETE / MKCOL / PROPFIND, pool de
  connexions borné et maintenu en keep-alive, réessais sur erreur de transport, `429`,
  `423` (verrou Nextcloud) et 5xx, `Retry-After` honoré qu'il soit exprimé en secondes ou
  en date HTTP, backoff exponentiel plafonné avec gigue. L'attente est injectable : les
  délais sont testés sans être subis.
- **Erreurs typées** (`STO-09`, `API-07`) — chaque panne porte un code machine stable
  (`storage_unavailable`, `conflict`, `storage_not_configured`…) et un message français.
  Jamais de 500 brute ; le détail technique va dans les journaux, pas dans la réponse.
- **Cache des lectures** (`STO-06`, décision **D8**) — TTL de 30 s, puis revalidation
  conditionnelle par ETag. Un tableau de bord qui tire dix fichiers ne fait pas dix
  requêtes, et une modification faite depuis un autre appareil ou un tableur est
  rattrapée : l'invalidation ne suit pas seulement nos propres écritures.
- **Dépôt CSV typé** (`STO-02` → `STO-05`) — modèles Pydantic, migration d'en-tête
  automatique, garde anti-conflit par valeurs attendues doublée d'un `If-Match` sur
  l'ETag du fichier, lecture fraîche forcée avant toute écriture sous garde.
- **Fichiers binaires** (`STO-07`) — arborescence datée `AAAA/MM/JJ`, création des
  parents une seule fois, hors du cache CSV.
- **`make check-storage`** (`STO-11`) — écrit, relit, vérifie la revalidation
  conditionnelle et nettoie derrière lui. Diagnostique une configuration absente, de
  mauvais identifiants ou un serveur sans ETag sans jamais lever de traceback.
- **Faux serveur WebDAV ASGI** en mémoire, avec injection de pannes : conflit, coupure
  réseau, `429` avec `Retry-After`, verrou de fichier, serveur qui n'annonce aucun ETag.
- Cycle de vie de la couche stockage piloté par le `lifespan` de FastAPI, et dépendance
  `StoreDep` pour les domaines à venir.

### Corrigé

- `FileStore` remplaçait silencieusement le cache qu'on lui passait : `FileCache` définit
  `__len__`, donc un cache vide est *falsy* et `cache or FileCache()` le jetait.
- `ensure_collection("")` ne créait rien, si bien que le dossier racine des données
  n'existait jamais au premier démarrage — le premier `PUT` aurait échoué en `409`
  incompréhensible.
- `CsvModel.from_csv` forçait `None` sur une colonne absente au lieu de laisser le défaut
  du modèle s'appliquer, ce qui invalidait toute ligne ancienne dès l'ajout d'une colonne
  et vidait `STO-04` de son sens.

### Modifié

- Exceptions de stockage suffixées `Error` (`StorageConflictError`, `StorageNotFoundError`…)
  conformément à la convention Python plutôt qu'en silençant la règle de lint.
- `CsvRepository` utilise la syntaxe générique PEP 695 (`class CsvRepository[TModel]`).
- `pytest-asyncio` en mode `auto` : la couche stockage est asynchrone de bout en bout.

### Non vérifié

- `make check-storage` contre un vrai Nextcloud : impossible sans identifiants. Le
  développement s'est fait contre le double ASGI.

## [0.1.0] — 2026-07-26

Lot **L00 — Fondations, outillage, tokens UI**. Le dépôt démarre, se teste et parle
déjà la langue visuelle de Metric. Aucune fonctionnalité métier.

### Ajouté

- Dépôt initialisé : `.gitignore`, `.editorconfig`, `README`, réglages VS Code pointant
  sur le venv du backend.
- **Backend** — squelette FastAPI (Python 3.14) : configuration centralisée par
  environnement (`API-02`), route de santé publique `/api/health` (`API-04`), OpenAPI
  sur `/api/docs` (`API-05`), CORS paramétrable (`API-03`). `ruff`, `mypy --strict` et
  `pytest` configurés. 5 tests.
- **Frontend** — Vite 8 + React 19 + TypeScript 6 strict, TanStack Query et React
  Router installés, ESLint + Prettier, Vitest + Testing Library. 5 tests.
- **Tokens UI** extraits de `GuidelinesUI.html` vers `styles/tokens.css`, complétés par
  les composantes RVB des signaux — ce qui permet de dériver les 4 niveaux d'intensité
  d'une heatmap depuis une seule couleur d'accent par piste.
- **Polices servies localement** : Space Grotesk et JetBrains Mono téléchargées par
  `npm run fonts` et versionnées (14 fichiers woff2, 308 ko). Plus aucune dépendance au
  CDN Google — prérequis du fonctionnement hors-ligne (`L15`).
- `base.css` : reset, typographie, primitives de mise en page, règle graduée,
  `prefers-reduced-motion`, chiffres à chasse fixe.
- Page `/_kitchen-sink` : référence visuelle des tokens, test de dérive de la charte.
- Écran d'accueil provisoire sondant `/api/health` : prouve le proxy et illustre la
  dégradation propre quand Nextcloud ou l'IA ne sont pas configurés (`IA-07`).
- `Makefile` (`setup`, `dev`, `check`, `test`, `fmt`, `build`, `fonts`) et
  `scripts/dev.sh` qui lance les deux serveurs et les arrête ensemble.
- `.env.example` documenté et complet.
- CI GitHub Actions : formatage, lint, types, tests des deux côtés, plus build.
- `docker-compose.yml` de développement — écrit, non exécuté (Docker absent de la
  machine ; validation au `L17-01`).

### Décidé

- Les **11 points de spécification** relevés entre `backlogV2.md` et `heat_backlog.md`
  sont arrêtés et consignés au [§3 de la feuille de route](ROADMAP.md#3-points-de-spécification-à-trancher).
- `httpx2` remplace `httpx` dans tout le projet : starlette 1.x déprécie `httpx` pour
  son `TestClient`, et le client WebDAV du lot L01 doit parler la même bibliothèque que
  les tests.
- TypeScript **6.0** et non 7 : `typescript-eslint` exige `<6.1.0`. Le lint prime sur
  la dernière majeure.
- Aucune bibliothèque de graphiques ni kit UI : la charte fournit déjà courbes, barres,
  anneau, heatmap et graphique croisé en SVG.
