# Journal des modifications

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Versionnement : une version mineure par lot de la [feuille de route](ROADMAP.md).

## [0.8.0] — 2026-07-27

Lot **L07 — Nutrition & fichiers binaires**. Le premier lot où un bug de chemin devient
une faille. 381 tests backend dont **35 de sécurité**, 86 frontend.

### Ajouté

- **Repas** (`NUT-01` → `NUT-03`, `NUT-05` → `NUT-07`, `NUT-09`) — photo et/ou
  description, rangement daté, type présélectionné par le serveur, macros manuelles,
  totaux du jour, liste bornée ou complète, correction préservant photo et provenance.
- **Repas favoris** (`NUT-10`) — ce qui revient chaque jour se rejoue en une action.
- **Service sécurisé des photos** (`NUT-08`) — endpoint authentifié, forme de chemin
  imposée, réponses cachables un an et non reniflables.
- **Écran Nutrition** — anneau de protéines, journal avec vignettes chargées **avec le
  jeton de session** (un `<img src>` naïf recevrait un 401), saisie photo avec aperçu.
- Le client API sait désormais envoyer un formulaire multipart, en laissant au navigateur
  le soin d'y poser la frontière de séparation.

### Sécurité

Trois décisions, toutes vérifiées par des tests écrits du point de vue de quelqu'un qui
essaie de sortir du dossier :

- **La forme prime sur le nettoyage.** Un chemin qui ne correspond pas exactement à
  `AAAA/MM/JJ/horodatage-aléa.ext` est refusé, sans tentative de le réparer. Huit
  tentatives d'évasion testées — `../`, encodage URL, chemin absolu, octet nul,
  antislash, double encodage.
- **Le contenu décide du type**, jamais le nom de fichier ni le `Content-Type` annoncé
  par le client. Servir des octets arbitraires sous un type d'image offrirait une surface
  au navigateur.
- **Un chemin mal formé et un chemin absent rendent le même 404.** Les distinguer
  renseignerait sur l'arborescence.

### Décidé

- Supprimer un repas **ne supprime pas sa photo**. Elle est rangée par date et
  consultable hors de l'app ; l'effacer d'un clic dans une liste ferait perdre un souvenir
  qu'aucune annulation ne rendrait. La suppression du fichier reste manuelle, et assumée.
- Le total de calories est accompagné du **nombre de repas réellement renseignés** : un
  total sur deux repas sur cinq ne veut pas dire grand-chose, et l'écran doit pouvoir le
  nuancer plutôt que d'afficher un chiffre trompeur.

## [0.7.0] — 2026-07-27

Lot **L06 — Hydratation & suppléments**. Les deux domaines « en un geste », et les
dernières sources dont le moteur d'assiduité aura besoin. 311 tests backend, 72 frontend.

### Ajouté

- **Hydratation** (`HYD-01` → `HYD-05`) — prise horodatée avec son décalage, raccourcis
  de volume paramétrables, total du jour face à l'objectif, série complète sur 30 jours,
  moyennes 7 et 30 j, jours ayant atteint l'objectif.
- **Suppléments** (`SUP-01` → `SUP-06`) — planning trié par horaire, checklist du jour qui
  repart vierge chaque matin, série par item, ratio et booléen « journée complète ».
  Cocher écrit une prise horodatée, décocher la supprime — et elle seule.
- **`app/core/dates.py`** — le jour local et la semaine ISO n'ont plus qu'une
  implémentation. Deux endroits qui découpent le temps finissent par donner deux totaux
  pour la même journée.
- **`app/core/cadence.py`** — grammaire des cadences, validée à la saisie et normalisée.
  La décision **D3** lie `schedule.frequency` au futur journal d'historisation : sans
  normalisation, deux écritures équivalentes enregistreraient un changement de cadence
  qui n'en est pas un. Ce module ne décide pas encore si un jour est validé.
- **Écran Routine** — anneau d'hydratation, raccourcis en un geste, checklist groupée par
  moment de la journée, planning avec sa cadence en clair.
- **Bascule optimiste** (`SUP-04`) — la case se coche avant la réponse du serveur et se
  **restaure** si elle est refusée. Attendre un aller-retour vers Nextcloud pour voir une
  case bouger condamnerait la saisie en un geste.

### Vérifié

- **La frontière de jour.** Une prise à 23 h 30 appartient au jour qu'affiche l'horloge ;
  une prise à 0 h 30 au jour qui commence ; un horodatage sans fuseau — le cas d'une
  ligne saisie dans un tableur — est lu comme local et non comme UTC (`HEAT-32`).
- **Une valeur de réglage contenant des virgules** dans un fichier qui les utilise comme
  séparateur : elle doit être protégée par des guillemets. Notre écrivain le fait, un
  test le prouve — mais une ligne ajoutée à la main sans guillemets serait tronquée
  silencieusement.

## [0.6.0] — 2026-07-26

Lot **L05 — Activité sportive**. Le plus gros domaine du backlog, 18 fonctionnalités, et
la source de six des neuf pistes d'assiduité à venir. 241 tests backend, 61 frontend.

### Ajouté

- **Courses** (`ACT-01`, `ACT-02`, `ACT-05`) — saisie en formats souples : `44:12`,
  `1:18:44`, `44`, `44,5`, `1h30`, et `5mi` converti en kilomètres. Allure dérivée **et
  stockée**, vitesse dans le détail.
- **Séances** (`ACT-03`, `ACT-04`, `ACT-18`) — identifiant stable qui survit aux
  corrections, effort perçu 1–10, sept types suggérés sans contrainte. Supprimer une
  séance purge ses exercices.
- **Catalogue et journal** (`ACT-06` → `ACT-09`) — neuf groupes musculaires, charge ×
  séries × réps, charge 0 = poids du corps, et le rappel de la dernière performance à la
  sélection d'un exercice.
- **Agrégats** (`ACT-10` → `ACT-16`) — volume par jour avec repos distingué de zéro,
  totaux de semaine ISO, huit semaines d'historique, historique fusionné, tonnage par
  groupe, records et 1RM par Epley, groupes négligés.
- **Duplication d'une séance** (`ACT-17`) — exercices compris, sans hériter du RPE :
  l'effort perçu appartient à la séance vécue, pas au modèle.
- **`app/core/parsing.py`** — analyse des durées, distances et décimales françaises,
  placé dans le socle parce que l'import Apple (`IMP-03`) devra normaliser exactement les
  mêmes formats.
- **`remove_where`** sur le dépôt CSV — suppression en cascade en une écriture, plutôt
  qu'une par ligne qui laisserait le fichier dans un état intermédiaire.
- **Écran Activité** — semaine, volume par jour, tonnage, groupes négligés, progression
  des charges, historique fusionné, saisie de course et de séance, journal d'exercices et
  catalogue.

### Corrigé

- Deux champs portaient le libellé « Durée » sur la même page : ambigu pour un lecteur
  d'écran comme pour un test. Celui de la séance est désormais « Durée de séance ».

### Choix de modélisation

- `exercise_log.csv` **duplique** le nom de l'exercice et son groupe musculaire alors
  qu'il porte déjà `exercise_id`. `ACT-06` exige que retirer un exercice conserve
  l'historique : sans duplication, une ligne deviendrait illisible dès que son exercice
  disparaît, et le fichier doit rester compréhensible seul dans un tableur.
- Un groupe musculaire jamais travaillé rend `null` et non un grand nombre : « jamais »
  et « il y a très longtemps » ne se traitent pas pareil, et une valeur inventée
  fausserait la génération IA de planning (`PLAN-03`).

## [0.5.0] — 2026-07-26

Lot **L04 — Corps : poids et mensurations**. Première tranche verticale complète, et
patron des cinq domaines suivants. 169 tests backend, 49 frontend.

### Ajouté

- **Pesées** (`BODY-01` → `BODY-06`) — saisie bornée, correction et suppression sous
  garde, indicateurs, série chronologique, tendance lissée et historique paginé, le tout
  en **une seule requête** par écran.
- **Mensurations** (`BODY-07` → `BODY-10`) — six mesures facultatives dont la masse
  grasse, au moins une requise. Chaque mesure garde son propre historique : « le relevé
  précédent » d'un tour de bras n'est pas forcément la ligne d'avant.
- **Écran Corps** — quatre chiffres clés, courbe de poids avec tendance superposée sur le
  même axe, saisie, historique éditable, panneau mensurations. Aucune valeur inventée :
  sur historique vide, l'écran dit ce que coûte le prochain geste.
- **Jeton de ligne** — chaque entrée porte l'empreinte de son contenu ; modifier ou
  supprimer exige de la renvoyer en `If-Match` (`STO-05`). Un en-tête absent est un
  conflit, jamais une permission — sinon la garde se contournerait en l'omettant.
- **Lecteur de réglages** — `settings/settings.csv` avec les défauts de l'annexe, pour
  que l'écart au poids cible ne soit pas une constante codée en dur.
- **Superposition dans `Chart`** — une série partageant l'unité de la principale se trace
  sur le **même axe**, contrairement à la série de contexte.
- [`docs/patron-domaine.md`](docs/patron-domaine.md) — les quatre fichiers, les deux
  pièges de calcul rencontrés, les huit familles de tests, et une liste de reprise.

### Corrigé

- **`test_every_data_route_requires_a_token` ne vérifiait rien.** Il parcourait
  `app.routes`, où FastAPI n'aplatit pas les routeurs inclus : la seule route visible
  était la santé, justement exemptée. Il lit désormais le schéma OpenAPI publié, et un
  second test interroge réellement chaque lecture sans jeton.
- **`check-storage` ne diagnostiquait pas l'erreur de configuration la plus probable.**
  Une `NEXTCLOUD_URL` pointant sur la racine du site donne un « ressource introuvable »
  incompréhensible ; le script nomme la cause et donne la ligne à coller.

### Vérifié

- Stockage éprouvé contre le **vrai Nextcloud** : écriture, relecture identique, `304`
  honoré sur lecture conditionnelle, nettoyage. Le point resté ouvert depuis le lot L01
  est fermé.

## [0.4.0] — 2026-07-26

Lot **L03 — Design system et coquille applicative**. Le jalon I est bouclé : l'application
se connecte, navigue, et dispose de toute la bibliothèque visuelle. 37 tests frontend.

### Ajouté

- **18 composants** repris de la charte : `Button` (5 variantes), `Card`, `Badge`,
  `Field`, `Rule`, `Eyebrow`, `Segmented`, `Empty`, `AiBlock`, `Stat`, `Sparkline`,
  `Bars`, `Progress`, `Ring`, `Table`, `Check`, `Heatmap`, `Chart`, `Toaster`.
- **`Heatmap`** — six états distincts, dont la distinction qui compte : `off` (rien
  n'était attendu) et `missed` (attendu, non validé) ne se ressemblent pas. Une piste
  « deux fois par semaine » est majoritairement grise, et une grille grise ne doit pas se
  lire comme un échec (`HEAT-05`). Le composant ne décide rien : états et niveaux
  viennent du serveur (`HEAT-30`).
- **`Chart`** — axe gradué, aire dégradée, série de contexte en pointillé, bande
  inférieure à seuil d'alerte, curseur et infobulle suiveuse.
- **Client API typé** — injection du jeton, décodage de l'enveloppe `{code, message,
  fields}`, distinction entre panne réseau et refus métier, et purge du jeton sur session
  expirée en un seul endroit (`AUTH-06`).
- **Écran de connexion et routes protégées** — le jeton présent au démarrage est
  **confronté au serveur** plutôt que cru sur parole ; sans cela un jeton expiré pendant
  que l'app était fermée afficherait l'application puis ferait échouer chaque écran.
- **TanStack Query configuré** — clés nommées par domaine, réessai réservé aux pannes
  passagères. Une mutation n'est jamais rejouée : réessayer une écriture en conflit est
  le meilleur moyen d'écraser la mauvaise ligne (`STO-05`).
- **Formateurs** — dates FR, `mm:ss` / `h:mm:ss`, allure, volumes, virgule décimale, et
  une sérialisation de date en **heure locale** : `toISOString()` rattacherait au mauvais
  jour une saisie faite après minuit (`HEAT-32`).
- Galerie de charte complète sur `/_kitchen-sink`, **publique** : aucune donnée
  utilisateur, consultable sans session, et vérifiable par capture automatisée.

### Corrigé

- `tokenStore` avalait silencieusement l'indisponibilité de `localStorage`, ce qui aurait
  fait perdre la session au premier rechargement sans rien annoncer — navigation privée
  Safari, cookies bloqués. Repli en mémoire détecté à l'exécution, et `persistent`
  permet de le signaler.

### Retiré

- L'écran d'attente `Home` du lot L00, remplacé par le tableau de bord et l'écran de
  connexion.

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
