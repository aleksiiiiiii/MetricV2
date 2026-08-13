# PWA & rappels — plan du lot L15

Objectif : que Metric **s'installe** sur un iPhone et **rappelle** ce qui n'a pas été noté,
application fermée. Ce document est le plan d'exécution ; il se lit avec le §2 de
[`etat-du-projet.md`](etat-du-projet.md), dont il ne touche aucun invariant, et avec
[`front.md`](front.md), qui reste la carte du front.

Six tâches, `L15-01` → `L15-06`, spec métier en section 13 de `backlogV2.md` (`NOT-01` à
`NOT-03`).

---

## 1. Ce que ce lot n'est pas

**Ce n'est pas `L17-01`.** Un service worker et Web Push exigent un contexte sécurisé.
`localhost` en est un ; `172.20.10.10` non ; et iOS n'accepte Web Push qu'une fois
l'application **ajoutée à l'écran d'accueil**. Le développement se fait donc sur
`localhost`, et la vérification finale par un **tunnel HTTPS temporaire** sur un vrai
iPhone.

Le tunnel est un outil de vérification, pas un déploiement. Rien n'est conteneurisé, aucun
reverse-proxy n'est touché, `L17-01` reste entier.

> **Et le déploiement ne passera pas par Docker.** Le HTTPS durable viendra de **Nginx
> Proxy Manager**, en amont de l'application : ce lot n'a donc ni pile à conteneuriser ni
> certificat à gérer. Ce qu'il doit, c'est être *proxifiable* — deux hôtes, des en-têtes
> transmis, et `/api` jamais mis en cache par le proxy. `make console` → `proxy` porte la
> liste, et `docker-compose.yml` reste ce qu'il est depuis le L00 : écrit, non exécuté.

**Ce n'est pas un écran de plus.** Les réglages de rappel sont une section de `/reglages`.
La barre de navigation a été tranchée au L14b — cinq cibles en bas, le reste dans la
feuille « Plus » — et elle ne se rouvre pas ici.

**Ce n'est pas un mode hors-ligne.** La file d'attente des écritures sans réseau est
`DATA-02`, donc `L16`. Ici, sans réseau, l'application s'ouvre et dit qu'elle ne sait rien.

---

## 2. La décision qui gouverne tout le reste

> **Le service worker met en cache la coquille, jamais les données.**

Un écran servi depuis le cache avec les chiffres d'hier est une **valeur inventée à
l'écran**, au sens le plus littéral de l'invariant — et le pire cas possible, parce que la
page a l'air parfaitement normale. Il n'y a ni tiret, ni « chargement », ni erreur : il y a
un poids, et il est faux.

| Ce qui est demandé | Stratégie | Pourquoi |
|---|---|---|
| Tout ce qui commence par `/api` | **réseau, sans repli** | c'est une mesure |
| Une navigation | coquille en cache, rafraîchie derrière | la coquille ne porte aucun chiffre |
| `/assets/*`, polices, icônes, manifeste | cache d'abord | noms empreintés, donc immuables |
| Une autre origine | réseau, jamais mis en cache | ce n'est pas à nous |

Pas de `stale-while-revalidate` sur une mesure. Sur la **coquille**, si : un document HTML
de 2 ko qui ne contient aucun chiffre n'est pas une mesure, et le rafraîchir derrière est
ce qui fait qu'un déploiement se voit au chargement suivant plutôt qu'au troisième.

**La décision de stratégie s'écrit dans une fonction pure de l'URL** —
`strategyFor(url, { navigation })` —, testable sans monter de service worker. Même parti
pris que `heatmap/engine.py` : ce qui juge ne lit rien. Une règle de cache écrite ailleurs
que dans cette fonction échapperait à sa batterie, et son symptôme serait un chiffre
d'hier affiché comme celui d'aujourd'hui.

---

## 3. Ce qu'un rappel a le droit de dire

> **Un rappel dit ce qui n'est pas noté, pas ce qui n'a pas été fait.**

« Tu n'as pas bu aujourd'hui » est une **affirmation fausse** : l'application sait
seulement que rien n'a été consigné. C'est « aucune valeur inventée » appliqué à une
notification, et c'est le cas difficile — parce qu'une notification est lue en trois mots,
sur un écran verrouillé, sans contexte et sans moyen de vérifier.

| Interdit | Retenu |
|---|---|
| « Tu n'as pas bu aujourd'hui » | « Hydratation — rien de noté » |
| « Tu as sauté ta séance » | « Séance prévue — rien de noté » |
| « Tu as oublié la créatine » | « Suppléments — créatine, whey pas encore notées » |
| « 0 repas aujourd'hui » | « Repas — rien de noté depuis ce matin » |

Le titre porte le cadrage, le corps porte le détail. Un chiffre **relevé** peut être cité
tel quel — « 750 ml notés sur 2000 » est une mesure, elle est vraie — ; c'est l'**absence**
qu'on n'a pas le droit de transformer en affirmation sur l'utilisateur.

### Le corollaire de conception

Un rappel qui arrive au mauvais moment se désinstalle en un geste et ne revient jamais.
C'est la fonctionnalité la plus facile à rendre nuisible du projet entier. Trois garde-fous
en découlent, et ils sont dans le code, pas dans l'intention :

1. **Le défaut est le silence.** Aucun rappel n'est configuré à l'installation. Chaque
   créneau est un choix explicite. Un réglage illisible vaut « éteint », jamais « à 3 h ».
2. **Un rappel par créneau et par jour.** Jamais deux. La mémoire est un fichier, pas une
   variable — un redémarrage ne renvoie rien.
3. **Une fenêtre de rattrapage bornée à 60 minutes.** Un serveur redémarré à 20 h 05
   délivre le rappel de 20 h ; redémarré à 23 h, il ne le délivre pas. Perdre un rappel
   coûte moins qu'en recevoir un la nuit.

### Les rappels lisent les fichiers existants

`supplements/schedule.csv` porte déjà `time`, `frequency` et `active` ;
`SupplementService.checklist(day)` dit déjà ce qui est dû et ce qui est pris. **Un rappel
de suppléments ne sonne que pour ce qui reste.** On n'écrit pas un second calendrier — il
divergerait du premier au premier changement, et c'est exactement la raison d'être de la
décision **D3**.

> **Attention** : la cellule `time` de ce fichier est **vide par conception**, et c'est
> elle qui a fait tomber le tableau de bord entier en `502` au premier usage réel. Tout
> nouveau fichier de ce lot est de la famille *planning* : chaque colonne porte un défaut,
> et les dates comme les nombres s'annotent `CsvDate` / `CsvNumber`.

---

## 4. Les six tâches

### `L15-01` — Manifeste et icônes

**Le blocage réglé.** Le dépôt n'avait aucun visuel de marque : `components/ui/icons.tsx`
ne porte que des pictogrammes d'interface. La piste retenue est **la règle graduée**, que
`GuidelinesUI.html` nomme lui-même « motif signature » — le trait de 1 px que `.rule`
dessine entre chaque section, avec ses graduations tous les 16 px.

**Écart assumé, mesuré avant d'être décidé** : à 48 px sur un écran d'accueil, un trait de
1 px et des graduations de 5 px **disparaissent**. L'icône reprend donc le motif *à
l'échelle du pavé* — trait et graduations épaissis proportionnellement — et non le motif
copié à ses valeurs CSS. C'est le même motif ; ce ne sont pas les mêmes pixels.

Quatre fichiers, dessinés par un script reproductible et non à la main :

| Fichier | Taille | Pour |
|---|---|---|
| `icon-192.png` | 192 | manifeste, Android |
| `icon-512.png` | 512 | manifeste, écran de démarrage |
| `icon-maskable-512.png` | 512 | Android adaptatif — motif rentré dans le cercle sûr à 80 % |
| `apple-touch-icon.png` | 180 | iOS, qui ignore le manifeste et applique son propre masque |

Le manifeste ne doit **pas contredire** le script de thème d'`index.html` :
`background_color` et `theme_color` valent `--bg` du thème sombre, celui de `:root`.
`tokens.test.ts` vérifie déjà que les deux couleurs de ce script ne dérivent pas des
tokens ; il vérifiera les deux du manifeste de la même façon.

> **Pourquoi une seule couleur là où l'application en a deux.** Un manifeste ne porte
> qu'un `theme_color`, la balise `<meta name="theme-color">` en porte un par thème et
> **gagne** à l'exécution. Le manifeste ne décide donc que de l'écran de démarrage à
> l'installation. Le sombre est celui de la charte : c'est le bon défaut.

### `L15-02` — Service worker

```
frontend/src/sw/strategy.ts   PUR — l'URL → la stratégie. Aucune API de navigateur.
frontend/src/sw/index.ts      le worker : install, activate, fetch, push, notificationclick
frontend/src/lib/pwa.ts       l'enregistrement, côté application
```

Le worker est écrit en TypeScript et bâti par une **seconde configuration Vite**
(`vite.sw.config.ts`) vers `dist/sw.js`, sans empreinte dans le nom — un service worker
doit vivre à une adresse stable, à la racine de sa portée.

**Aucun `vite-plugin-pwa`, et c'est un écart au §0 du ROADMAP.** Le plugin apporte Workbox,
sa propre grammaire de stratégies, et un `sw.js` généré. Or la décision du §2 demande que
la stratégie soit une **fonction pure testable** : elle serait alors écrite dans la
configuration du plugin, c'est-à-dire nulle part où un test la voie. Le coût de l'écart est
d'écrire une trentaine de lignes de worker ; le bénéfice est que la règle qui protège les
mesures est vérifiée par la batterie.

### `L15-03` — VAPID et abonnement (`NOT-01`)

Nouveau domaine backend, au patron habituel :

```
backend/app/domains/notifications/
├── models.py      SubscriptionRow · SentRow          ← famille planning, tout défaut
├── schemas.py     PushStatus · SubscriptionPayload · RemindersView
├── reminders.py   PUR — ce qui est dû, et ce que ça DIT. Ni fichier, ni horloge
├── push.py        le transport : pywebpush chiffre, httpx2 envoie
├── scheduler.py   la boucle — horloge injectable, mémoire dans un fichier
├── service.py     abonnements, réglages, envoi
└── router.py      /api/notifications/*
```

Deux fichiers, tous deux famille *planning* :

| Fichier | Colonnes |
|---|---|
| `notifications/subscriptions.csv` | `id, created, endpoint, p256dh, auth, user_agent` |
| `notifications/sent.csv` | `date, kind, sent_at` |

**Sans clé VAPID, rien n'est bloqué.** C'est `IA-07` appliqué au push, et il y a deux
précédents à recopier plutôt qu'à réinventer : `AiStatus` (`domains/ai/schemas.py`) et
`SubscriptionInfo` (`domains/planning/schemas.py`). Même forme, pour la même raison — un
écran ne demande jamais « la clé est-elle configurée ? » à sa propre configuration, il ne
la connaît pas. Il le demande au serveur, qui répond **`200` dans les deux cas** avec un
booléen et la phrase à afficher, en français.

Une clé absente est un **état**, pas une panne.

**Le chiffrement n'est pas écrit à la main.** `aes128gcm` et l'échange ECDH ne sont pas un
endroit où l'artisanat se justifie, et le projet aime pourtant les dépendances rares — CDP
piloté sans Playwright, pas de `ws`. `pywebpush` chiffre (`WebPusher.encode`), `py_vapid`
signe l'en-tête, et **`httpx2` envoie** : le client synchrone de `pywebpush` reposerait sur
`requests` au milieu d'une application asynchrone, et rendrait la doublure de test
impossible sans détourner un module tiers.

**La garde de `AUTH-05` tient.** Toutes les routes de push sont dans le groupe protégé. Le
flux `.ics` est la seule exception du projet et le §2 dit qu'une deuxième n'y aurait pas
droit ; un abonnement push se fait depuis l'application connectée, il n'en a aucun besoin.

### `L15-04` — Ordonnanceur (`NOT-02`)

L'ordonnanceur vit dans le **lifespan**, avec une **horloge injectable**. Le patron existe
déjà : `ModelCatalogue` prend `clock: Callable[[], float] = time.monotonic`, et c'est ce
qui rend sa mémorisation d'une heure testable en trois lignes.

Deux méthodes, et le découpage est ce qui empêche `L15-06` de devenir un test qui dort :

* `tick()` — **une passe**, appelable directement par un test, avec un instant fourni ;
* `run()` — la boucle, qui ne fait qu'appeler `tick()` et attendre.

Le **jour vient de `app/core/dates.py`**, jamais d'UTC. Un rappel de 20 h est un rappel de
20 h à Paris, et la frontière du jour est celle de l'horloge de l'utilisateur — la même que
pour une prise à 23 h 30.

L'ordonnanceur **se souvient de ce qu'il a envoyé** dans `notifications/sent.csv`, sinon un
redémarrage renvoie tout. Un rappel par créneau et par jour.

### `L15-05` — Réglages (`NOT-03`)

Dans `settings.csv`, **pas dans un nouveau fichier**. `app_settings/service.py` les réserve
déjà : son commentaire sur `TYPED_KEYS` dit que le fichier peut porter les clés
`reminders_*` et qu'elles sont **conservées à l'écriture**.

| Clé | Valeur |
|---|---|
| `reminders_supplements` | `HH:MM`, ou vide |
| `reminders_hydration` | `HH:MM`, ou vide |
| `reminders_meals` | `HH:MM`, ou vide |
| `reminders_workout` | `HH:MM`, ou vide |

**Une seule cellule par type, et la cellule vide est l'extinction.** Deux clés — une
activation, un horaire — doubleraient les lignes du fichier pour ne gagner que de retenir
une heure qu'on vient d'éteindre. Une cellule vide qui *veut dire quelque chose* est déjà
le cas de `plan.csv`, dont la colonne `time` est facultative par conception.

Un horaire illisible vaut **éteint**. C'est le seul repli acceptable : une valeur par
défaut réveillerait quelqu'un.

### `L15-06` — Tests

Aucun envoi réel dans `make check`. Une doublure de service push, sur le modèle de
`tests/fake_openrouter.py` et `tests/fake_webdav.py`.

| Ce qui est vérifié | Où |
|---|---|
| La stratégie ne met **jamais** `/api` en cache | `sw/strategy.test.ts` |
| Sans clé VAPID, l'état répond `200` et dit ce qui manque | `test_notifications.py` |
| Sans clé VAPID, l'abonnement refuse avec un **code** du catalogue | idem |
| Un abonnement expiré (`404`/`410`) est **retiré** du fichier | idem |
| Deux passes du même créneau n'envoient qu'une fois | `test_reminders.py` |
| Un redémarrage ne renvoie pas ce que `sent.csv` porte déjà | idem |
| Un rappel de suppléments ne cite que ce qui **reste** | idem |
| Une cellule `time` vide de `schedule.csv` ne fait rien tomber | idem |
| Le texte ne dit jamais ce qui n'a pas été **fait** | idem |
| La fenêtre de rattrapage s'arrête à 60 minutes | idem |

**Et ce que la batterie ne peut pas dire** : qu'un rappel arrive vraiment, application
fermée, sur un vrai iPhone, derrière un vrai HTTPS. Cette moitié de DoD va dans
[`verifications-manuelles.md`](verifications-manuelles.md), au fil de l'écriture.

---

## 5. Ce que ce lot ne touche pas

Les invariants du §2 de [`etat-du-projet.md`](etat-du-projet.md) tiennent, sans exception.
Trois méritent d'être nommés parce que ce lot les approche de près :

- **Aucune valeur inventée à l'écran** — et un écran servi du cache avec les chiffres
  d'hier en serait une. D'où le §2 de ce document.
- **Aucune valeur inventée dans une notification** — et « tu n'as pas bu » en serait une.
  D'où le §3.
- **Le jour vient du serveur, en heure locale.** Un ordonnanceur est précisément l'endroit
  où l'on écrirait `datetime.utcnow()` sans y penser.

Et deux choses que les lots précédents laissent, qui resservent telles quelles :
`index.html` porte déjà `viewport-fit=cover`, `apple-mobile-web-app-capable`, le titre
d'écran d'accueil et un `theme-color` résolu avant la première peinture ; `--safe-t`,
`--safe-b` et `--tabbar` existent depuis la refonte mobile, et la barre d'onglets tient
déjà compte de la zone sûre du bas en mode autonome.

---

## 6. Ordre d'exécution

| # | Portée | Risque |
|---|---|---|
| 1 | Icônes, manifeste, `index.html` | nul — des fichiers statiques |
| 2 | `sw/strategy.ts` + sa batterie, puis le worker | faible — la règle est testée avant d'être branchée |
| 3 | Domaine `notifications` : modèles, schémas, `push.py`, service, routes | moyen |
| 4 | Réglages `reminders_*` | faible |
| 5 | `reminders.py` pur, puis `scheduler.py`, puis le lifespan | moyen — c'est là que vit le texte des rappels |
| 6 | Front : section de `/reglages`, abonnement navigateur | faible |
| 7 | `make check`, puis **regarder les écrans** | — |

Sur les cinq derniers lots, la moitié des défauts sont sortis en regardant la page, et zéro
de la batterie. L'étape 7 n'est pas une formalité de fin.
