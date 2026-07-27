# Metric — Feuille de route & lots de livraison

Plan de construction de l'application **Metric** à partir de zéro, découpé en **lots
versionnés**. Un lot = une version mineure = un incrément démontrable.

**Sources de vérité**
| Document | Rôle | Autorité |
|---|---|---|
| `backlogV2.md` | Domaine métier complet, 13 sections, annexe CSV | Référence globale |
| `heat_backlog.md` | Spec `HEAT` v2 (moteur d'assiduité multi-pistes) | **Remplace** la partie `HEAT` de la section 12 |
| `GuidelinesUI.html` | Tokens, composants, motifs visuels | Référence UI exclusive |

> `backlogV2.md` annonce les sections 1–11 comme « réalisées » : c'est l'état de la v1.
> Ce dépôt est vide, tout est à reconstruire. Le statut est donc traité comme
> **spécification acquise et stable**, pas comme du code existant.

---

## 0. Cadre technique

Stack imposée par `backlogV2.md` (« stack de référence »), complétée là où le backlog
est muet.

### Backend
| Choix | Détail |
|---|---|
| Runtime | Python 3.14 (version présente sur la machine ; le code reste compatible 3.12+) |
| Framework | FastAPI + Pydantic v2 (validation `API-06`, OpenAPI `API-05`) |
| Dépendances | `venv` + `pip`, `pyproject.toml` + `requirements.lock` — `uv` n'est pas installé sur la machine, la bascule reste triviale (même `pyproject`) |
| Stockage | Nextcloud WebDAV via `httpx` + wrapper minimal (GET/PUT/PROPFIND/MKCOL) |
| Auth | `argon2-cffi` (AUTH-02) + `pyjwt` (AUTH-03) |
| Qualité | `pytest`, `ruff`, `mypy --strict` |
| Fuseau | `zoneinfo` Europe/Paris, partout (`HEAT-32`) |

Wrapper WebDAV maison plutôt qu'une lib : on a besoin de 5 verbes, mais de beaucoup de
contrôle sur le retry / `Retry-After` / keep-alive (`STO-08`).

### Frontend
| Choix | Détail |
|---|---|
| Base | React 19 + Vite + TypeScript strict |
| Données | TanStack Query v5 (cache, écriture optimiste `SUP-04`) |
| Routing | React Router v7 (mode déclaratif) |
| Styles | CSS natif + CSS Modules, tokens extraits de `GuidelinesUI.html`. **Aucun kit UI** |
| Graphiques | SVG écrit à la main, repris des patterns des guidelines. **Aucune lib de charts** |
| PWA | `vite-plugin-pwa` (prérequis `NOT-01`, `OPS-01`) |
| Tests | Vitest + Testing Library, Playwright pour les parcours |

Pas de lib de charts : les guidelines fournissent déjà courbes, barres, anneau, heatmap
et graphique croisé en SVG. Une lib imposerait son propre langage visuel et il faudrait
la combattre à chaque écran.

### Arborescence
```
metric/
├── backend/
│   ├── app/
│   │   ├── main.py  config.py
│   │   ├── core/            # sécurité, erreurs typées, dépendances FastAPI
│   │   ├── storage/         # webdav.py  csv_repo.py  cache.py  migrations.py
│   │   ├── domains/         # body activity nutrition hydration supplements
│   │   │                    # planning goals settings aggregates heatmap
│   │   │                    # (chacun : models / repository / service / router)
│   │   ├── ai/              # openrouter.py  prompts/  extract.py  images.py
│   │   └── scripts/         # hash_password.py  check_storage.py
│   └── tests/
├── frontend/
│   └── src/
│       ├── styles/          # tokens.css  base.css
│       ├── components/ui/   # Button Card Stat Badge Field Heatmap Chart Check …
│       ├── features/<domaine>/
│       ├── lib/             # api client, queryClient, auth, formats
│       └── routes/
├── docs/
├── docker-compose.yml
├── CHANGELOG.md
└── ROADMAP.md
```

Un dossier par domaine, avec la même structure quadruple. C'est ce qui rend `API-01`
(« chaque domaine testable isolément ») vrai dans les faits et pas seulement sur le
papier.

### Convention de versioning
- **SemVer** en `0.x` jusqu'au périmètre complet, `1.0.0` à la mise en production.
- **1 lot = 1 version mineure.** Tag `v0.N.0` à la clôture du lot, correctifs en `0.N.x`.
- Branche `main` toujours déployable ; un lot = une branche `feat/lot-NN-slug`.
- **Conventional commits** (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`),
  scope = domaine (`feat(heatmap): …`).
- `CHANGELOG.md` alimenté à la clôture de chaque lot (Keep a Changelog).
- Un lot n'est clos que si sa **DoD** est intégralement vérifiée. Pas de lot « clos à 90 % ».

### Définition de « terminé » (transverse, tout lot)
- [ ] Endpoints typés, validés (`API-06`), erreurs à code machine stable (`API-07`)
- [ ] Tests unitaires sur les règles de calcul + tests d'API sur les cas limites
- [ ] Aucune règle métier réimplémentée côté client
- [ ] UI conforme aux tokens des guidelines (zéro couleur / police en dur)
- [ ] États vide / chargement / erreur traités, pas seulement le cas nominal
- [ ] `ruff` + `mypy --strict` + `tsc --noEmit` au vert
- [ ] `CHANGELOG.md` mis à jour, tag posé

---

## 1. Vue d'ensemble des lots

| Lot | Version | Titre | Dépend de |
|---|---|---|---|
| **Jalon I — Socle** | | | |
| L00 | `v0.1.0` | Fondations, outillage, tokens UI | — |
| L01 | `v0.2.0` | Couche stockage WebDAV + CSV | L00 |
| L02 | `v0.3.0` | Socle API + authentification | L01 |
| L03 | `v0.4.0` | Design system & coquille applicative | L02 |
| **Jalon II — Domaines de saisie** | | | |
| L04 | `v0.5.0` | Corps : poids & mensurations *(tranche verticale de référence)* | L03 |
| L05 | `v0.6.0` | Activité sportive & exercices | L04 |
| L06 | `v0.7.0` | Hydratation & suppléments | L04 |
| L07 | `v0.8.0` | Nutrition & fichiers binaires | L04 |
| L08 | `v0.9.0` | Réglages & agrégats du tableau de bord | L05, L06, L07 |
| **Jalon III — Assiduité** | | | |
| L09 | `v0.10.0` | Moteur `HEAT` — modèle, config, pistes | L08 |
| L10 | `v0.11.0` | Moteur `HEAT` — calcul, cadences, statistiques | L09 |
| L11 | `v0.12.0` | Heatmaps & réglage des pistes (UI) | L10 |
| **Jalon IV — Intelligence** | | | |
| L12 | `v0.13.0` | Couche IA OpenRouter + analyse de repas + import Apple | L07 |
| L13 | `v0.14.0` | Planning sport & export iCal | L12 |
| L14 | `v0.15.0` | Objectifs IA & bilan hebdomadaire | L12, L13 |
| **Jalon V — Production** | | | |
| L15 | `v0.16.0` | PWA & notifications push | L11 |
| L16 | `v0.17.0` | Export, hors-ligne, recherche, corrélations | L11 |
| L17 | `v1.0.0` | Durcissement, déploiement, documentation | tous |

Ordre motivé : le socle d'abord parce que tout en dépend ; **le Corps en premier
domaine** parce que c'est le plus simple et qu'il valide la chaîne complète
CSV → API → Query → écran ; les heatmaps après les domaines de saisie parce qu'une
piste sans données sources est une grille vide ; l'IA après, parce que `IA-07` en fait
un confort et jamais un prérequis.

---

# Jalon I — Socle

## L00 · `v0.1.0` — Fondations, outillage, tokens UI

**Objectif** : un dépôt qui démarre, se teste et sait déjà parler la langue visuelle
de Metric.

- [x] `L00-01` `git init`, `main`, `.gitignore`, `.editorconfig`, `README`, réglages VS Code
- [x] `L00-02` Backend : squelette `venv` + `pip`, FastAPI qui démarre, `ruff` + `mypy --strict` + `pytest` configurés
- [x] `L00-03` Frontend : Vite + React 19 + TS strict, ESLint + Prettier, Vitest
- [x] `L00-04` Proxy Vite `/api` → uvicorn, `make dev` lance les deux et les arrête ensemble
- [x] `L00-05` `.env.example` complet et documenté (`API-02`) : URL Nextcloud, identifiants, secret JWT, CORS, clé OpenRouter, clé iCal
- [x] `L00-06` **Extraction des tokens** de `GuidelinesUI.html` → `styles/tokens.css` : couleurs, 2 polices, rayons, échelle typo. Polices téléchargées et versionnées en local (`npm run fonts`), plus aucun CDN Google
- [x] `L00-07` `base.css` : reset, fond, typographie, primitives de mise en page, règle graduée, `prefers-reduced-motion`, `.num` tabular-nums
- [x] `L00-08` Page `/_kitchen-sink` : référence visuelle des **tokens** (couleurs, typo, niveaux d'intensité, espacement). Devient la galerie des composants au `L03-11`, une fois `components/ui/` écrit
- [x] `L00-09` `docker-compose.yml` de développement — **écrit mais non exécuté** : Docker n'est pas installé sur la machine. Le chemin de travail est `make dev` ; la pile conteneurisée est validée au `L17-01`
- [x] `L00-10` GitHub Actions : formatage + lint + types + tests des deux côtés, plus build de production

**DoD** — `make check` vert des deux côtés (5 tests backend, 5 tests frontend, `mypy
--strict` et ESLint sans avertissement) ; les deux serveurs démarrent et `/api/health`
répond **à travers le proxy Vite** ; les polices sont servies localement ; le build de
production passe (77 kB gzip). `docker compose up` reste à vérifier au L17.

**Écarts d'environnement constatés et absorbés** (le cadre du §0 a été corrigé en
conséquence) :

| Attendu | Constaté | Décision |
|---|---|---|
| Python 3.12 + `uv` | Python 3.14.6, `uv` absent | `venv` + `pip`, `pyproject.toml` conservé — bascule vers `uv` triviale |
| `httpx` | starlette 1.x déprécie `httpx` dans son `TestClient` | Tout le projet passe à **`httpx2`**, y compris le futur client WebDAV (`L01-01`) |
| TypeScript 7 disponible | `typescript-eslint` exige `<6.1.0` | **TypeScript 6.0** — le lint prime sur la dernière majeure |
| Docker | absent de la machine | `docker-compose.yml` livré non exécuté, validation reportée au `L17-01` |
| Port 5173 libre | occupé par un autre processus Node | Vite bascule seul de port ; `dev.sh` n'affiche plus d'URL frontend codée en dur |

---

## L01 · `v0.2.0` — Couche stockage WebDAV + CSV

**Objectif** : lire et écrire des CSV sur Nextcloud de façon sûre. C'est la pièce la
plus risquée du projet : tout le reste s'appuie dessus.

- [x] `L01-01` Client WebDAV : GET / PUT / DELETE / MKCOL / PROPFIND, pool keep-alive borné, identifiants côté serveur uniquement (`STO-01`)
- [x] `L01-02` Retry sur erreur transitoire, `429` et verrou `423`, `Retry-After` honoré (secondes ou date HTTP), backoff exponentiel plafonné avec gigue (`STO-08`)
- [x] `L01-03` Erreurs de stockage traduites en `502`/`503`/`409`/`404` + message français + code machine ; le détail technique reste dans les journaux (`STO-09`, `API-07`)
- [x] `L01-04` `CsvRepository` génériqué (PEP 695) : en-tête explicite, un fichier par domaine, lecture typée par modèle Pydantic, ligne fautive signalée par numéro et colonne (`STO-02`)
- [x] `L01-05` Ajout en fin de fichier, sans jamais réécrire une ligne existante — voir la note sur le mécanisme ci-dessous (`STO-03`)
- [x] `L01-06` Migration automatique d'en-tête : remappage par nom, colonne nouvelle → défaut du modèle, **colonne inconnue de l'app préservée** (`STO-04`)
- [x] `L01-07` Garde anti-conflit : valeurs attendues de la ligne visée, `409` si divergence, message disant ce qui a été trouvé (`STO-05`)
- [x] `L01-08` Écriture sous `If-Match` sur l'ETag du fichier — voir la note ci-dessous
- [x] `L01-09` Cache mémoire par fichier, TTL 30 s, invalidation à l'écriture **et revalidation conditionnelle par ETag** au-delà du TTL (`STO-06`, **D8**)
- [x] `L01-10` Fichiers binaires : arborescence datée, création des parents une seule fois, hors du cache CSV (`STO-07`)
- [x] `L01-11` Script `check_storage.py` : écrit, relit, vérifie la revalidation conditionnelle, nettoie (`STO-11`)
- [x] `L01-12` Faux serveur WebDAV ASGI en mémoire + 79 tests : conflit, écriture interrompue, en-tête migré, `429`, `423`, coupure réseau, serveur sans ETag

**DoD** — `make check` vert (79 tests backend, `mypy --strict`, ruff) ; couverture de la
couche stockage à **95 %** ; une écriture interrompue laisse le fichier précédent intact ;
deux écritures concurrentes sur la même ligne produisent un `409` et non un écrasement ;
`check_storage.py` diagnostique une configuration absente, de mauvais identifiants et un
serveur sans ETag sans jamais lever de traceback. **Reste à faire : exécuter
`make check-storage` contre le vrai Nextcloud** — non vérifiable sans identifiants.

**Deux écarts assumés par rapport au libellé des tâches :**

| Prévu | Livré | Pourquoi |
|---|---|---|
| `L01-05` « écriture en ajout, sans réécriture du fichier » | `PUT` complet du fichier, en n'ajoutant qu'en fin | WebDAV n'a pas de verbe d'ajout et l'extension de mise à jour partielle de Sabre n'est pas active sur une Nextcloud standard. L'**invariant** est tenu (aucune ligne existante réécrite) et la propriété recherchée aussi : le `PUT` de Sabre écrit dans un temporaire puis renomme, donc une interruption laisse la version précédente intacte |
| `L01-08` « temporaire + `MOVE` atomique » | `PUT` unique sous `If-Match` | Le temporaire + `MOVE` coûte deux requêtes et **perd la garde `If-Match`**, donc protège moins bien contre le vrai risque de `STO-05` — l'écriture concurrente depuis un autre appareil. L'atomicité côté serveur est déjà assurée par Sabre |

Deux comportements ont par ailleurs été ajoutés au-delà de la spec, parce que leur
absence aurait été un défaut : un ajout concurrent est **rejoué automatiquement** (les
ajouts commutent, un `409` obligerait à ressaisir), et une colonne ajoutée à la main dans
un tableur **survit** à une écriture de l'app.

> **Décision technique** : `STO-03` (append) et l'édition de lignes (`BODY-02`, `ACT-04`,
> config des pistes) sont inconciliables tels quels. Règle retenue : **append pour toute
> création**, réécriture atomique sous garde `409` pour modification/suppression. Le
> versioning Nextcloud (`STO-10`) reste le filet de sécurité.
>
> **Point non trivial** : Nextcloud peut être écrit par ailleurs (autre appareil,
> édition tableur). Le cache ne peut donc pas être invalidé seulement par *nos* propres
> écritures — d'où la vérification d'ETag de `L01-09`, qui conditionne la validité de
> `HEAT-33`.

---

## L02 · `v0.3.0` — Socle API + authentification

**Objectif** : une API structurée, protégée, documentée.

- [x] `L02-01` Découpage en routeurs par domaine, préfixe `/api`, 12 squelettes prêts à recevoir leurs routes (`API-01`)
- [x] `L02-02` Configuration typée Pydantic Settings + **refus de démarrer** en production avec une configuration dangereuse (`API-02`)
- [x] `L02-03` CORS configurable par environnement (`API-03`)
- [x] `L02-04` `GET /api/health` public, annonçant stockage / auth / IA configurés (`API-04`)
- [x] `L02-05` OpenAPI + interface d'essai, schéma de session déclaré (`API-05`)
- [x] `L02-06` Socle de validation : 18 types bornés réutilisables — poids 0–500 kg, réps 1–200, FC 1–260, volume 0–5000 ml, date jamais future **en heure locale** (`API-06`)
- [x] `L02-07` Catalogue d'erreurs typées en un seul module + 4 gestionnaires globaux (métier, validation, `HTTPException`, filet de sécurité) (`API-07`)
- [x] `L02-08` Connexion mono-utilisateur contre la config serveur (`AUTH-01`)
- [x] `L02-09` Vérification Argon2id, comparaison d'identifiant en temps constant (`AUTH-02`)
- [x] `L02-10` Émission JWT signé, 7 jours par défaut, `Authorization: Bearer` (`AUTH-03`)
- [x] `L02-11` Anti-brute-force : 5 échecs / 60 s / IP → `429` avec délai annoncé en corps **et** en en-tête ; **hachage exécuté même si l'identifiant est faux** ; quota consulté **avant** de hacher (`AUTH-04`)
- [x] `L02-12` Dépendance d'authentification portée par le **groupe** de routeurs de données ; seules santé, doc et connexion sont publiques (`AUTH-05`, `AUTH-06`, `AUTH-07`)
- [x] `L02-13` `make hash-password`, saisie sans écho, jamais de mot de passe en clair sur disque ni en argument (`AUTH-08`)
- [x] `L02-14` 55 tests : `401` sans jeton, jeton expiré / falsifié / non signé / sans échéance, quota, catalogue, bornes, durcissement

**DoD** — `make check` vert (134 tests backend, couverture **96 %**, `mypy --strict`,
ruff) ; parcours complet vérifié en **HTTP réel** hors harnais de test : connexion,
route protégée, jeton altéré, six échecs consécutifs, blocage du bon mot de passe pendant
la pénalité, déconnexion. Une route de données ajoutée par un lot ultérieur est protégée
par construction, et un test structurel le vérifie automatiquement.

**Deux choix qui vont au-delà du libellé :**

| Sujet | Décision |
|---|---|
| Protection des routes | Portée sur le **groupe** de routeurs, pas route par route. Un endpoint ajouté au lot L07 est protégé parce qu'il est dans le groupe, pas parce que son auteur y a pensé — l'oubli devient structurellement impossible, et `test_every_data_route_requires_a_token` le vérifie à chaque exécution |
| Configuration de production | `APP_ENV=production` avec un secret de développement, un hash absent ou un stockage non renseigné **empêche le démarrage**. Échouer au déploiement plutôt qu'à la première requête : c'est le seul moment où l'on regarde les journaux |

**Limite assumée** : le jeton étant autoporteur, la déconnexion (`AUTH-07`) est
client-side — un jeton volé reste valide jusqu'à son échéance. Une liste de révocation
supposerait un état serveur, donc une écriture Nextcloud par déconnexion, disproportionné
pour une application mono-utilisateur.

---

## L03 · `v0.4.0` — Design system & coquille applicative

**Objectif** : la bibliothèque de composants des guidelines, et une app authentifiée
qui navigue.

- [x] `L03-01` Primitives : `Button` (primary / ghost / quiet / log / busy / disabled), `Card`, `Badge` (4 signaux), `Field` avec erreur par champ, `Rule`, `Eyebrow`, `Segmented`, `Empty`, `AiBlock`
- [x] `L03-02` Composants de données : `Stat` (+ `Sparkline`), `Bars`, `Progress`, `Ring`, `Table` générique, `Check` / `CheckGroup`
- [x] `L03-03` `Heatmap` : grille 7 × N, **six états** (`off`, `missed`, `done` 1–4, `bonus`, neutralisé, hors plage), statuts hebdomadaires, en-tête de mois, légende, infobulle. **Aucune règle d'état côté client** (`HEAT-30`)
- [x] `L03-04` `Chart` : axe gradué, grille de fond, aire dégradée, série de contexte en pointillé, bande inférieure à seuil d'alerte, curseur + infobulle suiveuse
- [x] `L03-05` Client API : `fetch` typé, injection du jeton, décodage de `{code, message, fields}` en exception typée, distinction panne réseau / refus métier
- [x] `L03-06` `401` → purge du jeton + notification, une seule fois et au même endroit (`AUTH-06`) ; déconnexion manuelle (`AUTH-07`)
- [x] `L03-07` `QueryClient` : clés nommées par domaine, réessai **uniquement** sur panne passagère, jamais sur refus métier ni sur mutation
- [x] `L03-08` Écran de connexion, routes protégées, jeton **revalidé auprès du serveur** au démarrage
- [x] `L03-09` Coquille : en-tête collant, navigation, déconnexion, zone de notifications discrètes
- [x] `L03-10` Utilitaires de format : dates FR, `mm:ss` / `h:mm:ss`, allure, volumes, virgule décimale, signe moins typographique
- [x] `L03-11` Kitchen sink promu en galerie complète des 18 composants + 37 tests frontend

**DoD** — `make check` vert (37 tests frontend, ESLint, `tsc` strict, Prettier) ; build de
production à 98 kB gzip ; **connexion et galerie vérifiées par capture** dans un vrai
navigateur. Session revalidée au démarrage plutôt que crue sur parole ; expiration gérée
sans écran blanc.

**Décisions prises en construisant :**

| Sujet | Décision |
|---|---|
| Galerie de charte publique | `/_kitchen-sink` est hors authentification : la page ne contient aucune donnée utilisateur, et pouvoir l'ouvrir sans session la rend consultable depuis n'importe quel appareil — et vérifiable par une capture automatisée |
| Persistance du jeton | `localStorage` avec **repli en mémoire** détecté à l'exécution. Navigation privée Safari, cookies bloqués, environnement de test : avaler l'erreur ferait perdre la session sans rien annoncer |
| Échelles multiples du graphique | La charte superpose deux unités. Conservé, avec trois garde-fous : un seul axe gradué, la série de contexte en pointillé, et les chiffres exacts à l'infobulle. La lecture précise passe par le curseur, jamais par la géométrie |
| Props optionnelles | Déclarées `?: T \| undefined` dans toute la bibliothèque : `exactOptionalPropertyTypes` refuse de passer une valeur potentiellement absente à une prop simplement optionnelle |

---

# Jalon II — Domaines de saisie

## L04 · `v0.5.0` — Corps : poids & mensurations

**Objectif** : première tranche verticale complète. Elle fixe le patron que les
domaines suivants recopieront.

- [x] `L04-01` `body/weight.csv` + `body/measurements.csv` : modèles, dépôts typés, chemins déclarés
- [x] `L04-02` Enregistrer une pesée : poids borné, date non future **en heure locale**, note (`BODY-01`)
- [x] `L04-03` Modifier / supprimer sous garde `409` par **jeton de ligne en `If-Match`** (`BODY-02`, `STO-05`)
- [x] `L04-04` Indicateurs : dernier poids, variation sur 8 pesées, écart à l'objectif lu dans les réglages (`BODY-03`)
- [x] `L04-05` Série chronologique même si le fichier est écrit dans le désordre, + min / max / amplitude (`BODY-04`)
- [x] `L04-06` Tendance lissée 7 jours, **fenêtre calendaire** et non un nombre de points (`BODY-05`)
- [x] `L04-07` Historique paginé, du plus récent au plus ancien, chaque entrée identifiable (`BODY-06`)
- [x] `L04-08` Mensurations : 6 mesures optionnelles, au moins une requise, masse grasse comprise (`BODY-07`, `BODY-10`)
- [x] `L04-09` Indicateurs de mensurations : **chaque mesure a son propre historique** (`BODY-08`)
- [x] `L04-10` Historique et édition des mensurations (`BODY-09`)
- [x] `L04-11` UI : écran Corps — 4 chiffres clés, courbe poids + tendance superposée, saisie, historique éditable, panneau mensurations
- [x] `L04-12` 32 tests backend + 12 tests d'écran : saisir → corriger → supprimer, jeton compris

**DoD** — `make check` vert (169 tests backend, 49 frontend) ; le CSV produit est lisible
dans un tableur, BOM compris ; le patron est écrit dans
[`docs/patron-domaine.md`](docs/patron-domaine.md). **Stockage vérifié contre le vrai
Nextcloud** : écriture, relecture identique et `304` honoré — le cache et la garde
anti-conflit tiennent sur l'instance réelle.

**Deux ajouts au socle, faits ici parce que les cinq domaines suivants en dépendent :**

| Ajout | Pourquoi |
|---|---|
| **Jeton de ligne** (`Row.token`, `replace_by_token`, `delete_by_token`) | `STO-05` demande d'annoncer les valeurs attendues. Un dictionnaire ne se transporte pas sur un `DELETE`, qui n'a pas de corps naturel. L'empreinte de contenu en `If-Match` dit la même chose en HTTP idiomatique |
| **Lecteur de réglages** (`app/domains/app_settings/`) | `BODY-03` a besoin du poids cible. Le coder en dur aurait créé une constante à déloger au L08 |

---

## L05 · `v0.6.0` — Activité sportive & exercices

**Objectif** : le plus gros domaine, et la source de 6 des 9 pistes d'assiduité.

- [x] `L05-01` Quatre fichiers d'activité : modèles, dépôts typés, chemins déclarés
- [x] `L05-02` Course : formats souples normalisés — `44:12`, `1:18:44`, `44`, `44,5`, `1h30`, `5mi` (`ACT-01`)
- [x] `L05-03` Allure min/km dérivée **et stockée**, vitesse km/h dans le détail (`ACT-02`)
- [x] `L05-04` Séance à **identifiant stable**, survivant aux corrections, 7 types suggérés sans contrainte (`ACT-03`)
- [x] `L05-05` Correction et suppression sous garde ; supprimer une séance **purge ses exercices** (`ACT-04`)
- [x] `L05-06` Détail d'une course comme ressource unitaire (`ACT-05`)
- [x] `L05-07` Catalogue, 9 groupes musculaires, **retrait sans perte d'historique** (`ACT-06`)
- [x] `L05-08` Journal charge × séries × réps, charge 0 = poids du corps (`ACT-07`)
- [x] `L05-09` Rappel de la dernière performance à la sélection (`ACT-08`)
- [x] `L05-10` Progression : dernière charge, écart, série des maxima par séance (`ACT-09`)
- [x] `L05-11` Volume par jour avec **repos distingué de zéro**, totaux de semaine ISO (`ACT-10`, `ACT-11`)
- [x] `L05-12` Huit semaines d'historique + historique fusionné courses / séances (`ACT-12`, `ACT-13`)
- [x] `L05-13` Tonnage par groupe musculaire et par semaine (`ACT-14`)
- [x] `L05-14` Records et 1RM estimé par Epley (`ACT-15`)
- [x] `L05-15` Groupes négligés — **« jamais » n'est pas un grand nombre** (`ACT-16`)
- [x] `L05-16` Duplication d'une séance, exercices compris, sans hériter du RPE (`ACT-17`)
- [x] `L05-17` Effort perçu 1–10 par séance (`ACT-18`)
- [x] `L05-18` UI : écran Activité — semaine, volume par jour, tonnage, groupes négligés, progression, historique, saisie course et séance, journal d'exercices, catalogue
- [x] `L05-19` 72 tests backend + 12 tests d'écran : formats, Epley, semaines ISO, purge en cascade

**DoD** — `make check` vert (241 tests backend, 61 frontend) ; les quatre fichiers CSV
sont conformes à l'annexe et lisibles en tableur ; une séance de musculation complète se
saisit sans quitter l'écran ; les agrégats basculent bien le lundi ; un record est détecté
à l'écriture.

**Trois décisions de modélisation :**

| Sujet | Décision |
|---|---|
| Dénormalisation du journal | `exercise_log.csv` duplique le nom et le groupe musculaire alors qu'il porte déjà `exercise_id`. Ce n'est pas un oubli : `ACT-06` exige que retirer un exercice conserve l'historique, et le fichier doit rester compréhensible seul dans un tableur (`STO-02`) |
| Analyse des formats dans le socle | `app/core/parsing.py` et non dans le domaine : l'import Apple (`IMP-03`) doit normaliser exactement les mêmes formats, et deux analyseurs finiraient par diverger |
| Ordre de la suppression en cascade | La séance part **en premier**, sous garde ; purger d'abord laisserait des exercices orphelins si la garde refusait la suppression |

---

## L06 · `v0.7.0` — Hydratation & suppléments

**Objectif** : les deux domaines de saisie « en un geste », et les sources restantes
des pistes d'assiduité.

- [x] `L06-01` `hydration/intake_log.csv` : horodatage **avec décalage**, volume, type facultatif (`HYD-01`)
- [x] `L06-02` Raccourcis de volume lus dans les réglages, tolérants à une saisie bancale (`HYD-02`)
- [x] `L06-03` Total du jour vs objectif réglable, ratio plafonné mais volume réel intact (`HYD-03`)
- [x] `L06-04` Correction et suppression d'une prise du jour, sous garde (`HYD-04`)
- [x] `L06-05` Série **complète** sur 30 jours, moyennes 7 et 30 j, jours ayant atteint l'objectif (`HYD-05`)
- [x] `L06-06` `supplements/schedule.csv` avec **`frequency` renseignée** et **`created`** — prérequis de `HEAT-23` et `HEAT-07`
- [x] `L06-07` Planning : nom, dose, unité, moment, tri par horaire (`SUP-01`)
- [x] `L06-08` Retrait sans perte d'historique (`SUP-02`)
- [x] `L06-09` Checklist du jour, état vierge chaque matin, prise horodatée à la coche (`SUP-03`)
- [x] `L06-10` Bascule optimiste **restaurée** en cas d'échec serveur (`SUP-04`)
- [x] `L06-11` Décocher supprime la prise du jour, et elle seule (`SUP-05`)
- [x] `L06-12` Ratio du jour et booléen « journée complète » (`SUP-06`)
- [x] `L06-13` UI : écran Routine — anneau d'hydratation, raccourcis en un geste, checklist groupée par moment avec série par item, planning avec cadence
- [x] `L06-14` 70 tests backend + 11 tests d'écran : frontière de jour à 23 h 30, bascule annulée, grammaire des cadences

**DoD** — `make check` vert (311 tests backend, 72 frontend) ; une prise à 23 h 30
appartient au jour affiché par l'horloge, et une prise à 0 h 30 au jour qui commence ;
cocher un supplément est instantané à l'écran et cohérent après rechargement.

**Deux pièces ajoutées au socle, parce que le moteur d'assiduité en dépendra :**

| Ajout | Pourquoi |
|---|---|
| **`app/core/dates.py`** | Le jour local et la semaine ISO n'ont plus qu'une implémentation. `week_start` vivait dans le domaine Activité ; deux endroits qui découpent le temps finissent par donner deux totaux pour la même journée |
| **`app/core/cadence.py`** | La décision **D3** lie `schedule.frequency` au journal d'historisation. Une seule grammaire, validée à la saisie et **normalisée** — sinon deux écritures équivalentes enregistreraient un changement de cadence qui n'en est pas un. Ce module ne décide pas encore si un jour est validé : c'est le lot L10 |

---

## L07 · `v0.8.0` — Nutrition & fichiers binaires

**Objectif** : les repas, avec photo, sans IA pour l'instant (elle arrive au L12).

- [x] `L07-01` `nutrition/meals.csv`, `favorites.csv` : modèles et dépôts typés
- [x] `L07-02` Photo **et/ou** description, au moins l'un des deux, espaces ne comptant pas (`NUT-01`)
- [x] `L07-03` Rangement `nutrition/photos/AAAA/MM/JJ/`, nom horodaté + aléa contre les collisions (`NUT-02`)
- [x] `L07-04` Type présélectionné selon l'heure, **calculé par le serveur** (`NUT-03`)
- [x] `L07-05` Macros saisissables et corrigeables à la main, sans IA (`NUT-05`)
- [x] `L07-06` Totaux du jour : protéines vs objectif, sucres vs plafond, calories **nuancées** par le nombre de repas renseignés (`NUT-06`)
- [x] `L07-07` Liste du jour, bornée ou complète (`NUT-07`)
- [x] `L07-08` Service authentifié des photos, forme de chemin imposée, réponses cachables et non reniflables (`NUT-08`)
- [x] `L07-09` Correction préservant photo et provenance d'origine (`NUT-09`)
- [x] `L07-10` Repas favoris rejouables en une action (`NUT-10`)
- [x] `L07-11` UI : écran Nutrition — anneau de protéines, journal avec vignettes, saisie photo, favoris
- [x] `L07-12` 35 tests de sécurité : huit tentatives d'évasion, six chemins mal formés, quatre contenus non-images

**DoD** — `make check` vert (381 tests backend, 86 frontend) ; un repas photo s'enregistre
depuis un téléphone ; **aucune requête ne sort du dossier photos** ; les macros sont
modifiables sans IA (`IA-07` par construction).

**Trois décisions sur la surface d'attaque :**

| Sujet | Décision |
|---|---|
| Validation du chemin | La stratégie n'est **pas** de nettoyer ce qu'on reçoit mais de refuser tout ce qui ne correspond pas exactement à la forme que nous produisons. Une expression régulière stricte, puis une vérification de confinement en ceinture |
| Type de fichier | Déduit de la **signature du contenu**, jamais du nom ni du `Content-Type` déclaré. Servir des octets arbitraires sous un type d'image offrirait une surface au navigateur |
| Message d'erreur | Un chemin mal formé et un chemin absent rendent le **même** 404. Les distinguer renseignerait sur l'arborescence |

**Une décision assumée** : supprimer un repas ne supprime pas sa photo. Elle est rangée
par date et consultable hors de l'app ; l'effacer d'un clic dans une liste ferait perdre
un souvenir qu'aucune annulation ne rendrait. La suppression du fichier reste manuelle.

---

## L08 · `v0.9.0` — Réglages & agrégats du tableau de bord

**Objectif** : les réglages partagés, et l'écran d'accueil en un seul appel.

- [ ] `L08-01` `settings/settings.csv` clé/valeur (**D2** : tout sous `settings/`), lecture typée, **valeurs de repli identiques backend et frontend** (annexe du backlog)
- [ ] `L08-02` Réglages exposés : poids cible, protéines cible, plafond sucres, objectif d'hydratation, raccourcis, métrique mise en avant
- [ ] `L08-03` `GET /api/aggregates/dashboard` : tous les indicateurs de synthèse en une requête (`AGG-01`)
- [ ] `L08-04` Totaux d'entraînement : total, semaine courante, 8 semaines, répartition courses / muscu (`AGG-02`)
- [ ] `L08-05` Série d'assiduité toutes sources + état des 7 derniers jours, hier reste valide tant que le jour en cours n'est pas fini (`AGG-03`)
- [ ] `L08-06` Séries temporelles génériques : contrat unique, plages 1 mois / 3 mois / tout, stats dernier / variation / moyenne / min / max (`AGG-04`)
- [ ] `L08-07` UI : tableau de bord — rangée de stat cards, sélecteur de période, graphique croisé, état vide « aucun relevé aujourd'hui »
- [ ] `L08-08` UI : écran Réglages (section généraliste, les pistes viendront au L11)
- [ ] `L08-09` Tests : un seul appel réseau au chargement du tableau de bord ; streak sur données trouées

**DoD** — le tableau de bord se charge en une requête ; `AGG-04` sert déjà au moins
trois métriques différentes sans code spécifique.

> `AGG-03` (« au moins une donnée, toutes sources ») et `HEAT-27` (série
> cadence-consciente par piste) sont **deux algorithmes distincts** et le resteront.
> Le premier mesure l'assiduité de suivi, le second le respect d'un engagement.

---

# Jalon III — Assiduité

> **Numérotation** : `HEAT-01` à `HEAT-33` désignent ici exclusivement la v2
> (`heat_backlog.md`). Les `HEAT-01` à `HEAT-08` de `backlogV2.md` §12 sont **abandonnés
> en tant qu'identifiants** ; leur contenu est absorbé : ancien `-02` → source
> `activity.duration`, `-03` → `hydration.intake`, `-04` → voir décision **D5**,
> `-05` → `entry_count`, `-06` → `HEAT-29`, `-07` → `HEAT-26`, `-08` → `HEAT-22`.
> Les renvois de `SUP-06` (« heatmap `HEAT-03` ») et `HYD-01` pointent vers l'ancienne
> numérotation : à corriger dans le backlog.

## L09 · `v0.10.0` — Moteur `HEAT` : modèle, config, pistes

**Objectif** : le modèle de piste et son cycle de vie. Aucun calcul d'état encore, mais
tout ce qui le paramètre.

- [ ] `L09-01` Modèle `Track` : id, libellé, source, filtre, seuil de validation, seuils d'intensité, binaire, accent, position, actif, date de création (`HEAT-01`)
- [ ] `L09-02` `settings/heatmap_tracks.csv` + `heatmap_cadences.csv` + `heatmap_off_days.csv`, sérialisation `params` lisible en tableur `min_count=1;window_days=2` (`STO-02`)
- [ ] `L09-03` Registre de sources extensible : `activity.muscle_group`, `activity.runs`, `activity.duration`, `supplement.intake`, `hydration.intake`, `entry_count` — une interface, six implémentations (`HEAT-02`)
- [ ] `L09-04` Contrat d'agrégat quotidien : chaque source rend **un nombre par jour**, rien d'autre (`HEAT-03`)
- [ ] `L09-05` Historique de cadences versionné avec `valid_from`, résolution de la cadence applicable à une date (`HEAT-14`)
- [ ] `L09-06` Plages neutralisées, `track_id` vide = toutes les pistes (`HEAT-06`)
- [ ] `L09-07` `GET/POST/PATCH/DELETE /api/heatmap/tracks` — création, modification versionnée, suppression sous garde `409` (`HEAT-18`, `HEAT-19`, `HEAT-21`)
- [ ] `L09-08` Modification des seuils et libellés, **avec recalcul complet de l'historique** et avertissement explicite dans la réponse (`HEAT-20`)
- [ ] `L09-09` Désactivation vs suppression : la désactivation conserve l'historique, la suppression n'efface jamais les données sources (`HEAT-21`)
- [ ] `L09-10` Ordre et piste mise en avant comme réglages (`HEAT-22`)
- [ ] `L09-11` `POST/DELETE /api/heatmap/off-days` (`HEAT-06`)
- [ ] `L09-12` Amorçage des 9 pistes par défaut, mapping groupe musculaire → piste **en configuration** et non en constante ; `autre` délibérément non mappé (**D7**) (`heat_backlog` §5)
- [ ] `L09-13` Amorçage des seuils (**D9**, **D10**) : `per_week` calculé sur la fréquence réelle des 4 dernières semaines et non figé à 2 ; validation de la piste `eau` à **1500 ml**, gradient d'intensité inchangé jusqu'à 2000 ml
- [ ] `L09-14` Cadence `supplement.intake` (**D3**) : `schedule.frequency` = valeur courante éditable, `settings/heatmap_cadences.csv` = journal append-only alimenté à chaque changement ; le moteur lit le journal pour juger le passé (`HEAT-23`, `HEAT-14`)
- [ ] `L09-15` Suppléments gradués non amorcés mais supportés (**D11**) : mode binaire par défaut, deux seuils suffisent à passer en gradué (`HEAT-15`, `HEAT-16`)
- [ ] `L09-16` Tests : cadence résolue à une date passée, création de piste non rétroactive (`HEAT-07`), suppression sans perte de source

**DoD** — les 9 pistes par défaut existent à l'initialisation, toutes modifiables ;
ajouter une piste ne demande aucune ligne de code ; ajouter une *source* est le seul
cas qui en demande.

---

## L10 · `v0.11.0` — Moteur `HEAT` : calcul, cadences, statistiques

**Objectif** : le cœur du projet. C'est le lot où la justesse compte le plus.

- [ ] `L10-01` Règle de validation `agrégat ≥ seuil`, seuil toujours paramètre de piste (`HEAT-04`)
- [ ] `L10-02` Machine à états du jour : `off` / `missed` / `done` / `bonus` (`HEAT-05`)
- [ ] `L10-03` Priorité des règles neutralisantes : neutralisé (`HEAT-06`) > antérieur à la création (`HEAT-07`) > jour en cours (`HEAT-08`) > cadence
- [ ] `L10-04` Cadence `daily` (`HEAT-09`)
- [ ] `L10-05` Cadence `window` : fenêtre **glissante** `min_count` / `window_days`, `missed` si la fenêtre qui se referme sur le jour contient moins de `min_count` validations (`HEAT-10`)
- [ ] `L10-06` Cadence `per_week` : unité = semaine ISO lundi→dimanche, **aucun `missed` au jour**, statut porté par la semaine (`HEAT-11`)
- [ ] `L10-07` Cadence `conditional` : attendu si un déclencheur est vrai — séance existante, séance d'un groupe donné (`HEAT-12`)
- [ ] `L10-08` Cadence `none` : purement descriptive (`HEAT-13`)
- [ ] `L10-09` Seuils d'intensité par piste → niveau 1–4 (`HEAT-15`) et mode binaire (`HEAT-16`)
- [ ] `L10-10` **Découplage validation / intensité** : un jour peut être validé et pâle (`HEAT-17`)
- [ ] `L10-11` Grille complète : aucun jour omis, `date → { valeur, état, niveau }` (`HEAT-24`)
- [ ] `L10-12` Statistiques : jours validés, jours attendus, taux de respect, plus longue série, série en cours, meilleur jour, total cumulé (`HEAT-26`)
- [ ] `L10-13` Série cadence-consciente : `off` et neutralisés **transparents**, ils n'incrémentent ni ne cassent (`HEAT-27`)
- [ ] `L10-14` Statuts hebdomadaires atteint / partiel / manqué, réalisé sur attendu (`HEAT-28`)
- [ ] `L10-15` Détail d'un jour par source : exercices et séries, distance et allure, prises horodatées, volumes (`HEAT-29`)
- [ ] `L10-16` Découpage en jours en fuseau local Europe/Paris, jamais UTC (`HEAT-32`)
- [ ] `L10-17` Plage par défaut (**D6**) : `from` = lundi de la semaine d'il y a 52 semaines, `to` = dimanche de la semaine courante → 53 colonnes pleines ; les jours futurs de la semaine en cours sont rendus `off` (`HEAT-31`)
- [ ] `L10-18` **Batterie de tests de règles** : la fenêtre glissante sur rythme L/M/V vs M/J/S (les deux corrects), grippe de 5 jours au milieu d'une série de 90, changement de cadence à mi-historique, piste créée hier, whey un jour sur deux pendant 3 mois → série de 3 mois
- [ ] `L10-19` Tests de propriété : aucune grille ne contient de trou ; aucun jour `missed` sur une piste `per_week` ou `none`

**DoD** — chaque exemple cité en clair dans `heat_backlog.md` est un test qui passe ;
tout calcul est serveur (`HEAT-30`) ; couverture de la machine à états ≥ 95 %.

---

## L11 · `v0.12.0` — Heatmaps & réglage des pistes (UI)

**Objectif** : neuf grilles à l'écran, en un appel, explorables.

- [ ] `L11-01` `GET /api/heatmap/{id}?from=&to=` : grille + stats + cadence, forme de réponse exactement conforme à `heat_backlog` §8 (`HEAT-24`)
- [ ] `L11-02` `GET /api/heatmap?tracks=a,b,c&from=&to=` : lecture multi-pistes en une requête (`HEAT-25`)
- [ ] `L11-03` `GET /api/heatmap/{id}/day/{date}` : détail explorable (`HEAT-29`)
- [ ] `L11-04` Cache serveur des grilles, clé = piste + plage + version de config + ETag des sources ; invalidation à toute écriture de source ou de config (`HEAT-33`)
- [ ] `L11-05` Test de performance : 9 pistes × 371 jours sans relire Nextcloud à chaque affichage
- [ ] `L11-06` UI : écran Assiduité — les 9 grilles, `off` visuellement distinct de `missed` (une grille majoritairement `off` **ne doit pas se lire comme un échec**)
- [ ] `L11-07` UI : rendu `per_week` — statut de semaine, pas de rouge au jour
- [ ] `L11-08` UI : tiroir de détail au clic sur une cellule
- [ ] `L11-09` UI : stat cards par piste — taux de respect, série en cours, record, total
- [ ] `L11-10` UI : réglages des pistes — créer, réordonner, mettre en avant, changer la cadence, éditer les seuils **avec avertissement de recalcul rétroactif** (`HEAT-19`, `HEAT-20`, `HEAT-22`)
- [ ] `L11-11` UI : neutraliser une plage (maladie, voyage, deload) et l'annuler
- [ ] `L11-12` Palette : accent par piste tiré des 4 signaux des guidelines, niveaux en opacité `l1`–`l4`

**DoD** — l'écran affiche 9 grilles en un appel réseau ; changer une cadence depuis
l'UI n'altère pas le passé ; changer un seuil le recalcule, et l'utilisateur en a été
averti avant de valider.

---

# Jalon IV — Intelligence

## L12 · `v0.13.0` — Couche IA + analyse de repas + import Apple

- [ ] `L12-01` Client OpenRouter unique, API compatible OpenAI, modèle préféré configurable (`IA-01`)
- [ ] `L12-02` Découverte des modèles gratuits : filtrage modération/embedding/TTS, classement, cache 1 h (`IA-02`)
- [ ] `L12-03` Cascade multi-modèles sur `429` ou réponse inexploitable ; échec total distinguant quota saturé et autre erreur (`IA-03`)
- [ ] `L12-04` Cascade restreinte aux modèles vision pour les appels sur image (`IA-04`)
- [ ] `L12-05` Extraction JSON robuste : nettoyage `<think>…`, premier objet valide par équilibrage d'accolades (`IA-05`)
- [ ] `L12-06` Préparation d'images : 1024 px max, JPEG, data URL (`IA-06`)
- [ ] `L12-07` Dégradation propre sans clé : message clair, app pleinement utilisable en manuel (`IA-07`)
- [ ] `L12-08` Analyse IA de l'assiette : protéines, sucres ajoutés, calories **proposés, jamais imposés** (`NUT-04`)
- [ ] `L12-09` Import Apple : analyse d'un screenshot, aucune écriture sans validation (`IMP-01`)
- [ ] `L12-10` Pré-remplissage intégralement modifiable (`IMP-02`)
- [ ] `L12-11` Conversions : miles → km, `28:45` → décimal, dates relatives → absolue non future ; **valeurs absentes laissées vides, jamais inventées** (`IMP-03`)
- [ ] `L12-12` Détection de doublon probable à la minute près (`IMP-04`)
- [ ] `L12-13` `source=apple|manual` dans le CSV (`IMP-05`)
- [ ] `L12-14` Capture illisible : message explicite, relance ou saisie manuelle (`IMP-06`)
- [ ] `L12-15` UI : bloc IA des guidelines (section 10), valeurs proposées visuellement distinctes des valeurs saisies, action « Pas d'accord »
- [ ] `L12-16` Tests avec réponses de modèle simulées : JSON bavard, JSON tronqué, `429` en cascade, aucune clé configurée

**DoD** — sans clé API, aucune fonctionnalité n'est bloquée ; avec clé, un
screenshot Apple Fitness pré-remplit une course en une action, et rien n'est écrit
sans validation.

---

## L13 · `v0.14.0` — Planning sport & export iCal

- [ ] `L13-01` `planning/plan.csv`, repository, calendrier mensuel navigable, semaine au lundi (`PLAN-01`)
- [ ] `L13-02` Planifier / modifier / supprimer une séance : date, heure, type, titre suggéré, durée, note (`PLAN-02`)
- [ ] `L13-03` Génération IA : fréquence réelle des 4 dernières semaines + groupes travaillés (`ACT-16`) + objectif actif + contraintes libres → 1 ou 2 semaines, alternance des groupes, récupération, pas de doublon (`PLAN-03`)
- [ ] `L13-04` Aperçu avant écriture, retrait individuel, adoption en une fois marquée source IA (`PLAN-04`)
- [ ] `L13-05` Flux `.ics` protégé par clé secrète stable, abonnable Apple/Google, téléchargeable (`PLAN-05`)
- [ ] `L13-06` Écart plan / réalisé par semaine + taux de respect du planning (`PLAN-06`)
- [ ] `L13-07` UI : calendrier mensuel, prévu vs effectué, aperçu de proposition IA
- [ ] `L13-08` Tests : flux iCal valide dans un vrai client de calendrier, clé invalide → refus

**DoD** — le flux `.ics` s'abonne réellement dans Apple Calendar ; une proposition IA
n'écrit rien avant adoption explicite.

---

## L14 · `v0.15.0` — Objectifs IA & bilan hebdomadaire

- [ ] `L14-01` `goals/goals.csv`, `insights/weekly.csv`, repositories
- [ ] `L14-02` Génération d'objectif : unique, chiffré, daté 4–8 semaines, justifié par les données ; données maigres → repli sur objectif de régularité (`GOAL-01`)
- [ ] `L14-03` Résumé factuel envoyé au modèle, **jamais les fichiers entiers** (`GOAL-02`)
- [ ] `L14-04` Adopter / régénérer / abandonner, conservation avec date et statut (`GOAL-03`)
- [ ] `L14-05` Calcul de progression selon la métrique : poids, séances/sem, km/sem, protéines/j, hydratation/j (`GOAL-04`)
- [ ] `L14-06` Trois états exposés : aucune proposition, en attente, actif avec échéance (`GOAL-05`)
- [ ] `L14-07` Historique avec résultat final atteint / partiel / abandonné, réinjecté dans la génération suivante (`GOAL-06`)
- [ ] `L14-08` Bilan hebdomadaire : ce qui progresse, ce qui décroche, une action concrète ; à la demande, historisé (`IA-08`)
- [ ] `L14-09` UI : écran Objectif — anneau de progression, bloc IA, historique
- [ ] `L14-10` Tests : progression sur les 5 métriques, repli sans données, objectif expiré

**DoD** — un objectif se génère, s'adopte et affiche une progression réelle issue des
données ; le résumé envoyé au modèle est vérifiable et borné.

---

# Jalon V — Production

## L15 · `v0.16.0` — PWA & notifications push

- [ ] `L15-01` Manifeste PWA, icônes, installable sur iOS et Android
- [ ] `L15-02` Service worker : coquille applicative en cache, stratégies par type de ressource
- [ ] `L15-03` Clés VAPID serveur + flux d'abonnement Web Push (`NOT-01`)
- [ ] `L15-04` Ordonnanceur backend déclenchant les rappels app fermée (`NOT-02`)
- [ ] `L15-05` Configuration des rappels par type et horaire, stockée comme les autres réglages (`NOT-03`)
- [ ] `L15-06` Tests : rappel reçu app fermée, désabonnement, jeton expiré

**DoD** — Metric s'installe depuis Safari iOS et délivre un rappel de suppléments
application fermée. *(Dépend de HTTPS : à valider avec `L17-01`.)*

---

## L16 · `v0.17.0` — Export, hors-ligne, recherche, corrélations

- [ ] `L16-01` Export complet : archive de tous les CSV + photos en option, indépendante de Nextcloud (`DATA-01`)
- [ ] `L16-02` File d'attente hors-ligne côté client, rejeu à la reconnexion, résolution des `409` (`DATA-02`)
- [ ] `L16-03` Recherche et filtres d'historique côté serveur : plage, type, texte libre (`DATA-03`)
- [ ] `L16-04` Corrélations simples : deux séries sur une plage + coefficient, **présenté comme une lecture, sans prétention causale** (`DATA-04`, optionnel)
- [ ] `L16-05` UI : file d'attente visible, indicateur hors-ligne, écran d'export
- [ ] `L16-06` Tests : séance saisie en mode avion puis rejouée, conflit pendant le rejeu

**DoD** — une séance saisie sans réseau apparaît sur Nextcloud après reconnexion ;
l'archive d'export s'ouvre sans l'app.

---

## L17 · `v1.0.0` — Durcissement, déploiement, documentation

- [ ] `L17-01` Conteneurisation backend + frontend derrière reverse-proxy à certificat automatique (`OPS-01`)
- [ ] `L17-02` Documentation d'exploitation : installation, mise à jour, sauvegarde, restauration (`OPS-02`)
- [ ] `L17-03` Revue de sécurité : en-têtes, CSP, expiration JWT, limitation de débit, service des photos, secrets
- [ ] `L17-04` Passe accessibilité : focus visible, contrastes, navigation clavier, `aria-pressed` des bascules, `prefers-reduced-motion`
- [ ] `L17-05` Passe performance : budget de chargement, découpage de code, coût réel des grilles `HEAT`
- [ ] `L17-06` Parcours Playwright de bout en bout sur les 8 écrans principaux
- [ ] `L17-07` Passe responsive mobile — cible d'usage principale
- [ ] `L17-08` Journalisation et supervision minimales, `/health` branché
- [ ] `L17-09` Sauvegarde/restauration répétée en conditions réelles
- [ ] `L17-10` Revue de traçabilité : chaque ID du backlog est couvert ou explicitement écarté

**DoD** — déploiement reproductible depuis zéro en suivant uniquement `docs/` ;
`v1.0.0` taguée.

---

## 2. Traçabilité

| Domaine | IDs | Lot(s) |
|---|---|---|
| `AUTH` | 01→08 | L02 (L03 pour 06–07 côté client) |
| `STO` | 01→11 | L01 (07 → L07) |
| `API` | 01→07 | L02 |
| `BODY` | 01→10 | L04 |
| `ACT` | 01→18 | L05 |
| `NUT` | 01→03, 05→10 | L07 · `NUT-04` → L12 · **`NUT-11` hors périmètre v1** |
| `HYD` | 01→05 | L06 |
| `SUP` | 01→06 | L06 |
| `PLAN` | 01→06 | L13 |
| `GOAL` | 01→06 | L14 |
| `IA` | 01→08 | L12 (08 → L14) |
| `IMP` | 01→06 | L12 · **`IMP-07` hors périmètre v1** |
| `AGG` | 01→04 | L08 |
| `HEAT` v2 | 01→04, 14, 18→23 | L09 |
| `HEAT` v2 | 05→13, 15→17, 24, 26→29, 30→32 | L10 |
| `HEAT` v2 | 25, 33 + UI | L11 |
| `NOT` | 01→03 | L15 |
| `DATA` | 01→03 | L16 · `DATA-04` optionnel |
| `OPS` | 01→02 | L17 |

**Écarté de la v1**, à rouvrir ensuite : `NUT-11` (base produits / code-barres —
dépendance externe Open Food Facts), `IMP-07` (import Apple étendu — multi-captures et
anneaux d'activité), `DATA-04` (corrélations, marqué optionnel dans le backlog).

---

## 3. Points de spécification à trancher

Contradictions et zones grises relevées entre les deux backlogs.
**Les 11 décisions ont été validées le 2026-07-26** : elles sont arrêtées et
s'appliquent aux lots indiqués. Toute remise en cause ultérieure se traite comme un
changement de spec, pas comme une question ouverte.

| # | Sujet | Constat | Décision arrêtée | Lot |
|---|---|---|---|---|
| **D1** | Collision d'identifiants `HEAT` | `HEAT-01→08` existent avec deux sens différents dans les deux documents | La v2 fait autorité ; corriger les renvois de `SUP-06` et `HYD-01` dans `backlogV2.md` | L09 |
| **D2** | `settings.csv` vs `settings/` | L'annexe pose `settings.csv` à la racine, la spec `HEAT` pose `settings/heatmap_tracks.csv` | Tout regrouper sous `settings/` : `settings/settings.csv` + les 3 fichiers de pistes. Un fichier et un dossier homonymes au même niveau est légal mais piégeux | L08 |
| **D3** | Cadence des suppléments | `HEAT-23` : la cadence vient de `schedule.frequency`. `HEAT-14` : la cadence est versionnée dans `heatmap_cadences.csv`. Deux sources de vérité | `schedule.frequency` = **valeur courante éditable** (un seul endroit décrit « whey un jour sur deux ») ; `heatmap_cadences.csv` = **journal append-only** alimenté à chaque changement. Le moteur lit le journal pour juger le passé, `schedule` pour le présent. Divergence structurellement impossible | L09 |
| **D4** | Recalcul rétroactif des seuils | `HEAT-20` : changer un seuil réécrit tout l'historique, et « doit être annoncé à l'utilisateur » | Confirmation obligatoire avant validation, avec l'ampleur chiffrée : « 34 jours passeraient de validé à manqué » | L09 / L11 |
| **D5** | Heatmap « suppléments complets » | L'ancien `HEAT-04` (jour complet = toutes les prises planifiées cochées) **n'est pas exprimable** avec les sources de la v2, qui ne connaît qu'un supplément à la fois | Le ratio du jour reste couvert par `SUP-06` au tableau de bord. Si la grille est voulue : ajouter une 7ᵉ source `supplement.completion` — coût faible, à décider une fois les pistes en place | L09 |
| **D6** | Alignement des 371 jours | « 371 jours se terminant aujourd'hui, alignés sur des semaines commençant le lundi » : les deux conditions ne peuvent être vraies ensemble sauf si aujourd'hui est un dimanche | Retenir : `from` = lundi de la semaine d'il y a 52 semaines, `to` = dimanche de la semaine courante (53 colonnes pleines, la dernière partiellement dans le futur et rendue en `off`). L'alignement de grille prime sur la borne exacte | L10 |
| **D7** | Groupe musculaire `autre` | `ACT-06` compte 9 valeurs, les 5 pistes par défaut n'en couvrent que 8 | `autre` reste délibérément non mappé : il ne doit pas polluer une piste. Le mapping étant une configuration, l'utilisateur peut le rattacher s'il le souhaite | L09 |
| **D8** | Cache et écritures externes | `HEAT-33` suppose que l'invalidation suit nos écritures, mais Nextcloud est modifiable depuis un autre appareil ou un tableur | Clé de cache incluant l'ETag des fichiers sources ; le cache ne survit pas à une modification externe | L01 / L11 |
| **D9** | `per_week` par défaut à 2 | 5 groupes × 2 = 10 créneaux musculaires hebdomadaires, plus la course *(décision ouverte du backlog `HEAT`)* | Amorcer les pistes **à partir de la fréquence réelle des 4 dernières semaines**, pas d'une constante. Nécessite des données : à faire au premier lancement, après L05 | L09 |
| **D10** | Validation eau à 1 L | Plancher bas : valide des journées à la moitié de l'objectif *(décision ouverte)* | Passer à **1500 ml**. Le seuil de validation décide vert ou rouge ; à 1 L le vert ne veut rien dire. `HEAT-17` garde le gradient jusqu'à 2 L | L09 |
| **D11** | Suppléments en binaire | Deux doses de whey = information perdue *(décision ouverte)* | Rester binaire par défaut : le mode gradué est déjà supporté (`HEAT-15`), il suffira de renseigner deux seuils si le besoin apparaît | L09 |

---

## 4. Risques

| Risque | Impact | Parade |
|---|---|---|
| Latence et instabilité de Nextcloud/WebDAV comme base de données | Fort | `L01` traité en premier, testé isolément, cache + retry + `409` ; jamais de calcul qui relit N fichiers à chaque affichage |
| Justesse du moteur de cadences (5 cadences × 4 états × versionnement) | Fort | `L10-18` transforme chaque exemple en clair de la spec en test ; `HEAT-30` interdit toute duplication de règle côté client |
| Modèles gratuits OpenRouter indisponibles ou changeants | Moyen | Cascade `IA-03` + `IA-07` : l'app entière fonctionne sans IA |
| Volume des CSV en croissance (`DATA-03` devient nécessaire « dès quelques centaines de lignes ») | Moyen | Filtrage serveur prévu dès `L16` ; repositories conçus pour lire par plage, pas tout le fichier |
| Dérive visuelle par rapport aux guidelines au fil des écrans | Moyen | Aucune couleur ni police en dur (DoD transverse) ; kitchen sink maintenu comme référence |
| Notifications iOS en PWA (restrictions Safari) | Moyen | Vérifier sur un appareil réel dès `L15-01`, avant de construire l'ordonnanceur |

---

## 5. Suivi

| Jalon | Lots | Version cible | État |
|---|---|---|---|
| I — Socle | L00 → L03 | `v0.4.0` | ☑ **livré** — L00 `v0.1.0`, L01 `v0.2.0`, L02 `v0.3.0`, L03 `v0.4.0` |
| II — Domaines | L04 → L08 | `v0.9.0` | ▣ en cours — **L04 à L07 livrés (`v0.8.0`)**, L08 (Agrégats) ferme le jalon |
| III — Assiduité | L09 → L11 | `v0.12.0` | ☐ à faire |
| IV — Intelligence | L12 → L14 | `v0.15.0` | ☐ à faire |
| V — Production | L15 → L17 | `v1.0.0` | ☐ à faire |

Mettre à jour ce tableau et les cases des lots à chaque clôture, en même temps que le
tag et le `CHANGELOG.md`.
