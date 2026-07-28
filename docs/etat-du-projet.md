# État du projet — reprise à froid

Document d'entrée. À lire en premier pour reprendre le développement de **Metric** sans
contexte préalable — que ce soit dans trois mois ou dans une nouvelle session.

**Version courante : `v0.11.0`** · onze lots livrés sur dix-huit. Le moteur d'assiduité —
le cœur du projet — calcule ; il ne lui manque que ses écrans.

| Mesure | Valeur *(vérifiée le 2026-07-28)* |
|---|---|
| Tests backend | **594**, dont 35 de sécurité sur les photos et **102 sur le moteur d'assiduité** |
| Tests frontend | **106** |
| Couverture du moteur | **100 %** de `heatmap/engine.py` |
| Qualité | `ruff`, `mypy --strict`, `eslint`, `tsc --noEmit` sans avertissement |
| Build de production | 112 ko gzip |

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

Le détail de chaque lot — tâches cochées, écarts assumés, décisions — est dans
[`ROADMAP.md`](../ROADMAP.md). Le journal des changements avec le *pourquoi* est dans
[`CHANGELOG.md`](../CHANGELOG.md).

### Écrans disponibles

`/connexion` · `/` tableau de bord · `/corps` · `/activite` · `/routine` · `/nutrition` ·
`/reglages` · `/_kitchen-sink` *(référence de charte, publique)*

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
└── domains/<nom>/     models · schemas · service · router
                       (activity a un `stats.py` de plus ; heatmap a `engine.py`
                        — pur —, `grids.py` — la couture — et `sources.py` ;
                        aggregates n'a pas de `models.py`, c'est le seul domaine
                        sans fichier à lui)

frontend/src/
├── components/ui/     bibliothèque de la charte
├── features/<nom>/    types + appels d'un domaine, aucun calcul
├── lib/               api, auth, query, format, cx
└── routes/            un écran par domaine
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

### La chaîne complète tourne enfin

`NEXTCLOUD_URL` a été corrigé le 2026-07-28 : il pointe sur le point d'accès WebDAV et non
plus sur la racine du site. L'API démarre avec `storage_configured: true`, et
`make dev` sert les deux moitiés.

**Ce que cela change** : les lots L01 à L10 ont tous été validés contre un double WebDAV en
mémoire, jamais contre l'instance réelle. Cette réserve tombe en partie — l'application
lit et écrit vraiment — mais **la latence n'a pas été mesurée**. Le tableau de bord ouvre
neuf fichiers par affichage, une grille d'assiduité en ouvre autant sur 371 jours. C'est
précisément ce que le cache serveur du lot L11 doit régler, et il faudra le mesurer, pas
le supposer.

`make check-storage` écrit puis relit un fichier de diagnostic sur Nextcloud et confirme la
chaîne de bout en bout. Il n'a pas encore été lancé.

### Quatre décisions ouvertes, sans urgence

- **Supprimer un repas ne supprime pas sa photo** (L07). Choix assumé : l'effacer d'un clic
  ferait perdre un souvenir qu'aucune annulation ne rendrait. À inverser si vous préférez.
- **`heatmap_metric` n'est pas contraint à une liste fermée** (L08). Les pistes existent
  depuis le L09 : le réglage peut désormais être resserré sur leurs identifiants.
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

### Une dette d'ergonomie, à traiter au L11

L'écran Activité cache son parcours principal. Le panneau de saisie des charges n'existe
que si une séance est **active** ; le catalogue d'exercices, lui, est toujours visible avec
son formulaire. Le regard tombe donc sur le catalogue, qui ne prend aucun chiffre, alors
que l'ordre réel est : déclarer l'exercice → créer la séance → consigner les charges.

Le lot L11 touche déjà aux écrans : c'est le moment de rendre cet ordre visible, par
exemple avec un journal toujours affiché et un sélecteur de séance plutôt qu'un panneau
conditionnel.

---

## 7. Prochain lot — L11

**Heatmaps & réglage des pistes.** Il ferme le jalon III : le moteur calcule, il lui
manque ses écrans.

Tout le calcul existe et est couvert à 100 %. Ce qui reste est de l'exposition :

- `L11-01` → `L11-03` — les trois endpoints de la spec §8 : grille d'une piste, lecture
  multi-pistes en une requête (`HEAT-25`), détail d'un jour (`HEAT-29`). Le service
  `GridService` rend déjà exactement ces trois choses ; il n'y a qu'à les publier.
- `L11-04` — **cache serveur des grilles** (`HEAT-33`), clé = piste + plage + version de
  config + ETag des sources. C'est le seul vrai travail d'ingénierie du lot : neuf pistes
  × 371 jours ne doivent pas relire Nextcloud à chaque affichage.
- `L11-06` → `L11-09` — l'écran. La contrainte à ne pas rater : **`off` doit être
  visuellement distinct de `missed`**. Une grille majoritairement `off` ne doit pas se
  lire comme un échec, sans quoi tout le travail du moteur est annulé à l'affichage.
- `L11-10` — le réglage des pistes, avec l'avertissement de recalcul rétroactif.

### Ce que L10 laisse en place

| Pièce | Où |
|---|---|
| `evaluate(...)` | la machine à états, pure et testable sans stockage |
| `GridService.grid` / `.grids` / `.day` | les trois lectures de la spec §8, prêtes à publier |
| `default_range(today)` | 53 colonnes pleines alignées sur le lundi (**D6**) |
| `Grid.weeks` | les statuts hebdomadaires, `None` hors `per_week` |

### Une dette nommée, à solder au L11

`HEAT-20` et la décision **D4** demandent d'annoncer l'ampleur d'un changement de seuil —
« 34 jours passeraient de validé à manqué » — **avant** de le valider. Le lot L09 n'a
livré que l'avertissement, faute de moteur. Le moteur existe désormais : le compte
s'obtient en évaluant la grille deux fois, avec l'ancien seuil et le nouveau, et en
comparant les états. `TrackSaved.recalculated_history` est déjà là pour le porter.

### Deux pièges de rendu, déjà repérés

- **Les jours `off` de la semaine en cours sont dans le futur.** La plage par défaut va
  jusqu'au dimanche : les cellules après aujourd'hui existent et valent `off`. Les peindre
  comme les autres `off` est correct ; les peindre comme des trous ne le serait pas.
- **`per_week` ne rend jamais de `missed` au jour.** Le rouge, sur ces pistes, se pose sur
  la **semaine** (`Grid.weeks`). Un écran qui chercherait des jours rouges y verrait un
  sans-faute permanent.

> `AGG-03` et `HEAT-27` sont **deux algorithmes distincts et le resteront** : le premier
> mesure l'assiduité de suivi, le second le respect d'un engagement. Ne pas les fusionner.
