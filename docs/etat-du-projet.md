# État du projet — reprise à froid

Document d'entrée. À lire en premier pour reprendre le développement de **Metric** sans
contexte préalable — que ce soit dans trois mois ou dans une nouvelle session.

**Version courante : `v0.8.0`** · huit lots livrés sur dix-huit.

| Mesure | Valeur *(vérifiée le 2026-07-27)* |
|---|---|
| Tests backend | **381**, dont 35 de sécurité sur le service des photos |
| Tests frontend | **86** |
| Qualité | `ruff`, `mypy --strict`, `eslint`, `tsc --noEmit` sans avertissement |
| Build de production | 109 ko gzip |

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

**C'est la section qui compte.** Huit lots les ont suivis ; les casser produirait des
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

Le détail de chaque lot — tâches cochées, écarts assumés, décisions — est dans
[`ROADMAP.md`](../ROADMAP.md). Le journal des changements avec le *pourquoi* est dans
[`CHANGELOG.md`](../CHANGELOG.md).

### Écrans disponibles

`/connexion` · `/` tableau de bord *(encore une page d'attente, le vrai arrive au L08)* ·
`/corps` · `/activite` · `/routine` · `/nutrition` · `/_kitchen-sink` *(référence de
charte, publique)*

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
├── storage/           WebDAV, cache, dépôt CSV typé
└── domains/<nom>/     models · schemas · service · router
                       (activity a un `stats.py` de plus)

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

### Trois décisions ouvertes, sans urgence

- **Supprimer un repas ne supprime pas sa photo** (L07). Choix assumé : l'effacer d'un clic
  ferait perdre un souvenir qu'aucune annulation ne rendrait. À inverser si vous préférez.
- **`/_kitchen-sink` est publique** (L03) : aucune donnée utilisateur, consultable sans
  session, vérifiable par capture automatisée.
- **`MIN_LENGTH` du mot de passe abaissé à 6** dans `hash_password.py`. C'est l'unique
  porte d'entrée vers un an de données personnelles, sans second facteur.

---

## 7. Prochain lot — L08

**Réglages & agrégats du tableau de bord.** Il ferme le jalon II.

- `AGG-01` — un seul endpoint rendant tous les indicateurs de synthèse. C'est la raison
  d'être du lot : dix appels parallèles au chargement d'un écran signifieraient dix
  lectures Nextcloud.
- `AGG-02` — totaux d'entraînement, série des 8 semaines, répartition courses / muscu.
- `AGG-03` — série d'assiduité toutes sources confondues, avec la règle « hier reste
  valide tant que la journée en cours n'est pas terminée ».
- `AGG-04` — séries temporelles génériques : un seul contrat réutilisé pour le poids, les
  mensurations, le volume hebdomadaire, la charge par exercice, l'hydratation.
- Les réglages deviennent **éditables** ; `app/domains/app_settings/` est aujourd'hui en
  lecture seule.
- Le vrai tableau de bord remplace la page d'attente.

> `AGG-03` et `HEAT-27` sont **deux algorithmes distincts et le resteront** : le premier
> mesure l'assiduité de suivi, le second le respect d'un engagement. Ne pas les fusionner.

Ensuite vient le jalon III — le moteur d'assiduité, cœur du projet. `app/core/cadence.py`
est déjà en place et n'attend que son évaluateur.
