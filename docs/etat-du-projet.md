# État du projet — reprise à froid

Document d'entrée. À lire en premier pour reprendre le développement de **Metric** sans
contexte préalable — que ce soit dans trois mois ou dans une nouvelle session.

**Version courante : `v0.16.0`** · seize lots livrés sur dix-neuf. Le jalon IV est
**complet mais ouvert** : la couche IA existe, elle estime une assiette, lit une capture
Apple, propose un planning, fixe un objectif, rend un bilan et répond aux questions.
**Ses quatre lots ont une DoD vérifiée à moitié** — L12, L13, L14, L14b — et le §7 dit
lesquelles, ce qui reste, et pourquoi cela ne peut pas se vérifier autrement qu'à la main.

| Mesure | Valeur *(vérifiée le 2026-08-08)* |
|---|---|
| Tests backend | **1099**, dont 35 de sécurité sur les photos, **135 sur le moteur d'assiduité**, **120 sur la couche IA**, **110 sur le planning**, **93 sur les objectifs** et **105 sur l'assistant** — carnet, fils, contrat, actions |
| Tests frontend | **239**, dont 28 sur les parcours d'estimation et d'import, 19 sur le planning, 19 sur les objectifs, 24 sur l'assistant |
| Couverture du moteur | **100 %** de `heatmap/engine.py` |
| Qualité | `ruff`, `mypy --strict`, `eslint`, `tsc --noEmit` sans avertissement |
| Build de production | 127 ko gzip |
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

**Pour installer ou mettre à jour un serveur**, tout est dans
[`docs/deploiement.md`](deploiement.md) : prérequis, structure de dossiers, unité systemd,
réglages Nginx Proxy Manager, sauvegarde, retour arrière, et une table des symptômes — parce
qu'en exploitation, un symptôme ne ressemble jamais à sa cause.

Deux documents n'ont pas d'autorité mais se lisent avant de livrer :
[`docs/verifications-manuelles.md`](verifications-manuelles.md) — **ce que `make check` ne
peut pas vérifier**, accumulé lot après lot, avec ce qu'on lance et ce qui compte comme
échec — et [`docs/front.md`](front.md), la carte des onze pages et des cinq couches de
l'interface, avec ce qu'une refonte a le droit de changer et ce qu'elle ne doit pas casser.

En cas de contradiction entre les deux backlogs, `heat_backlog.md` gagne. Les
contradictions connues sont **tranchées et consignées** au [§3 du ROADMAP](ROADMAP.md#3-points-de-spécification-à-trancher)
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

**Configuration, catalogue, planning, carnet** — `settings.csv`, les trois fichiers de
pistes, `supplements/schedule.csv`, `planning/plan.csv`, `goals/goals.csv`,
`insights/weekly.csv`, `insights/memory.csv`, `exercises.csv`, `favorites.csv`. Une cellule vide, un nombre illisible,
une source mal orthographiée y sont des possibilités **normales**. Chaque colonne porte
donc un défaut, chaque lecture typée retombe sur son propre repli, et l'erreur reste
locale : une piste abîmée rend une grille vide, elle n'emporte pas les huit autres.

> **Un défaut de colonne ne suffit pas à tenir cette promesse**, et il a fallu un `502` en
> usage réel pour le voir. `CsvModel.from_csv` n'applique le défaut qu'aux cellules
> **vides** ; une cellule *remplie de travers* — un horodatage dans une colonne de date —
> lève encore. Les colonnes de ces fichiers s'annotent donc `CsvDate` et `CsvNumber`
> (`app/storage/model.py`), qui retombent sur leur repli au lieu de lever. Un horodatage
> est **récupéré** — le jour y est écrit, le lire n'est pas l'inventer. Une
ligne sans identifiant est écartée des listes mais **survit dans le fichier** — on
n'efface pas ce qu'on ne comprend pas.

**Mesure** — pesées, courses, séances, journal d'exercices, repas, prises. Ceux-là restent
stricts : une ligne illisible lève `StorageSchemaError`. On ne devine pas une donnée.

Cette règle a coûté deux incidents avant d'être comprise. Au L08, une cellule vide de
`settings.csv` faisait tomber tous les écrans. Au premier usage réel, une cellule `time`
vide de `schedule.csv` faisait tomber le tableau de bord — et c'était aussi une violation
de `STO-04`, dont la promesse « ajouter une colonne n'invalide aucune ligne ancienne » ne
peut pas tenir si la colonne ajoutée est obligatoire.

`planning/plan.csv` est le cas limite de la famille, et il vaut d'être connu : sa colonne
`time` est vide **par conception** — `PLAN-02` dit l'heure facultative. Là où la cellule
vide de `schedule.csv` était un accident, celle-ci est le cas normal.

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

### Une valeur proposée n'est pas une mesure

Ce qu'un modèle rend comme **valeur** est proposé : affiché comme tel — trait discontinu,
teinte du bloc IA, `aria-description` —, corrigeable au doigt, et jamais écrit sans
validation (`NUT-04`, `IMP-02`). Retoucher une proposition la fait sienne, et la marque
disparaît.

> **Ce que le lot L18 a changé, et ce qu'il n'a pas changé.** L'assistant peut désormais
> **agir** : ajouter une séance, créer un exercice, supprimer un repas. L'invariant tient
> quand même, parce qu'il porte sur les valeurs *estimées* — une macro lue sur une photo,
> une charge devinée — et non sur un geste demandé explicitement. Ce qui le remplace pour
> les actions est écrit dans `domains/assistant/actions.py` : deux niveaux fixés par la
> table et non par le modèle, un ajout annulable d'un appui, une correction ou une
> suppression qui n'écrit rien sans confirmation, et **aucun chemin d'écriture parallèle**
> — les schémas et les services des domaines sont ceux de l'API.
>
> La mémoire, elle, a bel et bien changé de régime : `IA-10` retient sans valider, et la
> correction vient après. Le compromis tient pour un carnet et **ne tiendrait pas pour une
> mesure** — une note fausse ne casse aucun chiffre, elle change ce que l'assistant croit
> savoir, et cela se lit.

C'est « aucune valeur inventée à l'écran » appliqué à l'estimation, et c'est le cas
**difficile** : un zéro se repère, un chiffre inventé par un modèle est plausible.

Deux corollaires, qui ont chacun une raison :

- **Hors bornes, on écarte ; on ne ramène pas à la borne.** 4000 g de protéines ramenés à
  500 g donneraient une valeur fausse d'apparence honnête.
- **Une réponse tronquée ne rend rien.** Compléter des accolades manquantes reviendrait à
  inventer les valeurs qu'elles contenaient. On passe au modèle suivant (`IA-03`).

### Sans clé, rien n'est bloqué

`IA-07` : l'IA est un confort, jamais un prérequis. Sans clé, `AiServiceDep` fait échouer
l'endpoint avec un code du catalogue — l'appelant n'a rien à vérifier lui-même —, les
écrans ne proposent simplement pas l'assistance, et `/reglages` dit ce qui manque.

C'est « un fichier de configuration ne fait jamais tomber un écran », appliqué à une
dépendance externe.

### Ce qui est mis en cache ne porte jamais un chiffre

Le service worker du lot L15 met en cache **la coquille, les polices et les icônes** — et
rien d'autre. Tout ce qui commence par `/api` va au réseau, **sans repli**.

Un écran servi depuis le cache avec les chiffres d'hier est une valeur inventée à l'écran
au sens le plus littéral, et c'est le pire cas de tout le §2 : il n'y a ni tiret, ni
« chargement… », ni erreur — il y a un poids, et il est faux. Rien à l'écran ne permet de
s'en apercevoir.

La décision vit dans une **fonction pure de l'URL**, `frontend/src/sw/strategy.ts`,
testable sans monter de service worker. Une exception écrite ailleurs — « juste pour le
tableau de bord » — échapperait à sa batterie.

### Un rappel dit ce qui n'est pas noté, pas ce qui n'a pas été fait

« Tu n'as pas bu aujourd'hui » est une **affirmation fausse** : l'application sait seulement
que rien n'a été consigné. C'est « aucune valeur inventée » appliqué à une notification, et
c'est le cas difficile — une notification est lue en trois mots, sur un écran verrouillé,
sans contexte et sans moyen de vérifier.

Un chiffre **relevé** se cite tel quel : « 750 ml notés sur 2000 » est vrai et utile. C'est
l'**absence** qu'on n'a pas le droit de transformer en affirmation.

La règle vit dans `domains/notifications/reminders.py`, qui est pur — ni fichier, ni
horloge. Trois garde-fous l'accompagnent, et ils sont dans le code : le défaut est le
silence, un rappel par créneau et par jour, une fenêtre de rattrapage d'une heure.
**Un rappel qui arrive au mauvais moment se désinstalle en un geste et ne revient jamais.**

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

**Une seule route de données échappe au groupe**, et elle porte sa propre garde : le flux
`.ics` du planning (`PLAN-05`). Un abonnement Apple Calendar va chercher son fichier tout
seul, périodiquement, **sans pouvoir porter d'en-tête `Authorization`** — exiger le jeton
livrerait une fonctionnalité incapable de fonctionner.

Elle est donc montée au niveau de l'application, avec la santé et la documentation, et
**hors du schéma publié** : l'y déclarer demanderait d'inscrire une exception permanente
dans la garde de `AUTH-05`, c'est-à-dire d'ouvrir une porte dans le mécanisme même qui les
interdit. Ce qu'elle doit en échange est écrit dans `app/domains/planning/router.py` — clé
d'au moins 32 caractères, comparaison à temps constant, rien de publié sans clé, et le même
refus pour une clé fausse que pour un flux inexistant.

**Si une deuxième route demande un jour la même exception, elle n'y a pas droit.** C'est
la forme du besoin qui l'a justifiée ici, pas la commodité.

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
| L12 | `v0.13.0` | Couche IA OpenRouter, estimation d'assiette, import Apple — **ouvre le jalon IV** |
| L13 | `v0.14.0` | Planning sport, génération assistée, flux iCal abonnable |
| L14 | `v0.15.0` | Objectifs IA, progression réelle, bilan hebdomadaire |
| L14b | `v0.16.0` | Assistant conversationnel, mémoire de santé, garde-fou médical |
| L15 | `v0.17.0` | PWA installable, service worker, Web Push, rappels ordonnancés — **ouvre le jalon V** |

Le détail de chaque lot — tâches cochées, écarts assumés, décisions — est dans
[`ROADMAP.md`](ROADMAP.md). Le journal des changements avec le *pourquoi* est dans
[`CHANGELOG.md`](../CHANGELOG.md).

### Écrans disponibles

`/connexion` · `/` tableau de bord · `/corps` · `/activite` · `/planning` · `/objectif` ·
`/routine` · `/nutrition` · `/assiduite` · `/reglages` · `/assistant` *(**hors navigation**
depuis le L14b — on y entre par le tableau de bord et l'écran Objectif)* ·
`/_kitchen-sink` *(référence de charte, publique — **hors navigation** depuis le L14)*

La barre s'arrête à neuf entrées, et ce n'est plus une commodité : elle demande **806 px
pour 695 disponibles**, mesurés entrée par entrée. Deux écrans sont donc atteints
autrement. La carte du front — [`docs/front.md`](front.md) — porte le détail et les deux
leviers qui restent.

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
                       (activity a un `stats.py` de plus ; aggregates, ai et imports
                        n'ont pas de `models.py` — ils ne possèdent aucun fichier CSV)

backend/app/domains/ai/        la couche IA, sans fichier ni domaine métier
├── client.py          transport OpenRouter, et la distinction quota / panne
├── service.py         cascade bornée, catalogue mémorisé une heure, cycle de vie
├── extract.py         lire un JSON dans de la prose, sans jamais compléter
├── images.py          1024 px, JPEG, data URL
└── deps.py            `AiServiceDep` — sans clé, l'endpoint ne s'exécute pas

backend/app/domains/imports/   n'écrit que dans les fichiers du domaine Activité
├── analysis.py        consigne au modèle, relecture, conversions (`IMP-03`)
├── service.py         `analyze` ne sait pas écrire, `confirm` ne lit aucune image
└── schemas.py         brouillon (tout nullable) et charge utile (bornée)

backend/app/domains/assistant/  conversation et carnet de santé
├── context.py         **rassemble** le condensé — ne calcule rien, publie tout
├── conversation.py    consigne, relecture, garde-fou médical — pur, sans fichier
├── service.py         `ask` ne sait pas écrire, `remember` ne sait pas interroger
└── router.py          compose deux domaines : il va chercher `PLAN-06` lui-même

backend/app/domains/goals/      objectifs et bilans hebdomadaires
├── metrics.py         désigne cinq métriques du registre, n'en définit aucune
├── progress.py        **juge** — pur, sans fichier ni horloge. L'avancement vit ici
├── generation.py      consigne, condensé factuel, relecture (`GOAL-01`, `GOAL-02`)
├── weekly.py          consigne et relecture du bilan (`IA-08`) — pur lui aussi
├── service.py         `propose` ne sait pas écrire, `adopt` ne sait pas interroger
└── router.py          compose les deux domaines : il va chercher `PLAN-06` lui-même

backend/app/domains/planning/   le premier domaine à porter des dates futures
├── models.py          famille *planning* : chaque colonne a un défaut, `time` comprise
├── ical.py            RFC 5545 — sans dépôt ni HTTP, donc vérifiable sur des valeurs fixes
├── generation.py      consigne, calendrier écrit en clair, relecture (`PLAN-03`)
├── service.py         lit trois fichiers, n'en écrit qu'un ; `propose` ne sait pas écrire
└── router.py          deux routeurs — le protégé, et le flux `.ics` public par clé

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
make console      # console de supervision — la porte d'entrée
make dev          # API + frontend, en local uniquement
make dev-lan      # idem, mais joignable depuis un téléphone du réseau
make preview      # le build de production sur :4173 — le seul endroit où vit le service worker
make check        # lint + types + tests, des deux côtés — ce que rejoue la CI
```

**`make console` pilote quatre services**, pas deux, depuis le lot L15 : `api`, `web`,
`preview` (le build de production) et `tunnel` (HTTPS éphémère). Les deux derniers ne
démarrent **jamais tout seuls** — `preview` peut servir un build vieux d'une semaine, et
`tunnel` ouvre l'application sur l'Internet public. Elle porte aussi `push`, qui dit d'un
coup d'œil si un rappel partira, et `proxy`, qui dit ce qu'un reverse-proxy demande.

> **Le projet ne se conteneurise pas pour se vérifier.** Le HTTPS d'une passe sur téléphone
> vient d'un tunnel éphémère ; le HTTPS durable viendra de **Nginx Proxy Manager**, en
> amont. Ni l'un ni l'autre n'est `docker compose`, et `L17-01` reste entier.

### Ouvrir l'application sur un téléphone

`make dev-lan` annonce l'URL à saisir (`http://<ip>:5180/`). Trois choses à savoir :

- **Seul le frontend est exposé.** Le proxy de Vite relaie `/api` depuis la machine de
  développement vers `127.0.0.1:8000` : l'API — donc les identifiants Nextcloud et le
  secret JWT — reste injoignable depuis le réseau. Ne pas ajouter `--host` à uvicorn.
- **Port dédié `5180`, en `--strictPort`**, et non le 5173 habituel. Vite ne cherche un
  port libre que sur l'adresse qu'il va écouter : un autre projet tenant `[::1]:5173`
  laisse `*:5173` libre, les deux serveurs démarrent, et l'application obtenue dépend de
  l'adresse tapée. Sur un téléphone, c'est indémêlable. Le cas s'est produit.
- **C'est du `http://` en clair**, sur un réseau de confiance seulement. Le jour où le lot
  L15 amènera la PWA, les service workers exigeront un contexte sécurisé.

`make check` doit être vert avant tout commit. Il couvre `ruff`, `mypy --strict`,
`pytest`, `prettier`, `eslint`, `tsc --noEmit` et `vitest`.

**Et il ne suffit pas.** Ce qu'il ne peut pas voir — un vrai téléphone, une vraie capture,
une grille après un mois d'historique — vit dans
[`docs/verifications-manuelles.md`](verifications-manuelles.md), avec pour chaque entrée le
geste à faire et ce qui compte comme échec. Trois lots de suite, ce sont ces
vérifications-là qui ont trouvé les défauts, pas la batterie de tests.

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

**Et elle s'est confirmée quatre fois de suite.** La refonte de l'écran Activité (`v0.12.1`)
est partie avec vingt-quatre tests d'écran verts ; deux défauts n'en sont sortis qu'en
regardant la page — une date écrite deux fois, et une phrase promettant d'ouvrir « la
séance la plus récente » sur un écran qui n'en avait aucune. La passe tactile (`v0.12.2`)
en a produit trois de plus, dont un qu'aucun test ne pouvait voir : **les colonnes de
l'historique ne s'alignaient pas d'une ligne à l'autre**, chaque fiche étant sa propre
grille où une piste `auto` se résout selon son seul contenu.

Le lot L13 en a produit deux de plus, le L14 trois — dont **une violation d'invariant** :
un anneau de progression qui affichait « 0% » là où l'avancement était indéterminé, sous
quatre-vingt-treize tests d'API et dix-neuf tests d'écran verts.

Un test vérifie ce qu'on a pensé à vérifier ; l'œil voit ce qu'on n'avait pas prévu. Une
mesure automatisée voit encore autre chose : c'est en interrogeant le DOM sur la hauteur
de chaque contrôle qu'on a trouvé la navigation à 33 px, que personne n'avait remarquée en
onze lots — et c'est en la réinterrogeant au L14 qu'on a su que la barre demandait 806 px
pour 695, entrée par entrée.

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

## 7. Où en sont les lots L12 à L14b, et ce qu'il reste

**Quatre lots livrés, quatre DoD vérifiées à moitié, et pour la même raison.** Aucun n'est
clos : la convention du projet ne connaît pas le « clos à 90 % ».

Ce qui manque aux quatre tient en une phrase — **la chaîne n'a jamais été branchée sur le
vrai monde**. Un modèle réel n'a pas lu de capture, un client de calendrier réel ne s'est
pas abonné au flux, aucun objectif n'a atteint son échéance, aucune question n'a reçu de
vraie réponse. Tous demandent un geste manuel, tous consignés dans
[`verifications-manuelles.md`](verifications-manuelles.md), et l'appel à un modèle réel
demande en plus **un accord préalable, à chaque fois**.

### Le lot L14b — assistant et mémoire de santé (`v0.16.0`)

**Vérifié** : rien n'est écrit avant validation, des deux côtés. Le condensé est borné,
publié à l'écran, et une note personnelle de repas n'y entre pas — un test le constate sur
le texte réellement envoyé. Le carnet fonctionne entièrement sans clé.

**Ce qui reste** : poser une vraie question à un vrai modèle. C'est la seule chose que la
simulation ne peut pas dire — si la réponse *s'appuie* sur les chiffres qu'on lui a donnés
plutôt que d'en inventer de plausibles, et si ce qu'elle propose de retenir vaut d'être
retenu. Le geste est au §3 de
[`verifications-manuelles.md`](verifications-manuelles.md).

**Deux pièces de ce lot resserviront ailleurs :**

| Pièce | Où | Ce qu'elle fait |
|---|---|---|
| `context.build` | `domains/assistant/` | tout ce que l'app sait, en une douzaine de lignes, sans rien recalculer |
| `_echoes` | `domains/assistant/conversation.py` | écarte une note qui ne fait que redire une ligne du condensé |

**Ce que sa passe navigateur a appris**, et qui vaut pour tout le projet : l'écran était
correct partout — aucune cible sous 44 px, aucun débordement, contenu aligné — et le champ
de question descendait de **289 px par échange**, sur l'écran dont poser une question est
le seul objet. Une mesure unique donnait un chiffre qui n'avait l'air de rien ; il a fallu
mesurer trois fois de suite. **Quand un écran s'allonge à l'usage, le mesurer une fois
revient à ne pas le mesurer.**

### Le lot L14 — objectifs et bilan hebdomadaire (`v0.15.0`)

**Vérifié** : rien n'est écrit avant adoption, des deux côtés — le fichier n'existe
toujours pas après une proposition, aucune requête d'écriture ne part de l'écran. Et
`GOAL-02` est vérifiable plutôt que déclaratif : une note personnelle de repas
**n'atteint pas** la consigne, un test le constate sur le texte réellement envoyé, et
l'écran publie le condensé ligne à ligne.

**Ce qui reste** : qu'une échéance passe. Le résultat final — atteint, partiel — se calcule
sur des données qui n'existent pas encore, et c'est le seul endroit du projet où une moitié
de DoD demande six semaines plutôt qu'un geste. Un raccourci existe pour vérifier la
clôture sans attendre : antidater `created` et `deadline` dans un tableur. Il ne vérifie
pas la progression réelle.

**Trois pièces de ce lot resserviront ailleurs :**

| Pièce | Où | Ce qu'elle fait |
|---|---|---|
| `progress.py` | `domains/goals/` | avancement vers une cible — pur, sans fichier ni horloge |
| Trois métriques | `aggregates/service.py` | séances/sem, km/sem, protéines/j, servies aussi par `AGG-04` |
| `Call.prompt` | `tests/fake_openrouter.py` | ce qui est **réellement** envoyé au modèle, journalisé |

**Ce que sa passe navigateur a appris**, et qui vaut pour tout le projet : l'anneau de
progression affichait « 0% » là où l'avancement était indéterminé. Le schéma rendait
`null`, un test le vérifiait, l'écran ne colorait pas l'anneau — et le composant dessinait
quand même le pourcentage, parce qu'un anneau dessine un pourcentage. Quatre décisions
correctes, une page qui ment. **Une valeur inventée à l'écran ne se voit qu'à l'écran.**

### Le lot L13 — planning sport et flux iCal (`v0.14.0`)

**Vérifié** : rien n'est écrit avant adoption. Deux batteries le constatent depuis deux
angles — côté serveur, le fichier **n'existe toujours pas** après une proposition ; côté
écran, aucune requête d'écriture n'est partie. Le retrait individuel est vérifié sur la
charge utile réellement envoyée, pas sur l'état du composant.

**Ce qui reste** : abonner Apple Calendar au flux. Un `.ics` peut satisfaire la RFC 5545 et
être refusé sans un mot — les symptômes d'un pliage de ligne fautif ou d'un `UID` instable
sont un calendrier vide, ou un doublon **par modification**, indéfiniment.

Trois pièces de ce lot resserviront ailleurs :

| Pièce | Où | Ce qu'elle fait |
|---|---|---|
| `CsvRepository.extend` | `storage/csv_repo.py` | plusieurs lignes en **une** écriture |
| `ical.py` | `domains/planning/` | RFC 5545, sans dépôt ni HTTP |
| `PlannedDate` | `core/validation.py` | la borne de ce qui a le droit d'être futur |

### Le lot L12 — couche IA, estimation de repas, import Apple (`v0.13.0`)

**Ce qui est vérifié** : sans clé, aucune fonctionnalité n'est bloquée. L'état répond en
disant ce qui manque, les endpoints IA refusent avec un code du catalogue, et la saisie
manuelle comme la validation d'un import écrivent normalement.

**`IA-02` a été passé pour de bon le 2026-07-31** : 365 modèles publiés, 15 retenus,
6 vision. Le filtrage tient — et il a fallu le corriger deux fois, voir plus bas.

**Ce qui reste** : passer une vraie capture dans un vrai modèle. C'est la seule chose que
la simulation ne peut pas dire, et elle **demande un accord préalable**, chaque fois. Le
geste exact, et ce qui compte comme échec, sont au §1 de
[`verifications-manuelles.md`](verifications-manuelles.md).

**Le modèle configuré est payant, et c'est voulu.** `OPENROUTER_MODEL` vaut
`anthropic/claude-sonnet-5` : il passe en tête de cascade, il lit une capture bien mieux
qu'un 31B gratuit, et une analyse coûte de l'ordre d'un centime. Les gratuits sont le
repli. Vider le réglage suffit à revenir au tout-gratuit.

### Ce que la couche IA a posé, et qui resservira

Trois lots l'attendaient — le planning (`PLAN-03`), les objectifs (`GOAL-*`), le bilan
hebdomadaire (`IA-08`). **Les trois sont livrés, plus un quatrième qui n'était pas prévu :
l'assistant conversationnel (`IA-09`).** Aucun n'a eu de modèle à choisir ni de cascade à
écrire. La couche a tenu telle quelle sur cinq usages, dont quatre qu'elle n'avait pas vus
venir — et le cinquième, la conversation, ne lui a pas demandé une ligne de plus.

| Pièce | Où | Ce qu'elle fait |
|---|---|---|
| `AiService.ask_json` | `domains/ai/service.py` | consigne + image → dictionnaire, ou une erreur qui distingue quota et panne |
| `ModelCatalogue` | `domains/ai/service.py` | modèles gratuits découverts, filtrés, classés, mémorisés une heure |
| `first_json_object` | `domains/ai/extract.py` | lit un JSON dans de la prose, sans jamais compléter ce qui manque |
| `prepare_data_url` | `domains/ai/images.py` | 1024 px, JPEG, data URL |
| `AiServiceDep` | `domains/ai/deps.py` | sans clé, l'endpoint ne s'exécute pas — rien à vérifier soi-même |
| `AiBlock`, `Stepper proposed` | `components/ui/primitives.tsx` | dire à l'écran qu'une valeur est proposée, et la laisser corriger |
| `tests/fake_openrouter.py` | tests | scénariser un `429`, un JSON tronqué, un catalogue sans vision |

### Les règles que ce lot a ajoutées aux invariants

**Une valeur proposée n'est pas une mesure**, et l'écran doit le montrer. C'est « aucune
valeur inventée à l'écran » appliqué à l'estimation — en plus difficile, parce qu'un
chiffre inventé par un modèle est *plausible*, là où un zéro se repère.

**Hors bornes, on écarte ; on ne ramène pas à la borne.** 4000 g de protéines ramenés à
500 g donneraient une valeur fausse d'apparence honnête. Le champ reste vide.

**Le modèle lit, il ne convertit pas.** Miles, `28:45`, dates relatives : une seule
grammaire, celle de `app/core/parsing.py`, la même que pour une saisie au clavier.

**Une réponse tronquée ne rend rien.** Compléter des accolades manquantes reviendrait à
inventer les valeurs qu'elles contenaient.

### Ce que la passe réelle a appris, et qu'il faut retenir

Deux entrées du vrai catalogue passaient le filtre à tort, et **aucune simulation
n'aurait eu l'idée de les écrire** :

| Entrée | Ce qu'elle annonce | Pourquoi elle passait |
|---|---|---|
| `openrouter/auto` | `pricing.prompt = "-1"` | sentinelle « variable » : le routeur facture le tarif du modèle vers lequel il route. Le test était « pas strictement positif » |
| `google/lyria-3-clip-preview` | `output_modalities = ["text", "audio"]` | générateur de musique. Le test était « `text` est parmi les sorties » |

Un prix doit désormais valoir **exactement zéro**, et un modèle retenu doit rendre **du
texte et rien d'autre**. Le catalogue passe de 22 retenus à 15, de 10 vision à 6.

C'est la même leçon que le §6 répète depuis trois lots : la batterie simulée était verte
sur les deux. **Une entrée réelle a des formes que personne n'invente.**

### Ce qui reste ouvert dans le lot

- **Aucune vraie capture n'est passée dans un vrai modèle.** Toute la chaîne est couverte
  contre le double ASGI ; ce qu'il ne peut pas dire, c'est si un modèle lit réellement un
  écran Apple Fitness. C'est la moitié de DoD qui manque.
- **Le HEIC n'est pas analysable** — écart assumé. Pillow demanderait `pillow-heif` et sa
  chaîne native ; une photo au format iPhone par défaut reçoit un refus explicite et le
  repas s'enregistre normalement.

### Ce que L11 laisse en place, toujours valable

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
le téléphone et consigner une vraie série est le test qui manque** — et depuis le L13,
**viser un jour dans le calendrier du mois** est le second.

Et `L17-07` n'est pas clos : **sept écrans sur dix** n'ont pas eu la passe. `/planning` et
`/objectif` l'ont reçue en même temps que leur livraison, et chacune a produit des défauts
qu'aucun test du lot n'avait vus — un lien à 17 px et un calendrier repoussé sous le pli
pour le premier, un anneau affichant « 0% » sur un avancement indéterminé pour le second.
La grille du planning est par ailleurs la **cible la plus serrée du
projet** : 47,1 × 44 px à 390 px, sans un pixel à céder.

**Aucune grille n'a encore un an d'historique réel derrière elle.** Les pistes ayant été
amorcées le jour de la livraison, `HEAT-07` les rend `off` sur tout le passé et le taux de
respect vaut `null` — comportement correct, mais qui laisse le rendu d'une grille dense et
le calcul des longues séries vérifiés sur données simulées uniquement. **Rouvrir
`/assiduite` dans un mois est le vrai test de ce lot.**

> **Trois taux distincts, et ils le resteront.** `AGG-03` mesure l'assiduité de *suivi* —
> a-t-on relevé quelque chose ce jour-là. `HEAT-27` mesure le respect d'un *engagement* de
> cadence — « deux fois par semaine ». `PLAN-06` mesure le respect d'un *rendez-vous* — la
> séance prévue mardi a-t-elle eu lieu mardi.
>
> Trois questions différentes, trois algorithmes. Les fusionner donnerait un chiffre dont
> personne ne saurait dire ce qu'il compte.
>
> **Et `GOAL-04` n'est pas le quatrième.** Il ne mesure pas un respect mais un
> *avancement* : la distance parcourue entre le chiffre qu'on avait et celui qu'on s'est
> fixé. Il se borne à `[0, 1]` comme les trois autres, il s'affiche comme eux en
> pourcentage, et c'est exactement ce qui rend la confusion tentante.
