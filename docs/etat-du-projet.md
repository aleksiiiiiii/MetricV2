# État du projet — reprise à froid

Document d'entrée. À lire en premier pour reprendre le développement de **Metric** sans
contexte préalable — que ce soit dans trois mois ou dans une nouvelle session.

**Version courante : `v0.10.0`** · dix lots livrés sur dix-huit. Le jalon II est clos et
le jalon III — l'assiduité, cœur du projet — a commencé.

| Mesure | Valeur *(vérifiée le 2026-07-28)* |
|---|---|
| Tests backend | **492**, dont 35 de sécurité sur le service des photos |
| Tests frontend | **106** |
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

**C'est la section qui compte.** Dix lots les ont suivis ; les casser produirait des
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

### Un fichier de configuration ne fait jamais tomber un écran

Réglages, pistes, cadences, jours neutralisés : ces fichiers sont **destinés** à être
ouverts dans un tableur. Une cellule vide, un nombre illisible, une source mal
orthographiée, un accent inventé y sont des possibilités normales — pas des incidents.

Chaque lecture typée retombe donc sur son propre repli, et l'erreur reste locale : une
piste abîmée rend une grille vide, elle n'emporte pas les huit autres. La règle est née
d'un vrai défaut au L08, où une cellule vide de `settings.csv` faisait tomber tous les
écrans à la fois.

Les fichiers de **mesure**, eux, ne suivent pas cette règle : une ligne de pesée illisible
est une erreur qu'il faut voir (`StorageSchemaError`). On ne devine pas une donnée.

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
                       (activity a un `stats.py` de plus, heatmap un `sources.py` ;
                        aggregates n'a pas de `models.py` — c'est le seul domaine
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

### Une ligne dans `.env`

`NEXTCLOUD_URL` pointe sur la racine du site au lieu du point d'accès WebDAV.
**L'application ne peut donc rien écrire.** La forme correcte a été vérifiée contre
l'instance réelle — écriture, relecture identique, `304` honoré sur lecture
conditionnelle :

```
NEXTCLOUD_URL=https://nextcloud.aleksi.systems/remote.php/dav/files/MetricsApp
```

Ensuite `make console` → `storage` confirme en trois secondes.

Tant que cette ligne n'est pas corrigée, **rien n'a jamais été exercé contre l'instance
réelle** — le lot L08 compris. Le tableau de bord ouvre neuf fichiers par affichage : le
comptage des lectures est vérifié par test, la latence réelle ne l'est pas.

### Quatre décisions ouvertes, sans urgence

- **Supprimer un repas ne supprime pas sa photo** (L07). Choix assumé : l'effacer d'un clic
  ferait perdre un souvenir qu'aucune annulation ne rendrait. À inverser si vous préférez.
- **`heatmap_metric` n'est pas contraint à une liste fermée** (L08). Les pistes
  d'assiduité sont des données utilisateur créées au L09 ; figer aujourd'hui un
  vocabulaire que ce lot remplacera obligerait à rejeter une piste légitime. À resserrer
  une fois les pistes en place.
- **`/_kitchen-sink` est publique** (L03) : aucune donnée utilisateur, consultable sans
  session, vérifiable par capture automatisée.
- **`MIN_LENGTH` du mot de passe abaissé à 6** dans `hash_password.py`. C'est l'unique
  porte d'entrée vers un an de données personnelles, sans second facteur.

---

## 7. Prochain lot — L10

**Moteur `HEAT` : calcul, cadences, statistiques.** C'est le lot où la justesse compte le
plus, et le seul du projet à porter une exigence de couverture (≥ 95 % sur la machine à
états).

Tout ce qui le paramètre existe déjà. Ce qui manque est le **jugement** :

- `HEAT-05` — la machine à états du jour : `off` / `missed` / `done` / `bonus`. Quatre
  états et non cinq niveaux, parce qu'une grille majoritairement `off` n'est pas un échec.
- `HEAT-04` — validation `agrégat ≥ seuil`, le seuil venant toujours de la piste.
- `HEAT-09` → `HEAT-13` — les cinq cadences. La fenêtre `window` est **glissante** et non
  une parité de calendrier : lundi/mercredi/vendredi et mardi/jeudi/samedi sont deux
  rythmes également corrects.
- `HEAT-27` — la série cadence-consciente, à ne pas confondre avec `AGG-03`. Les jours
  `off` et neutralisés y sont **transparents** : une whey prise un jour sur deux pendant
  trois mois donne une série de trois mois, pas de deux jours.
- `L10-03` — l'ordre de priorité des règles neutralisantes, qui est la partie la plus
  facile à se tromper : neutralisé > antérieur à la création > jour en cours > cadence.

### Ce que L09 laisse en place

| Pièce | Où |
|---|---|
| `TrackService.cadence_at(track_id, jour)` | la règle qui s'appliquait à une date passée |
| `TrackService.neutralised(track_id)` | les plages à traiter en `off`, globales comprises |
| `sources.daily_values(store, source, filtre)` | l'agrégat quotidien, un nombre par jour |
| `TrackRow.created` | la borne de non-rétroactivité (`HEAT-07`) |
| `TrackRow.levels` et `binary` | de quoi convertir l'agrégat en niveau 1–4 (`HEAT-15`) |

Le moteur n'aura donc à décider que d'une chose : **l'état d'un jour**. Tout ce dont il a
besoin pour le faire lui est servi.

### Deux pièges déjà repérés

- **`per_week` ne produit jamais de `missed` au jour** (`HEAT-11`) : c'est la semaine qui
  porte un statut. Un rouge quotidien sur une piste hebdomadaire serait un contresens.
- La plage par défaut (**D6**) n'est pas « 371 jours se terminant aujourd'hui » : c'est du
  lundi d'il y a 52 semaines au dimanche de la semaine courante. Les deux conditions du
  backlog ne peuvent être vraies ensemble sauf un dimanche, et l'alignement de grille
  prime sur la borne exacte.

> `AGG-03` et `HEAT-27` sont **deux algorithmes distincts et le resteront** : le premier
> mesure l'assiduité de suivi, le second le respect d'un engagement. Ne pas les fusionner.
