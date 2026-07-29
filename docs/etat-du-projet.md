# État du projet — reprise à froid

Document d'entrée. À lire en premier pour reprendre le développement de **Metric** sans
contexte préalable — que ce soit dans trois mois ou dans une nouvelle session.

**Version courante : `v0.12.2`** · douze lots livrés sur dix-huit. **Le jalon III est
clos** : le moteur d'assiduité calcule, et il a désormais ses écrans. La dette
d'ergonomie qu'il laissait derrière lui est soldée ; **le prochain travail est le lot L12**.

| Mesure | Valeur *(vérifiée le 2026-07-28)* |
|---|---|
| Tests backend | **655**, dont 35 de sécurité sur les photos et **135 sur le moteur d'assiduité** |
| Tests frontend | **149**, dont 21 sur le seul parcours de saisie d'une séance |
| Couverture du moteur | **100 %** de `heatmap/engine.py` |
| Qualité | `ruff`, `mypy --strict`, `eslint`, `tsc --noEmit` sans avertissement |
| Build de production | 120 ko gzip |
| Affichage d'assiduité, Nextcloud réel | 751 ms à froid, **6 ms ensuite** |

---

## 1. Ce qu'est Metric

Suivi sportif personnel : corps, activité, nutrition, hydratation, suppléments, planning,
assiduité. Mono-utilisateur, français, unités métriques.

**Les données vivent en CSV sur Nextcloud.** Il n'y a pas de base de données, et c'est un
choix structurant : les fichiers doivent rester exploitables dans un tableur même si
l'application disparaît.

### Trois documents de référence, dans cet ordre d'autorité

| Document | Contenu | Autorité |
|---|---|---|
| `heat_backlog.md` | Spec `HEAT` v2 — moteur d'assiduité | **Remplace** la partie `HEAT` de la section 12 de `backlogV2.md` |
| `backlogV2.md` | Domaine métier complet, 13 sections, annexe CSV | Référence globale |
| `GuidelinesUI.html` | Tokens, composants, motifs visuels | Référence UI exclusive |

En cas de contradiction entre les deux backlogs, `heat_backlog.md` gagne. Les
contradictions connues sont **tranchées et consignées** au [§3 du ROADMAP](../ROADMAP.md#3-points-de-spécification-à-trancher)
(décisions D1 à D11, validées le 2026-07-26). Ne pas les rouvrir sans raison.

---

## 2. Les invariants

**C'est la section qui compte.** Onze lots les ont suivis ; les casser produirait des
incohérences que les tests n'attraperaient pas tous.

### Aucun calcul métier côté client

Moyennes, écarts, séries, ratios, cadences : tout est calculé par le serveur. La règle
vient de `HEAT-30` mais vaut partout. Deux implémentations d'une même moyenne divergent au
premier cas limite, et c'est l'utilisateur qui arbitre entre deux chiffres qui devraient
être identiques.

Le client formate, il ne dérive pas.

### Le jour suit le fuseau local, jamais UTC

`app/core/dates.py` en détient l'unique implémentation. Une prise à 23 h 30 appartient au
jour qu'affiche l'horloge ; un horodatage sans fuseau est lu comme **local**, pas comme
UTC (`HEAT-32`). La semaine commence le lundi, semaine ISO.

Ne jamais appeler `date.today()` ni `toISOString().slice(0,10)`.

### Toute écriture destructrice passe par un jeton

Chaque ligne lue porte un `token`, empreinte de son contenu. Modifier ou supprimer exige
de le renvoyer en en-tête `If-Match` (`STO-05`). Un en-tête **absent est un conflit**,
jamais une permission — sinon la garde se contournerait en l'omettant.

Côté dépôt : `replace_by_token`, `delete_by_token`, `remove_where` pour les cascades.

Ce qui s'édite **en bloc** — un fichier de configuration — porte la même garde à
l'échelle du fichier : `Sheet.token`, et `CsvRepository.overwrite(items, token=…)`.

### Le fichier doit se lire seul

Certaines colonnes sont dupliquées à dessein : `exercise_log.csv` porte le nom et le groupe
musculaire en plus de `exercise_id`, `supplements/intake_log.csv` porte le nom et la dose.
Ce n'est pas un oubli de normalisation — c'est ce qui permet à `ACT-06` et `SUP-02` d'être
vrais : retirer un exercice ou un supplément **conserve son historique lisible**.

### Aucune valeur inventée à l'écran

Sur historique vide, un écran affiche un tiret et ce que coûte le prochain geste — jamais
un zéro qui passerait pour une mesure. Un groupe musculaire jamais travaillé rend `null`,
pas un grand nombre : « jamais » et « il y a très longtemps » appellent des réponses
différentes.

### Ce qui juge ne lit rien

`app/domains/heatmap/engine.py` décide de l'état d'un jour — `off`, `missed`, `done`,
`bonus` — et **ne connaît ni fichier, ni HTTP, ni horloge**. On lui passe une
configuration, un dictionnaire `date → nombre` et une plage ; il rend une grille.

C'est ce qui rend la justesse vérifiable : chaque exemple de `heat_backlog.md` est un test
de dix lignes, sans application à monter. Une règle d'assiduité écrite ailleurs —
dans `grids.py`, dans un routeur — échapperait à cette batterie. Ne pas en écrire ailleurs.

### Un fichier de configuration ne fait jamais tomber un écran

Deux familles de fichiers, deux comportements, et la frontière est la question « est-ce
que l'utilisateur ouvre ce fichier dans un tableur ? ».

**Configuration, catalogue, planning** — `settings.csv`, les trois fichiers de pistes,
`schedule.csv`, `exercises.csv`, `favorites.csv`. Une cellule vide, un nombre illisible,
une source mal orthographiée y sont des possibilités **normales**. Chaque colonne porte
donc un défaut, chaque lecture typée retombe sur son propre repli, et l'erreur reste
locale : une piste abîmée rend une grille vide, elle n'emporte pas les huit autres. Une
ligne sans identifiant est écartée des listes mais **survit dans le fichier** — on
n'efface pas ce qu'on ne comprend pas.

**Mesure** — pesées, courses, séances, journal d'exercices, repas, prises. Ceux-là restent
stricts : une ligne illisible lève `StorageSchemaError`. On ne devine pas une donnée.

Cette règle a coûté deux incidents avant d'être comprise. Au L08, une cellule vide de
`settings.csv` faisait tomber tous les écrans. Au premier usage réel, une cellule `time`
vide de `schedule.csv` faisait tomber le tableau de bord — et c'était aussi une violation
de `STO-04`, dont la promesse « ajouter une colonne n'invalide aucune ligne ancienne » ne
peut pas tenir si la colonne ajoutée est obligatoire.

**Avant d'ajouter une colonne à un modèle, demandez-vous dans quelle famille il est.**

### Une valeur partagée est servie, jamais recopiée

Les valeurs de repli des réglages — poids cible, objectif d'hydratation, plafond de
sucres — vivent dans `app/domains/app_settings/service.py` et **nulle part ailleurs**.
`GET /api/settings` rend les valeurs effectives *et* les défauts ; le frontend n'en code
aucun.

La même constante écrite dans deux langages tient jusqu'au premier oubli. Servie, elle ne
peut pas diverger.

### Un cache s'invalide sur ce qu'il a lu, pas sur ce qu'il a déclaré

Les grilles d'assiduité sont mémorisées côté serveur. Une grille mémorisée n'est valable
que tant que **tous les fichiers qui l'ont produite** portent le même ETag qu'au moment du
calcul — et cette liste de fichiers est **relevée pendant le calcul** (`FileStore.observe`),
jamais écrite à la main.

La raison est que Nextcloud se modifie derrière notre dos — téléphone, client de synchro,
tableur (décision **D8**). Une liste déclarée aurait l'air juste et cesserait de l'être au
premier fichier lu en plus, sans que rien ne le signale. Le symptôme serait le pire
possible : une grille qui refuse de changer après une saisie.

Corollaire : une réponse servie **sans ETag** n'est pas mémorisée du tout. Un cache qu'on
ne sait pas invalider vaut moins que pas de cache.

### Le doigt est la cible, et il ne vise pas au pixel

`L17-07` désigne le mobile comme **cible d'usage principale**. Depuis la `v0.12.2`, cela
se traduit par des règles, plus par une intention : `--tap` (44 px) est le plancher de
toute chose qu'on touche, `--tap-lg` (56 px) celui de l'action qui **termine** un geste ;
les feuilles de style s'écrivent **mobile d'abord**, les `min-width` ajoutant ce que la
place permet ; un champ numérique descend à 16 px minimum, sinon iOS zoome et décale la
page.

Trois règles encadrent le glissement, et elles ont chacune coûté quelque chose ailleurs :

- **Un geste n'est jamais la seule porte.** L'action qu'un glissement découvre existe
  toujours dans le document, et s'affiche d'emblée là où il y a un pointeur fin. On ne
  découvre pas ce qu'on ne voit pas.
- **Un geste plus vertical qu'horizontal appartient à la page.** Sans cette garde, faire
  défiler une liste au pouce déclencherait son action — qui, sur l'historique, est une
  suppression.
- **Le glissement navigue, il ne mesure pas.** Pas de curseur pour une charge : viser
  82,5 kg au pouce est difficile, et une mesure fausse entrée sans s'en apercevoir coûte
  plus qu'un appui de plus. C'est « aucune valeur inventée à l'écran », appliqué au geste.

Le geste a **une seule implémentation**, `lib/swipe.ts`. Deux en donneraient deux seuils.

### Les erreurs portent un code, pas un texte

Le client décide sur `code` (`API-07`), jamais sur le message. Le message vient du serveur,
en français, et s'affiche tel quel. Catalogue complet dans `app/core/exceptions.py`.

### La protection des routes est portée par le groupe

Un endpoint ajouté à un domaine est protégé **parce qu'il est dans le groupe protégé** de
`app/domains/api.py`, pas parce que son auteur y a pensé.
`test_every_data_route_requires_a_token` lit le schéma OpenAPI publié et le vérifie à
chaque exécution ; un second test interroge réellement chaque lecture sans jeton.

> Première version de ce test : elle parcourait `app.routes` — où FastAPI n'aplatit pas
> les routeurs inclus — et ne vérifiait donc rien pendant deux lots. Si vous ajoutez une
> garde structurelle, vérifiez qu'elle échoue quand elle doit échouer.

---

## 3. Ce qui est construit

| Lot | Version | Contenu |
|---|---|---|
| L00 | `v0.1.0` | Fondations, outillage, tokens UI extraits de la charte, polices locales |
| L01 | `v0.2.0` | Couche stockage WebDAV + CSV : retry, cache à revalidation ETag, garde anti-conflit |
| L02 | `v0.3.0` | Socle API + authentification Argon2id / JWT, anti-brute-force, catalogue d'erreurs |
| L03 | `v0.4.0` | Design system — 18 composants, client API typé, coquille, écran de connexion |
| L04 | `v0.5.0` | Corps : poids et mensurations *(patron de référence)* |
| L05 | `v0.6.0` | Activité : courses, séances, exercices, tonnage, records, groupes négligés |
| L06 | `v0.7.0` | Hydratation & suppléments, checklist optimiste, objet `Cadence` |
| L07 | `v0.8.0` | Nutrition : repas, photos, service sécurisé |
| L08 | `v0.9.0` | Réglages éditables, agrégats du tableau de bord, séries génériques — **clôt le jalon II** |
| L09 | `v0.10.0` | Moteur `HEAT` : modèle de piste, registre de sources, cadences versionnées, jours neutralisés |
| L10 | `v0.11.0` | Moteur `HEAT` : machine à états, cinq cadences, statistiques *(100 % couvert)* |
| L11 | `v0.12.0` | Heatmaps à l'écran, cache de grilles mesuré, réglage des pistes — **clôt le jalon III** |
| L11b | `v0.12.1` | Refonte de l'écran Activité — *dette soldée, pas un lot* |
| L11c | `v0.12.2` | Passe tactile : charte + écran Activité — *avance `L17-07`* |

Le détail de chaque lot — tâches cochées, écarts assumés, décisions — est dans
[`ROADMAP.md`](../ROADMAP.md). Le journal des changements avec le *pourquoi* est dans
[`CHANGELOG.md`](../CHANGELOG.md).

### Écrans disponibles

`/connexion` · `/` tableau de bord · `/corps` · `/activite` · `/routine` · `/nutrition` ·
`/assiduite` · `/reglages` · `/_kitchen-sink` *(référence de charte, publique)*

Le **réglage des pistes** vit dans `/reglages` et non dans `/assiduite` : la piste mise en
avant *est* le réglage `heatmap_metric`, et les séparer aurait obligé à expliquer deux fois
où se règle la même chose.

---

## 4. Où se trouve quoi

```
backend/app/
├── config.py          configuration typée, refuse de démarrer en production si dangereuse
├── core/              socle transverse
│   ├── dates.py       jour local, semaine ISO          ← invariant temporel
│   ├── cadence.py     grammaire des cadences           ← utilisé par L09/L10
│   ├── parsing.py     durées, distances, décimales FR  ← réutilisé par l'import Apple
│   ├── validation.py  bornes de vraisemblance (API-06)
│   ├── exceptions.py  catalogue d'erreurs (API-07)
│   ├── security.py    Argon2id + JWT
│   └── deps.py        dépendances FastAPI
├── storage/           WebDAV, cache (contenu **et** absence), dépôt CSV typé
│                      `files.py` sait aussi dire ce qu'il a lu (`observe`) et
│                      lire en parallèle (`prefetch`) ← à réutiliser
└── domains/<nom>/     models · schemas · service · router
                       (activity a un `stats.py` de plus ; aggregates n'a pas de
                        `models.py`, c'est le seul domaine sans fichier à lui)

backend/app/domains/heatmap/   le domaine le plus découpé, et la frontière compte
├── engine.py          **juge** — pur, sans fichier ni horloge. Toute règle vit ici
├── grids.py           **coud** — ingrédients → moteur → formes publiées
├── sources.py         registre : une source rend un nombre par jour, rien d'autre
├── cache.py           grilles mémorisées, invalidées par la version de leurs sources
└── service.py         pistes, cadences versionnées, jours neutralisés

frontend/src/
├── components/ui/     bibliothèque de la charte
├── features/<nom>/    types + appels d'un domaine, aucun calcul
├── lib/               api, auth, query, format, cx
└── routes/            un écran par domaine
                       (`settings/` regroupe les sections de l'écran Réglages,
                        qui en porte deux depuis le L11)
```

**Avant d'ajouter un domaine, lire [`docs/patron-domaine.md`](patron-domaine.md).** Il
décrit les quatre fichiers, les deux pièges de calcul déjà rencontrés, les huit familles
de tests à écrire, et une liste de reprise.

---

## 5. Comment vérifier

```bash
make console      # console interactive : start / stop / status / logs
make check        # lint + types + tests, des deux côtés — ce que rejoue la CI
```

`make check` doit être vert avant tout commit. Il couvre `ruff`, `mypy --strict`,
`pytest`, `prettier`, `eslint`, `tsc --noEmit` et `vitest`.

La console choisit un port libre si le port habituel est pris, et le proxy du frontend
suit via `METRIC_API_PORT`.

### Convention de versioning

Un lot = une version mineure = un tag `v0.N.0`. Un lot n'est clos que si sa **DoD** est
intégralement vérifiée — pas de lot « clos à 90 % ». `CHANGELOG.md` est alimenté à la
clôture, avec le *pourquoi* des décisions et une section **Non vérifié** quand quelque
chose n'a pas pu l'être.

---

## 6. Ce qui attend une action de votre part

### La chaîne réelle est vérifiée, et mesurée

`make check-storage` a été lancé le 2026-07-28 : connexion, écriture, relecture,
nettoyage — et surtout **`If-None-Match` honoré avec un `304`**. C'était la prémisse de
toute la conception du cache (décision **D8**) ; elle est vérifiée et non plus supposée.

**La latence est chiffrée**, et c'est le chiffre à connaître avant d'optimiser quoi que ce
soit dans ce projet :

| | Durée |
|---|---|
| Aller-retour WebDAV unitaire | **~180 ms** |
| Écran d'assiduité, cache froid | 751 ms |
| Écran d'assiduité, affichage suivant | 6 ms |
| Après expiration du TTL, 7 revalidations `304` | 448 ms |

Deux conséquences valent d'être retenues.

**Le réseau était déjà réglé** par le cache de `FileStore` (`STO-06`) avant le lot L11. Le
profilage d'un affichage l'a montré : les 50 ms restantes étaient du calcul refait à
l'identique, dont 70 % d'analyse CSV — six mille lignes revalidées par affichage parce que
neuf pistes rouvrent les mêmes cinq fichiers. Un cache qui aurait visé le réseau aurait
doublé un mécanisme existant sans rien gagner. **Profiler avant d'optimiser a changé la
conception, pas seulement son réglage.**

**À 180 ms l'aller-retour, l'ordre des lectures compte plus que leur nombre.** Sept
fichiers lus l'un après l'autre font plus d'une seconde ; lus en parallèle
(`FileStore.prefetch`), ils en font un peu plus d'un. Tout écran qui ouvre plusieurs
fichiers devrait les précharger ensemble.

### Quatre décisions ouvertes, sans urgence

- **Supprimer un repas ne supprime pas sa photo** (L07). Choix assumé : l'effacer d'un clic
  ferait perdre un souvenir qu'aucune annulation ne rendrait. À inverser si vous préférez.
- **`heatmap_metric` n'est pas contraint à une liste fermée** (L08). Les pistes existent
  depuis le L09, et l'écran Réglages les met en avant d'un clic depuis le L11 : le champ
  libre ne sert plus qu'à saisir un identifiant qui n'existe pas. Bon candidat au
  resserrement.
- **`/_kitchen-sink` est publique** (L03) : aucune donnée utilisateur, consultable sans
  session, vérifiable par capture automatisée.
- **`MIN_LENGTH` du mot de passe abaissé à 6** dans `hash_password.py`. C'est l'unique
  porte d'entrée vers un an de données personnelles, sans second facteur.

### Ce que le premier usage réel a révélé

Trois défauts trouvés en lançant l'application, aucun par les tests. Ils sont corrigés,
mais ce qu'ils disent vaut d'être retenu.

| Défaut | Ce qu'il enseigne |
|---|---|
| `make dev` échouait sur `wait: -n: invalid option` | macOS livre bash **3.2**, pas 4.3. Un script de développement doit tourner sur le shell que la machine a. Aucun autre bashisme de bash 4 dans le dépôt, vérifié |
| Une cellule `time` vide dans `schedule.csv` faisait tomber le **tableau de bord entier** en `502` | `STO-04` promet qu'ajouter une colonne n'invalide aucune ligne ancienne — cette promesse ne tient pas si la colonne est obligatoire. Les fichiers de **catalogue et de planning** portent maintenant un défaut sur chaque colonne |
| Le bouton « ouvrir » d'une séance semblait inerte | Le panneau s'ouvrait hors du champ de vision, et `void promesse.then(...)` avalait les refus du serveur. Le parcours n'avait **aucun test d'écran** — c'est pour cela qu'il est passé |

**La leçon commune** : tout ce qui a été trouvé ici l'a été en *utilisant* l'application,
pas en la testant. Lancer `make dev` et saisir une vraie séance après chaque lot vaut mieux
que dix tests de plus.

**Et elle s'est confirmée deux fois de suite.** La refonte de l'écran Activité (`v0.12.1`)
est partie avec vingt-quatre tests d'écran verts ; deux défauts n'en sont sortis qu'en
regardant la page — une date écrite deux fois, et une phrase promettant d'ouvrir « la
séance la plus récente » sur un écran qui n'en avait aucune. La passe tactile (`v0.12.2`)
en a produit trois de plus, dont un qu'aucun test ne pouvait voir : **les colonnes de
l'historique ne s'alignaient pas d'une ligne à l'autre**, chaque fiche étant sa propre
grille où une piste `auto` se résout selon son seul contenu.

Un test vérifie ce qu'on a pensé à vérifier ; l'œil voit ce qu'on n'avait pas prévu. Une
mesure automatisée voit encore autre chose : c'est en interrogeant le DOM sur la hauteur
de chaque contrôle qu'on a trouvé la navigation à 33 px, que personne n'avait remarquée en
onze lots.

### La dette d'ergonomie de l'écran Activité — soldée en `v0.12.1`

Le panneau de saisie des charges n'existait que si une séance était **active**, alors que
le catalogue d'exercices, lui, était toujours visible avec son formulaire. Le regard
tombait donc sur le seul formulaire qui ne prend aucun chiffre.

Le journal est désormais **toujours affiché**, en pleine largeur et en tête de la zone de
saisie, avec un sélecteur de séance ; la plus récente s'ouvre d'office. Le catalogue passe
en dernier et dit qu'il se déclare une fois. Treize tests d'écran couvrent ce parcours.

**Pourquoi avant le lot L12 et pas après** : `IMP-02` pré-remplit une course et une séance
depuis une capture Apple — l'import se greffe donc exactement sur ce parcours. L'argument
« aucune ligne partagée » avait écarté la dette du L11 ; le même argument, appliqué au L12,
la faisait passer devant.

**Ce qui n'a pas été fait, et pourquoi.** Le journal n'a pas été remonté en tête d'écran :
les cinq écrans du projet posent les indicateurs d'abord, la saisie ensuite, et régler
celui-ci en désalignant les quatre autres aurait coûté plus que la gêne. Le catalogue n'a
pas été replié derrière un dépliant : `GuidelinesUI.html` n'en a pas, et la charte est la
référence exclusive.

---

## 7. Prochain lot — L12

**Couche IA + analyse de repas + import Apple.** Il ouvre le jalon IV.

Son UI se greffe sur un écran désormais tactile : le bloc IA, l'aperçu d'import et le
bouton « Pas d'accord » suivent les règles du §2 — plancher de 44 px, mobile d'abord, et
les contrôles de `primitives.tsx` (`Stepper`, `Chip`, `ChipStrip`, `SwipeRow`) plutôt que
de nouveaux. Une valeur **proposée** par l'IA se corrige au doigt, sinon elle sera adoptée
telle quelle faute de pouvoir la retoucher — ce qui viderait `NUT-04` de son sens.

Le contrat structurant est `IA-07` : **sans clé API, aucune fonctionnalité n'est bloquée.**
L'application reste pleinement utilisable en saisie manuelle, et le manque de clé se dit
en clair plutôt que de faire échouer un écran. C'est la même règle que « un fichier de
configuration ne fait jamais tomber un écran », appliquée à une dépendance externe.

Trois points à ne pas manquer, tous déjà écrits dans le backlog :

- **La cascade multi-modèles** (`IA-03`) doit distinguer « quota saturé » de « autre
  erreur ». Les deux mènent à un échec, mais l'un se résout en attendant et l'autre non —
  et l'utilisateur n'a pas la même conduite à tenir.
- **Ce que l'IA propose n'est jamais imposé** (`NUT-04`, `IMP-02`). Les valeurs proposées
  doivent être visuellement distinctes des valeurs saisies, et rien ne s'écrit sans
  validation. C'est le pendant de « aucune valeur inventée à l'écran ».
- **Les conversions de l'import Apple laissent vide ce qu'elles ne savent pas**
  (`IMP-03`). Une valeur absente reste absente ; la deviner ferait entrer une mesure
  fausse dans un fichier qui est censé rester exploitable dans dix ans.

**La clé OpenRouter est configurée** (`ai_enabled` vrai au démarrage). La conduite arrêtée
le 2026-07-29 : **développement et tests intégralement sur réponses simulées** — `L12-16`
l'exige de toute façon (JSON bavard, JSON tronqué, `429` en cascade, aucune clé). Le vrai
service n'est appelé que pour les deux choses qui ne se simulent pas — la découverte des
modèles gratuits (`IA-02`, dont le catalogue réel change en permanence) et une passe de
bout en bout sur un vrai screenshot à la DoD — **et jamais sans accord préalable**. Tout
test qui appellerait réellement OpenRouter reste hors de `make check` : il ne serait pas
déterministe.

### Ce que L11 laisse en place

| Pièce | Où |
|---|---|
| `GridService.view` / `.multi_view` / `.inspect` | les trois lectures de la spec §8, publiées |
| `GridService.impact` | simulation d'une modification, sans rien écrire (**D4**) |
| `GridCache` + `FileStore.observe` | mémorisation invalidée par les fichiers réellement lus |
| `FileStore.prefetch` | lecture parallèle — à réutiliser dans tout écran multi-fichiers |
| `Source.paths` | chemins déclarés par source, pour le préchargement uniquement |

### Deux dettes nommées, par ordre de valeur

La troisième — la refonte de l'écran Activité — est **soldée en `v0.12.1`** (voir §6).
C'était la seule qu'un usage réel avait fait remonter. Ce qui reste n'a été relevé que par
lecture du code, ce qui est une raison de les traiter plus tard, pas plus tôt.

1. **Navigation par plage sur l'écran Assiduité.** L'API accepte `from`/`to` et les valide ;
   l'écran s'en tient aux 53 semaines par défaut. Une année précédente n'est pas
   consultable.
2. **Réordonnancement par glisser-déposer.** « Monter » / « Descendre » fonctionne et coûte
   un appel par cran.

### Ce qui n'a pas pu être éprouvé

**Rien n'a jamais été touché sur un vrai téléphone.** La passe tactile est mesurée dans un
Chrome émulant un iPhone 14, en évènements tactiles réels : cibles, débordement,
glissements, tout est vérifié. Mais l'émulation ne reproduit ni l'imprécision du pouce, ni
le clavier système qui remonte sur le champ actif, ni la latence. **Ouvrir `/activite` sur
le téléphone et consigner une vraie série est le test qui manque.**

Et `L17-07` n'est pas clos : sept écrans sur huit n'ont pas eu la passe.

**Aucune grille n'a encore un an d'historique réel derrière elle.** Les pistes ayant été
amorcées le jour de la livraison, `HEAT-07` les rend `off` sur tout le passé et le taux de
respect vaut `null` — comportement correct, mais qui laisse le rendu d'une grille dense et
le calcul des longues séries vérifiés sur données simulées uniquement. **Rouvrir
`/assiduite` dans un mois est le vrai test de ce lot.**

> `AGG-03` et `HEAT-27` sont **deux algorithmes distincts et le resteront** : le premier
> mesure l'assiduité de suivi, le second le respect d'un engagement. Ne pas les fusionner.
