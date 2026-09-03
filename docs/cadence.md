# Cadence Tabata — feuille de route

Metric fabrique des séances ; Cadence Tabata les exécute. Le pont entre les deux est une
**URL**, et rien d'autre : pas d'API, pas de compte, pas de base partagée. Toute la
difficulté du lot tient dans cette phrase — un lien est un objet fragile, il s'échappe mal,
il se borne mal, et **personne ne saura jamais** qu'il a été suivi jusqu'au bout.

Le format est spécifié dans [`llms.txt`](../llms.txt), version 1, déclarée stable. Ce
document ne le recopie pas : il dit ce que Metric en fait.

---

## 1. Les décisions prises

Toutes arbitrées avant écriture. Elles sont ici pour être relues, pas pour être rediscutées
en cours de route.

| | Décision | Conséquence |
|---|---|---|
| **D1** | L'adresse de Cadence est un **réglage**, `cadence_base_url` dans `settings/settings.csv` | Sans elle, aucun lien n'existe — et l'écran le dit au lieu d'en inventer un |
| **D2** | ~~Deux mondes séparés~~ — **renversée le 24 août** : un tabata est du sport, il entre dans l'ancien système | Chaque exercice de circuit porte un groupe musculaire, et rejoint `exercises.csv` au premier « fait » |
| **D3** | « Je l'ai fait » écrit une **séance et ses séries** | `workouts.csv` type `HIIT` `source: cadence`, plus une ligne de journal par exercice |
| **D4** | La durée est **estimée puis modifiable** | L'estimation est une proposition, jamais une mesure — §4 |
| **D5** | Le planning porte le **lien dans sa note** | Le raccourci, pas la référence. Ce que ça coûte est au §7 |
| **D6** | La complétion reste **déclarative** | Cadence n'est pas modifiée, aucun retour, aucun rappel |
| **D7** | Le lien se construit **côté serveur**, dans un module pur | Ni le client ni le modèle n'assemblent une URL — §3 |

### Le seul point où j'ai tranché à ta place — D3

Tu as répondu « pour un exercice de 30 s on met −1 » à une question qui portait sur
`exercise_log.csv`. Ça ne peut pas y aller, et pour deux raisons mesurées dans le code :

- `Reps = Annotated[int, Field(ge=1, le=200)]` dans
  [`core/validation.py:92`](../backend/app/core/validation.py#L92). Un `−1` est refusé. Le
  laisser passer voudrait dire desserrer une borne **partagée avec la saisie manuelle** :
  une faute de frappe à `−1` entrerait alors dans le journal de charge.
- `ExerciseLogRow` exige `exercise_id` et `muscle_group`
  ([`models.py:168`](../backend/app/domains/activity/models.py#L168)). D2 dit qu'un exercice
  Cadence n'en a ni l'un ni l'autre. On écrirait deux colonnes vides dans un fichier
  décrit comme « strict — c'est une mesure ».

**Donc `−1` reste, mais dans le fichier de Cadence.** Il y désigne exactement ce que la
grammaire de `llms.txt` appelle le suffixe `s` : *cet exercice est au temps, il n'a pas de
répétitions*. C'est le même genre de sentinelle documentée que `weight_kg = 0 = poids du
corps`, et elle a le même mérite — une cellule qui **dit** quelque chose, là où une cellule
vide laisse deviner.

Si tu voulais vraiment que les tabatas comptent dans le volume par groupe musculaire, c'est
D2 qu'il faut rouvrir, pas D3 : il faudrait choisir un groupe musculaire par exercice à la
création. C'est un lot en soi, il n'est pas dans celui-ci.

---

## 2. Les deux fichiers

```
activity/circuits.csv            id · name · rounds · round_rest_s · created · note
activity/circuit_exercises.csv   circuit_id · position · name · duration_s · reps · rest_s
```

**Pourquoi `circuits` et pas `workouts`.** `workouts.csv` décrit ce qui **a eu lieu** : il
porte une date, une durée réelle, un RPE. Un circuit n'a pas de date — c'est un patron,
il se rejoue. Mettre les deux dans le même fichier ferait porter à `date` un sens différent
selon la ligne, ce qui est la façon la plus sûre de casser un CSV qu'on ouvre dans un
tableur trois ans plus tard (`STO-02`).

Le mot `circuit` plutôt que `tabata` : c'est ce que le format décrit — des rounds et des
exercices — et ça ne fige pas le nom d'une application dans un nom de colonne. L'interface,
elle, dira « Cadence », puisque c'est ce que l'utilisateur ouvre.

### `circuits.csv`

| Colonne | Bornes | Note |
|---|---|---|
| `id` | 12 caractères | **Stable**, comme `workout_id`. Les exercices s'y rattachent |
| `name` | `Label` | Le nom de la séance dans Cadence |
| `rounds` | 1 – 99 | La borne vient de `llms.txt` §4, on la fait respecter à la saisie |
| `round_rest_s` | 0 – 900 | Idem |
| `created` | date | Serveur. Sert à trier, jamais à dater une mesure |
| `note` | `Note` | Libre. N'entre pas dans le lien |

### `circuit_exercises.csv`

| Colonne | Bornes | Note |
|---|---|---|
| `circuit_id` | — | Rattachement à `circuits.id`, jamais à sa position |
| `position` | 1 – 40 | L'ordre **lu**, jamais recompté |
| `name` | texte libre | Voir §5 — le nom décide de l'illustration |
| `duration_s` | 1 – 999 | Lu **seulement** si `reps == -1` |
| `reps` | `-1` ou 1 – 999 | `-1` = au temps. C'est cette colonne qui fait autorité |
| `rest_s` | 0 – 999 | Repos après l'exercice |

**`reps` fait autorité, `duration_s` est subordonnée.** Un fichier corrigé à la main peut
porter `reps: 12` **et** `duration_s: 30` ; la règle dit alors 12 répétitions, et
`duration_s` est ignorée. Sans cette règle écrite, deux lecteurs du fichier — le générateur
de lien et l'estimateur de durée — trancheraient différemment le jour où ça arrive.

Deux fichiers et non un, avec les exercices sérialisés dans une cellule : le projet a déjà
tranché ça pour `run_splits.csv`, et pour la même raison — une liste dans une cellule n'est
plus lisible dans un tableur, ce qui est la seule chose que `STO-02` demande.

---

## 3. Le module pur — `activity/circuit_link.py`

> **Pas `cadence.py`.** [`app/core/cadence.py`](../backend/app/core/cadence.py) existe déjà
> et décrit la **fréquence** d'une piste d'assiduité ; `RunRow.cadence_spm` compte des pas
> par minute. Trois sens pour un mot dans un même dépôt, c'est deux de trop. Le module dit
> ce qu'il fait — il fabrique et relit un lien — et le nom de l'application tierce reste où
> il désigne vraiment quelque chose : le réglage `cadence_base_url` et l'interface.

**C'est la première chose à écrire, et elle ne touche à aucun écran.**

Trois fonctions, aucune entrée-sortie, aucun réseau — mêmes garanties que `progress.py` et
`splits.py` :

```python
def build_url(base: str, circuit: Circuit) -> str        # llms.txt §5
def parse_url(url: str) -> ParsedCircuit | None          # llms.txt §1 à l'envers
def estimate(circuit: Circuit) -> Estimate               # llms.txt §7
```

**Pourquoi le serveur et pas le client.** L'invariant « aucun calcul métier côté client »
s'applique mot pour mot : l'échappement `~ → %7E`, le bornage à 99 rounds, le suffixe `x`
qui distingue 15 répétitions de 15 secondes — ce sont des règles, pas du formatage. Le
client reçoit un champ `url` déjà construit et ne fait que le poser dans un `href`.

**Pourquoi le serveur et pas le modèle non plus.** Un modèle à qui on demande une URL en
écrit une plausible. `Pompes:15:20` au lieu de `Pompes:15x:20` est la faute que `llms.txt`
§2 appelle « la plus fréquente », et elle est **silencieuse** : la séance se lance, elle est
simplement fausse. Le modèle nomme des exercices ; le serveur fabrique le lien.

### Ce que la batterie doit couvrir

Les onze points de la liste de `llms.txt` §11 deviennent onze tests. Plus deux qui viennent
du projet :

- **L'aller-retour.** `parse_url(build_url(base, c)) == c`, sur les cinq exemples vérifiés
  du §6 et sur des noms à accents, `~`, `:`, `%`, emoji. C'est le test qui attrape le plus
  de choses pour le moins d'écriture.
- **Les cas de `llms.txt` §9.** Un lien invalide ne lève pas : `parse_url` rend `None`, et
  l'import (§6) affiche une erreur portant un code. Aucune exception ne remonte à l'écran.

### L'estimation, et le `~` qu'elle traîne

`llms.txt` §7 est catégorique : dès qu'un exercice est en répétitions, la durée est une
estimation, et Cadence lui-même la préfixe d'un `~`. L'API rend donc deux champs :

```
estimated_duration_min: float
exact: bool          # faux dès qu'un exercice porte reps > 0
```

L'écran affiche `18 min` ou `~18 min` selon `exact`. **Ce n'est pas de la coquetterie** :
l'invariant « aucune valeur inventée à l'écran » interdit d'annoncer 18 minutes pour une
séance dont personne ne connaît la durée. Le tilde est ce qui distingue une mesure d'un
ordre de grandeur, et il est déjà le vocabulaire de l'application qu'on ouvre.

---

## 4. « Je l'ai fait »

`POST /api/activity/circuits/{row_id}/done`, et **aucun chemin d'écriture nouveau** : la
charge utile est une `WorkoutPayload`, le service appelé est
`WorkoutService.create(payload, source="cadence")`, qui accepte déjà une provenance
([`service.py:901`](../backend/app/domains/activity/service.py#L901)).

| Champ | Valeur |
|---|---|
| `date` | **Le jour du serveur.** L'écran ne date rien |
| `type` | `HIIT` — déjà dans `WORKOUT_TYPES` |
| `duration_min` | L'estimation, **pré-remplie et modifiable** avant l'appui (D4) |
| `note` | Le nom du circuit |
| `source` | `cadence` |
| `rpe` | Facultatif, proposé dans la même feuille |

**Une nouvelle provenance, `cadence`.** Elle rejoint `manual`, `apple` et `ia`. `IMP-05`
s'applique : corriger la durée d'une séance venue de Cadence ne la transforme pas en saisie
manuelle.

**Le geste, et pourquoi il n'est pas confirmé.** Consigner une séance est une **addition**,
et l'invariant est explicite — une addition se défait par la suppression que l'utilisateur
ferait de toute façon, elle n'a pas à être confirmée. Un appui suffit. C'est la suppression
d'un circuit qui passe par `SwipeRow` et ses deux appuis.

**Ce que ça ne fait pas.** Rien n'empêche de déclarer deux fois la même séance, et rien ne
rappellera de la déclarer. C'est la conséquence directe de D6, elle est assumée : Cadence ne
sait pas parler à Metric, et lui faire croire le contraire coûterait plus cher que le
problème.

---

## 5. Le réglage, et l'écran quand il est vide

`cadence_base_url` entre dans `SettingsValues` et `SettingsPayload`
([`app_settings/schemas.py`](../backend/app/domains/app_settings/schemas.py)), typé comme
une URL `https://` bornée. **Son défaut est la chaîne vide**, et c'est un défaut qui a un
sens : la fonctionnalité est en sommeil.

Trois conséquences, toutes à écrire :

1. `GET /api/activity/circuits` rend `url: null` sur chaque circuit tant que le réglage est
   vide. **Pas d'URL relative, pas de domaine deviné.**
2. L'écran affiche l'état vide qu'il doit : « L'adresse de Cadence n'est pas renseignée »,
   et le geste qui coûte le moins — un lien vers Réglages. Les circuits restent visibles et
   modifiables ; c'est le seul bouton « Ouvrir » qui manque.
3. Le champ va dans [`routes/settings/Profile.tsx`](../frontend/src/routes/settings/Profile.tsx),
   avec les autres réglages d'application.

> **Périmé depuis [`charges.md`](charges.md).** Ce paragraphe décrivait les 35 noms de
> Cadence, partis dans la consigne du modèle parce qu'eux seuls affichaient une
> illustration. Cadence en embarque **1324**, avec un rapprochement qui tolère le français :
> `circuit_link.ILLUSTRATED` n'existe plus, et la consigne dit désormais d'écrire des noms
> **précis** plutôt que d'appartenir à une liste. Le catalogue figé
> (`exercise_catalog.json`) sert la saisie ; **D2 tient toujours** — aucune correspondance
> n'est stockée entre les deux mondes.

---

## 6. L'écran — `/activite/seances`

**Une page, pas une section.** `/activite` fait déjà 4 763 px de haut et le §7 de
`CLAUDE.md` l'a noté ; le catalogue a pris ce chemin avant (`/activite/catalogue`), et le
précédent est bon. La page rejoint `routes/activity/`.

### Ce qu'on y voit

Une carte par circuit : le nom, `4 rounds`, `~18 min`, et trois gestes.

| Geste | Forme | Pourquoi cette forme |
|---|---|---|
| **Ouvrir** | Un `<a>` vers l'URL, cible 56 px (`--tap-lg`) | C'est l'action qui **termine** le geste |
| **Fait** | Une feuille : durée pré-remplie, RPE facultatif, un appui | §4 |
| **Corriger / Supprimer** | `SwipeRow` | Le motif existe, on ne réinvente pas un second vocabulaire |

**« Ouvrir » est un vrai lien**, pas un bouton qui appelle `window.open`. C'est ce qui donne
l'appui long, le partage, et surtout ce qui laisse iOS router vers la PWA installée.

### La feuille de création

Nom, rounds, repos entre rounds, puis les exercices : nom, un sélecteur **temps / reps**,
la valeur, le repos. Le sélecteur est ce qui écrit `−1` ou une valeur dans `reps` — il n'y
a pas de champ « −1 » à l'écran, la sentinelle reste dans le fichier.

Aucune valeur par défaut inventée dans le formulaire. L'invariant le dit et le §2 de
`CLAUDE.md` rappelle que `sets: '3'` écrit en dur traînait à trois endroits.

**Cette feuille s'ajoute à la table `SURFACES`** de
[`scripts/audit-surfaces.mjs`](../scripts/audit-surfaces.mjs) dans le même lot. C'est écrit
là-bas noir sur blanc, et l'angle mort d'où le script vient de sortir avait coûté six
surfaces à 32 px.

### L'import d'un lien collé

Un champ « Coller un lien Cadence », un appui, `parse_url` fait le reste. Le décodeur est
déjà écrit pour l'aller-retour du §3 : **le coût marginal est celui d'une route et d'un
champ.** C'est ce qui récupère d'un coup les séances déjà construites dans Cadence, qu'il
faudrait ressaisir sinon.

Un lien illisible rend une erreur portant un code (`invalid_workout_link`), avec son message
français depuis le serveur.

---

## 7. Le planning

D5 : **le lien vit dans la note**, telle qu'elle existe déjà. Aucune colonne nouvelle, aucun
rattachement, `plan.csv` ne bouge pas.

Ce que ça coûte, dit franchement :

- **Le lien ne suit pas les corrections du circuit.** Renommer un circuit ou changer un
  exercice ne touche pas la note déjà écrite. La séance prévue gardera l'ancienne version —
  ce qui, pour un plan écrit la semaine dernière, est défendable.
- **Supprimer un circuit ne casse rien.** L'URL est autoportante : elle contient la séance
  entière. C'est le seul endroit où l'absence de base de données joue en notre faveur.

### Ce que le serveur ajoute quand même

`PlannedSession` gagne un champ calculé :

```
workout_url: str | None      # extrait de la note par cadence.py
```

**Ce n'est pas une entorse à D5, c'en est la condition.** Sans lui, l'écran devrait
reconnaître une URL Cadence dans un texte libre — donc reconnaître le format côté client,
donc en tenir une seconde implémentation. Le serveur extrait, le client affiche un bouton
« Ouvrir ».

### iCal

`planning/ical.py` pose déjà `SUMMARY` et `DESCRIPTION` ; il pose en plus la propriété
`URL`, remplie par la même extraction. **Conséquence : une séance prévue s'ouvre depuis le
calendrier iOS**, sans passer par Metric. Vu le geste réel — on regarde son calendrier le
matin — c'est probablement le chemin le plus emprunté du lot, pour trois lignes.

---

## 8. L'assistant

Une action, un besoin de contexte, un ajout de consigne.

### `circuit.create`, niveau `AJOUT`

Elle s'exécute et s'annule d'un appui, comme `exercise.create` — elle n'écrit aucune mesure,
seulement un patron. Ses arguments sont la charge utile du domaine, `CircuitPayload` : le
même schéma, le même service, le même chemin d'écriture. La table d'actions
([`assistant/actions.py`](../backend/app/domains/assistant/actions.py)) gagne une ligne.

**Le lien est rendu par le résultat de l'action, pas par le texte de la réponse.** Le modèle
écrit « je t'ai fait un circuit épaules » ; c'est l'écran qui affiche le bouton « Ouvrir »,
construit avec l'`url` que le serveur a mise dans le résultat. Une URL tapée par le modèle
dans son `reply` serait du texte non vérifié, avec la faute du suffixe `x` en embuscade.

### `plan.add` gagne un argument facultatif

`circuit_id`. Quand il est présent, **le serveur** ajoute le lien à la note de la séance
prévue. Le modèle demande le rattachement, il ne fabrique pas l'URL — c'est la même règle
qu'au paragraphe précédent, appliquée au planning.

### La tranche de contexte `circuits`

Le mécanisme `need` existe et plafonne à deux passes
([`assistant-agent.md` §3](assistant-agent.md)). `need: ["circuits"]` rend la liste des
circuits enregistrés, pour que « refais-moi celui de mardi » désigne quelque chose.

### Générer depuis les données

C'est ce qui distingue Metric d'un générateur de liens : `stats.py` calcule déjà les
**groupes négligés**, et le condensé factuel les porte. « Fais-moi 20 minutes sur ce que je
néglige » est alors une demande à laquelle le modèle peut répondre — sans qu'on écrive une
seule ligne de génération, parce que le contexte et l'action existent tous les deux.

**Ce qui ne change pas :** `IA-12`. Un circuit reste un ajout, donc `AJOUT` ; mais la garde
qui refuse `plan.*` sur une alerte médicale s'applique telle quelle à `plan.add` porteur
d'un `circuit_id`. Un genou douloureux ne déclenche pas une semaine de tabata.

---

## 9. L'ordre d'exécution

Chaque phase est vérifiable seule. Les trois premières ne montrent rien à l'écran, et c'est
volontaire : le format est ce qui casse en silence.

> **Les phases 1, 2, 3 et le serveur de la 5 sont faites** (24 août 2026). Tout le backend
> du lot est donc en place ; il ne reste aucune route à écrire avant l'écran. Ce que chaque
> phase a coûté en plus du plan est en [§12](#12-journal).

| # | Phase | Ce qui la clôt |
|---|---|---|
| 1 | ~~`circuit_link.py` — construire, décoder, estimer~~ **fait** | Les 5 exemples de `llms.txt` §6 + l'aller-retour, verts |
| 2 | ~~Le réglage `cadence_base_url`~~ **fait** | Le champ dans Réglages, mesuré à 402 / 390 / 360 px dans les deux thèmes |
| 3 | ~~Le domaine — 2 CSV, schémas, service, 7 routes~~ **fait** | Les 8 familles de `patron-domaine.md` §4 |
| 4 | ~~La page `/activite/seances`~~ **faite** | Créer, ouvrir, faire, corriger, supprimer · mesurée 402 / 390 / 360 px, deux thèmes |
| 5 | ~~L'import d'un lien collé~~ **fait** | Le champ est en bas de `/activite/seances` |
| 6 | ~~Le planning — `workout_url` + `URL` iCal~~ **fait** | La séance s'ouvre depuis le calendrier iOS |
| 7 | ~~L'assistant — action, contexte, consigne~~ **fait** | Une demande en français produit un circuit ouvrable |
| 8 | Vérification | §10 |

---

## 10. Vérifier

`make check` d'abord, sans exception. Puis ce qu'il ne couvre pas, et qui trouve le reste :

```bash
node scripts/audit-mobile.mjs  --base http://localhost:<port> --token "<jeton>"
node scripts/audit-surfaces.mjs --base http://localhost:<port> --token "<jeton>"
```

`/activite/seances` entre dans le premier, sa feuille de création dans la table `SURFACES`
du second. **Puis regarder les captures**, dans les deux thèmes.

### Les trois choses qu'aucun script ne verra

1. **Le lien ouvre-t-il la PWA installée, ou Safari ?** C'est le pari de tout le lot, et il
   ne se vérifie que sur le téléphone. Si iOS ouvre Safari, la séance se lance quand même —
   Cadence est autonome côté client — mais on perd le plein écran et le son démarre moins
   bien. **Repli prévu si le cas se présente : un appui long sur la carte copie le lien**,
   et rien d'autre à changer.
2. **La longueur des URL.** Un circuit à quinze exercices aux noms longs fait une URL de
   plusieurs centaines de caractères. Elle tient partout, mais elle est illisible dans une
   note de planning. À regarder à la première vraie séance.
3. **Le clavier système sur la feuille de création.** Un formulaire à quatre champs par
   exercice, sur 390 px, avec le clavier ouvert : c'est exactement le genre d'écran que
   l'émulation rend confortable et que le pouce rend pénible.

---

## 11. Ce que ce lot ne fait pas

Nommé plutôt qu'oublié.

- **Les tabatas n'ajoutent aucun tonnage.** `weight_kg = 0` est le poids du corps, donc
  le volume est nul — ce qui est vrai. Ils comptent en **séries** par groupe musculaire,
  en séances et en durée.
- **Aucune notification, aucun rappel.** D6.
- **Aucune correspondance entre les deux catalogues d'exercices.** D2, toujours vrai :
  rien n'est stocké qui relie un nom de Cadence à un exercice de Metric. Le filet n'est
  plus la liste des 35 noms — elle a disparu ([`charges.md`](charges.md) §4) — mais le
  catalogue figé, qui **sert des noms exacts à la saisie** sans en apparier aucun.
- **Le format reste en version 1.** Si Cadence évolue, `cadence.py` est le seul fichier à
  rouvrir — c'est la raison d'être du §3.
- **Rien n'est fait pour partager un circuit à quelqu'un d'autre.** L'URL le permettrait
  trivialement ; l'application est mono-utilisateur, la question ne se pose pas.


---

## 12. Journal

### Phase 2 — le réglage (24 août 2026)

`cadence_base_url` dans `settings/settings.csv`, servi typé par l'API, saisi dans une carte
« Applications » de `/reglages`.

**Trois choses que le plan ne disait pas, et que le code a imposées :**

1. **La borne est une borne de lien, pas de vraisemblance.** `BaseUrl` refuse `?` et `#`
   — une base qui en porte donnerait `…?a=b?w=…` une fois le paramètre ajouté — et refuse
   tout ce qui n'est pas `http`/`https`, parce que la valeur finit dans un `href` rendu par
   l'application. Le refus arrive à la saisie, où il se corrige. *(Le refus du `?` est
   tombé le 2 septembre 2026 — voir la dernière entrée de ce journal ; le reste tient.)*
2. **Une adresse abîmée retombe sur rien, pas sur elle-même.** Le fichier s'ouvre dans un
   tableur ; une cellule collée de travers y est normale. Le service applique le même motif
   **en lecture** et rend la chaîne vide : l'écran dit alors « non renseignée », un état
   qu'il sait afficher, au lieu d'offrir un bouton qui mène à une page d'erreur.
3. **Le badge lit la valeur, pas `stored`.** Effacer l'adresse **écrit** une cellule vide,
   donc la clé est dans le fichier, donc `Origin` — qui lit `stored` — dirait « réglé »
   d'un champ vide. C'est le seul réglage de l'écran dans ce cas, parce que c'est le seul
   sans valeur de repli.

**Un défaut trouvé en capture et corrigé** : le paragraphe explicatif collait à l'étiquette
du champ. `.noteSpaced` n'espace que par le haut ; les cartes d'objectifs enveloppent leur
`Field` dans `.row`, et celle-ci le fait maintenant aussi. Aucune mesure ne l'avait vu — les
six relevés annonçaient déjà `0 cible < 44 px`.

**Mesuré** : 402, 390 et 360 px, thèmes sombre et clair. Zéro cible sous 44 px, aucun
débordement horizontal, aucun champ sous 16 px (donc pas de zoom iOS à la mise au point).

**Vérifié sur une doublure d'API**, pas sur les vraies données : le stockage Nextcloud
répondait `502` pendant tout le lot. Ce que ça laisse non vérifié : l'écriture réelle de la
clé dans `settings.csv` sur Nextcloud. Le chemin est celui de tous les autres réglages, et
la batterie backend le couvre sur un faux WebDAV — mais ce n'est pas la même chose que de
l'avoir vu.


### Phases 1, 3 et 5 — le module pur et le domaine (24 août 2026)

`circuit_link.py`, deux fichiers CSV, `CircuitService` et sept routes. **Aucun écran** : le
format est ce qui casse en silence, et il est éprouvé avant d'être montré.

**Ce que la batterie couvre** — 69 tests, dont les cinq exemples vérifiés de `llms.txt` §6
produits **au caractère près**, l'aller-retour sur chacun, les cinq tolérances du §4, les
cinq liens sans issue du §9, et les deux estimations du §7.

**Quatre choses que le plan ne disait pas :**

1. **Le bornage est dans le module pur, pas seulement dans le schéma.** Cadence *ramène*
   les valeurs hors bornes au lieu de les rejeter : une séance à 500 rounds s'y exécute à
   99. Si le bornage n'existait qu'à la saisie, une ligne corrigée dans un tableur ferait
   diverger ce que Metric estime de ce que Cadence exécute. `normalise` est donc appliquée
   par `build_url` **et** par `estimate`.
2. **Les bornes du circuit ne viennent pas de `core/validation.py`.** `Reps` ou
   `DurationMin` disent ce qui est vraisemblable *pour nous* et se discutent ; celles de
   Cadence sont le contrat d'une application tierce. `schemas.py` les dérive des constantes
   de `circuit_link`, pour que le schéma ne puisse pas diverger du générateur de lien.
3. **`CircuitList.linkable` n'est pas déductible de la liste.** Sur une liste vide, l'écran
   doit distinguer « aucun circuit » de « aucune adresse » — deux états vides qui ne
   proposent pas le même geste suivant.
4. **La sentinelle `-1` ne sort jamais du fichier.** À l'API, `duration_s` et `reps`
   s'excluent : c'est celui qui vaut `null` qui dit la nature de l'autre. À la saisie, c'est
   un sélecteur temps/reps. Personne n'a jamais à taper `-1`.

**Le test qui porte D2 et D3** : déclarer un circuit fait écrit une séance `HIIT` marquée
`cadence`, datée par le serveur, et vérifie que `exercise_log.csv` **n'existe même pas**.
Un second vérifie que le catalogue d'exercices de Metric reste vide après la création d'un
circuit nommé « Push-Ups Classic ».

**Vérifié contre le vrai Nextcloud**, revenu en ligne : `GET /api/activity/circuits` répond
`{"circuits": [], "linkable": false}` sur un stockage qui n'a encore aucun de ces fichiers —
donc les chemins, la lecture du réglage et l'état vide tiennent en conditions réelles.

**Ce qui n'a délibérément pas été fait** : aucune écriture dans le vrai stockage. Créer un
circuit y écrirait deux fichiers, et `/done` écrirait dans `workouts.csv`, c'est-à-dire dans
les vraies données de santé. Ça se fait sur demande, pas de sa propre initiative.


### D2 renversée — un tabata est du sport (24 août 2026)

La séparation des deux mondes ne survit pas à l'usage : un tabata fait est une séance, et
la voir disparaître de l'équilibre par groupe musculaire n'a aucun sens. Ce qui change :

- **`circuit_exercises.csv` porte `muscle_group`**, choisi à la création parmi les neuf de
  Metric. C'est la colonne qui relie les deux mondes, et elle est **exigée** à la saisie.
- **Rien n'est deviné depuis le nom anglais de Cadence.** Une correspondance approximative
  de plus se serait trompée en silence — exactement comme celle des illustrations, où
  « Push-Ups » donne l'image de *Pike Push-ups*.
- **`ExerciseService.ensure`** crée l'exercice dans `exercises.csv` au premier « fait »,
  puis le réutilise. Reconnaissance par `fold` et par les alias, celle de `notes.py` : pas
  une seconde règle. Un groupe déjà choisi n'est **jamais** écrasé — le catalogue appartient
  à l'utilisateur.
- **`ExerciseService.log_timed`** écrit la ligne de journal sans passer par
  `ExerciseEntryPayload`. Le schéma de saisie borne `reps` à `ge=1` ; desserrer cette borne
  aurait rendu `-1` acceptable **à la saisie manuelle**, où ce serait une faute de frappe
  silencieuse dans un journal de charge. Un second point d'entrée étroit et documenté coûte
  moins cher qu'une borne relâchée pour tout le monde.
- **`sets` = le nombre de rounds**, `reps` = les répétitions ou `-1` au temps, `weight_kg`
  = 0.
- **L'ordre d'écriture** : le catalogue d'abord, la séance ensuite, le journal enfin. Une
  panne laisse au pire une entrée de catalogue en trop — visible et corrigeable. L'ordre
  inverse laisserait une séance sans ses séries, c'est-à-dire une mesure incomplète.

**Ce qui reste séparé** : les noms anglais de Cadence ne sont rapprochés d'aucune donnée de
Metric. Ils servent à choisir un intitulé qui affiche une démonstration, et rien d'autre.

**Un cas qui reste imparfait** : un lien Cadence collé n'apporte aucun groupe musculaire —
le format n'a pas de champ pour ça. L'import écrit donc `autre`, et l'écran laissera
corriger. Un geste de plus, assumé, plutôt qu'un groupe faux qu'on n'aurait pas vu.


### Phase 4 — l'écran, et D4 rendue visible (25 août 2026)

`/activite/seances`. Une **page** et non une feuille : un circuit à huit exercices ne tient
pas dans un panneau à `86dvh` qui défile dans une page qui défile déjà. Même précédent que
`/activite/catalogue`, donc **aucune ligne n'est ajoutée à `SURFACES`** — la page entre dans
`PRIVATE_ROUTES` de `audit-mobile.mjs`, où elle est mesurée comme les autres.

**Ce que l'écran ne calcule pas** : ni le lien, ni la durée. `url` arrive fabriqué,
`estimated_duration_min` arrive calculée. L'écran pose l'un dans un `href` et formate
l'autre — avec le `~` que lui impose `exact`.

**Le sélecteur Secondes / Répétitions** est ce qui empêche la faute la plus fréquente du
format. Il écrit `duration_s` **ou** `reps` dans la charge utile, jamais les deux, et jamais
`-1` : la sentinelle reste dans le fichier.

**`ExternalLinkButton`**, nouvelle primitive. `LinkButton` rend un `Link` de react-router :
il intercepte le clic et cherche une route interne, donc une adresse vers une autre
application n'y mène nulle part. Un vrai `<a href target="_blank" rel="noopener noreferrer">`
donne l'appui long, le partage, et la chance que le système route vers la PWA installée.

**Quatre défauts trouvés en capture, aucun par la batterie** — les six relevés annonçaient
`0 cible < 44 px` avant comme après :

1. La carte « Coller un lien Cadence » occupait tout le haut de l'écran, avant la liste. Ce
   qu'on vient faire neuf fois sur dix, c'est ouvrir une séance. Elle est passée en bas.
2. Son champ collait à son paragraphe — le même `noteSpaced` qui n'espace que par le haut,
   déjà payé au lot précédent sur la carte des réglages.
3. Quatre actions sur une rangée : « Supprimer » se retrouvait seul sur une deuxième ligne
   à 390 px, et la grappe se lisait comme quatre boutons de même poids. « Ouvrir dans
   Cadence » prend maintenant toute la largeur et sa hauteur `--tap-lg` — c'est l'action qui
   **termine** le geste.
4. « Repos entre rounds (s) » passe sur deux lignes à 360 px et décalait son champ de 20 px
   sous celui de « Rounds ». `align-items: end` sur la paire, ce qui règle le cas pour tous
   les libellés — raccourcir celui-ci ne l'aurait réglé que pour lui.

**Mesuré** : 402, 390 et 360 px, thèmes sombre et clair, page seule et formulaire ouvert.
Zéro cible sous 44 px, aucun débordement horizontal, aucun champ sous 16 px.

**Vérifié sur la doublure d'API.** Rien n'a été écrit dans le vrai Nextcloud.

**Ce qui reste imparfait, et nommé** : à 360 px, « Supprimer » passe encore à la ligne sous
« Fait » et « Corriger ». C'est un retour à la ligne propre, et l'armement en deux appuis
protège le geste — mais l'action la plus dangereuse est celle qui a sa ligne à elle.


### Phases 6 et 7 — le planning et l'assistant (25 août 2026)

**Les sept décisions du §1 sont toutes en vigueur.** D6 n'a jamais rien demandé — c'est le
choix de *ne pas* ouvrir de retour depuis Cadence — et D7 a été rendue à la phase 1.

#### Le planning

- `PlannedSession.workout_url`, **extrait de la note par le serveur**. `plan.csv` ne gagne
  aucune colonne : le raccourci de D5 tient.
- `circuit_link.find_in_text` fait l'extraction, et c'est `parse_url` qui tranche — pas
  « ça ressemble à une URL ». Une adresse sans séance lisible n'est pas rendue, donc
  l'écran ne propose jamais d'ouvrir un lien mort.
- `PlanPayload.circuit_id` : le serveur colle le lien **à la note**, puis l'oublie. Un
  identifiant qui ne désigne rien est ignoré en silence — refuser toute la séance prévue
  parce qu'un modèle a nommé un circuit supprimé coûterait plus que ça ne protège.
- **Le flux iCal porte `URL`** (§3.8.4.6), non échappée comme du texte : la RFC la type
  `URI`. Une séance prévue s'ouvre donc dans Cadence **depuis le calendrier iOS**.

#### L'assistant

- `circuit.create`, niveau `AJOUT` — elle n'écrit aucune mesure, seulement un patron, et se
  défait d'un appui.
- **Le modèle ne tape jamais d'URL.** `Outcome.link` porte l'adresse fabriquée par le
  service, `ActionReport.link` la transporte, l'écran la rend en bouton. Une adresse écrite
  par un modèle est du texte non vérifié, où le suffixe `x` se perd en silence.
- Tranche `seances_cadence` : les séances enregistrées, **et la règle de nommage** — écrire
  des noms précis, en français si besoin. La liste des 35 noms qui vivait ici est partie
  avec `circuit_link.ILLUSTRATED` ([`charges.md`](charges.md) §4) : 1324 noms coûteraient
  la fenêtre de contexte pour un gain nul.
- La tranche dit aussi quand l'adresse de Cadence n'est pas réglée : mieux vaut que le
  modèle le sache que de le laisser promettre un lien qui n'existera pas.

#### Deux gardes structurelles ont fait leur travail

`test_assistant_context` et `test_assistant_actions` ont refusé le lot tant que
`circuit.create` n'avait pas sa tranche de lecture déclarée et son domaine d'annulation
enregistré. C'est exactement ce pour quoi elles existent.

#### Un défaut trouvé en capture

Sous le bouton « Ouvrir dans Cadence », la note répétait l'URL en toutes lettres — deux
lignes de `?w=Gainage~2~60~Plank:60s:30` au milieu du texte réellement écrit. L'écran
affiche maintenant la note privée de cette adresse.

**Ce n'est pas reconnaître le format côté client** : le serveur a déjà fait ce travail et
rend `workout_url` ; l'écran retire une sous-chaîne exacte qu'il n'a pas identifiée
lui-même. La note **stockée** n'est pas touchée — le formulaire de correction la recharge
entière, sinon enregistrer une modification effacerait le lien.

#### Mesuré, et ce qui reste

402 / 390 / 360 px, deux thèmes. Zéro cible sous 44 px sur `/planning` à 402 et 390.

**À 360 px, trois cases du calendrier mensuel font 39 px de large** — sept colonnes dans
360 px moins les marges, c'est de l'arithmétique. **Défaut pré-existant, laissé** : il ne
vient pas de ce lot et le corriger veut dire repenser la grille du mois, ce qui est un lot
en soi. Il est nommé ici pour ne pas se redécouvrir.


### Le champ à suggestions, et un bug de l'assistant (25 août 2026)

#### Le bug : `circuit.create` refusée, sans dire pourquoi

Symptôme réel : une réponse juste — quatre exercices, illustrations comprises — et
« La valeur donnée pour « exercises » n'est pas acceptable. »

**Deux causes, et la même leçon que le `kind` de `plan.add` :**

1. **Le catalogue d'actions ne savait pas décrire un objet imbriqué.** `_field_doc` ne
   traitait que des scalaires ; `circuit.create` est la première action dont un argument est
   une liste d'objets, et elle était annoncée `exercises (texte, requis)`. Aucun modèle ne
   peut rien faire de ça. `_field_doc` suit maintenant les `$ref` et rend la forme complète.
2. **`muscle_group` était un `str` avec un validateur.** Un validateur ne laisse aucune
   trace dans le schéma JSON : le modèle lisait « texte » pour un champ qui n'accepte que
   neuf valeurs, et envoyait « pecs ». Il est typé par l'énumération `MuscleGroup`, dont les
   neuf valeurs partent maintenant dans la consigne.

Le libellé de l'action porte en plus la règle que le schéma ne sait pas dire : `duration_s`
**ou** `reps`, jamais les deux.

Le correctif vaut pour toute action future à charge utile imbriquée — c'est le point.

#### Le champ à suggestions

`components/ui/Combobox.tsx`, servi par `GET /api/activity/circuits/exercises` — devenu une
**recherche** (`?q=`) : le catalogue de l'utilisateur d'abord, ce sont les seuls noms qui
portent un groupe musculaire, puis le catalogue figé de Cadence, sans doublon —
reconnaissance par `fold`, celle du reste du domaine.

- La liste se réduit **à chaque frappe**, sans accents ni casse ni ponctuation.
- `Tab` écrit le premier résultat et passe au champ suivant ; `Entrée` écrit le surligné ;
  flèches pour parcourir, `Échap` pour fermer.
- Choisir une suggestion **pré-remplit le groupe musculaire** quand l'exercice est déjà au
  catalogue. Rien n'est deviné depuis le nom.
- Le champ **reste libre** : un nom hors liste s'enregistre. Ces suggestions ne sont pas des
  valeurs autorisées — n'importe quel intitulé fait tourner une séance.

**Pas de `<datalist>`** : iOS ne le rend pas, il ne complète pas au `Tab`, et il n'est pas
stylable — donc ses lignes ne peuvent pas porter les 44 px de plancher.

**La liste est dans le flux**, pas en position absolue : une liste flottante se fait
recouvrir par le clavier système, qui occupe la moitié basse de l'écran dès qu'on tape.

#### Trois défauts trouvés, deux en capture, un au test

1. **Débordement horizontal à 360 px** : la liste prenait la largeur de son plus long nom.
   Un enfant de conteneur flex ne rétrécit pas sous son contenu sans `min-width: 0` — la
   règle vaut à chaque étage, d'où les trois.
2. **Le mot « ILLUSTRATION » tronquait le nom** — « Push-Ups Cla… » — alors que le nom est
   précisément ce qu'on lit pour choisir. Il est devenu une puce, le texte restant en
   `.sr-only` et le `hint` du champ disant ce qu'elle signifie.
3. **Taper « plank » masquait la suggestion « Plank »** : le filtre « une seule
   correspondance déjà écrite » comparait sur le repli, donc empêchait de corriger la casse
   — celle qui décide de l'illustration. La comparaison porte sur le texte brut.

**Mesuré** : 402 et 360 px, deux thèmes, liste ouverte. Zéro cible sous 44 px, aucun
débordement, aucun champ sous 16 px.


### L'écran sur ordinateur (25 août 2026)

L'audit ne mesure que des largeurs de téléphone. Trois défauts n'existaient qu'au-delà, et
tous les trois sortaient d'une seule cause : **rien ne bornait le formulaire**.

1. **Les champs s'étiraient sur toute la page.** À 1 440 px, le champ où l'on tape « 4 »
   faisait 1 200 px de large, et l'œil traversait l'écran entre une étiquette et sa valeur.
   Le projet a déjà l'idiome — `.lede` se borne à `56ch`. Le formulaire se borne à `56rem`
   au-delà du premier point de rupture ; sous 600 px, la largeur disponible *est* la bonne.
2. **La borne a d'abord été trop serrée.** À `46rem`, les neuf pastilles de groupe
   musculaire se mettaient à défiler alors qu'il restait 700 px de vide à droite — un geste
   de plus pour rien. `56rem` est la largeur à laquelle elles tiennent sur une ligne.
3. **La puce d'illustration finissait à l'autre bout de l'écran.** `justify-content:
   space-between` sur une ligne de 1 200 px la détachait du nom : elle ne se lisait plus
   comme une annotation mais comme une décoration de fin de ligne. Elle est collée au nom,
   et la même règle vaut aux deux largeurs — une seule, plutôt que deux.

**Mesuré** : 1 440, 1 024 et 768 px, formulaire ouvert et liste dépliée. Aucun débordement,
zéro cible sous 44 px.


### Le fil garde ce qu'il a fait, et la conversation reprend (25 août 2026)

#### Le chevauchement sur ordinateur

Au-delà de 600 px, `.catalogueRow` passe en `flex-direction: row`. Le lien « Ouvrir » y
était un **frère du texte**, avec `width: 100 %` : il réclamait toute la ligne et recouvrait
le nom de la séance, qui se coupait mot par mot. Les actions sont maintenant dans un bloc à
elles — invisible sur téléphone, où la rangée est déjà une colonne.

#### Les actions survivent à la réouverture d'un fil

La colonne `actions` de `messages.csv` était **documentée mais jamais écrite**. Elle l'est.

- **Sans les annulations.** Le jeton d'une ligne périme dès qu'elle change ; ranger le
  bouton « annuler » n'aurait qu'un effet — un `409` trois jours plus tard que rien
  n'explique.
- **Sans les actions refusées.** Elles n'ont rien produit ; les relire ferait réapparaître
  un échec passé comme s'il venait d'avoir lieu.
- **Ce qui reste ne périme pas** : la phrase, le lien, l'identifiant. Un lien Cadence porte
  la séance entière — et la retrouver est ce qu'on vient chercher en rouvrant un fil.
- Une cellule JSON coupée en deux coûte les actions de son tour, jamais le fil.

#### Le bouton « Fait » dans le fil

Après la séance, on revient dans la conversation et on la consigne sans changer d'écran.
Durée pré-remplie par l'estimation, corrigeable — le même geste et les mêmes mots qu'à
`/activite/seances`, pas un second vocabulaire pour le même acte.

Le circuit est retrouvé par son identifiant **stable** (`ActionReport.resource_id`), jamais
par la position qu'il occupait au moment de la réponse : `undo.row_id` se décale à la
première suppression. Un circuit supprimé depuis ne se retrouve pas, et le bouton disparaît
de lui-même plutôt que d'échouer à l'appui.

#### La conversation reprend sous une heure

`ThreadList.resume` : le serveur rend un identifiant de fil, ou rien.

**La décision est prise côté serveur.** Il tient l'heure et le fuseau ; mesurer l'écart dans
l'écran serait un second calcul de temps, celui que « le jour vient du serveur » interdit.
Le client reçoit un identifiant ou rien — il n'a aucun écart à mesurer.

Une heure, et le nombre se défend des deux côtés : plus court, on perd le fil d'une séance
parce qu'on a rangé le téléphone ; plus long, on revient le soir sur une conversation du
matin, et le modèle reçoit un passé hors sujet — pire qu'un fil vide.

La reprise ne s'applique qu'à un écran vierge : ni sur un `?fil` explicite, qui est une
adresse, ni après avoir fermé un fil à la main. Elle est **dérivée au rendu** et non posée
par un effet — `react-hooks/set-state-in-effect` a refusé la première version, à raison.

**Mesuré** : 402 et 1 440 px. Zéro cible sous 44 px, aucun débordement.


### Les séances passent en tête, et la fête arrive (25 août 2026)

#### Mises en avant sur `/activite`

Une séance Cadence est le geste le plus direct de l'écran — un appui et elle démarre —
alors que consigner une série suppose d'avoir déjà commencé. Elle passe donc **devant le
journal**, par le même arbitrage qui avait fait passer le journal devant les statistiques.

- Trois cartes au plus : au-delà, la section repousse le journal hors de l'écran et
  redevient un catalogue. Le lien mène au reste.
- **Ni créer, ni corriger, ni supprimer** : ça vit sur `/activite/seances`, qui a l'espace
  et l'adresse. Ici on ouvre et on consigne — les deux gestes qu'on fait le téléphone à la
  main.
- Le lien « Séances Cadence » a quitté l'en-tête : deux portes vers la même page dans le
  même écran font hésiter au lieu d'aider.

#### Une seule carte, trois endroits

`routes/activity/CircuitCard.tsx` sert en tête de `/activite`, sur `/activite/seances` et
dans le fil de l'assistant. Trois copies auraient donné trois façons de dire « fait », trois
arrondis de durée, et le jour où l'une change les deux autres mentent. L'assistant l'importe
à travers `routes/` — inhabituel, et le moindre mal : ce qui est partagé est un **geste
métier**, pas une primitive d'interface.

#### « Fait » → « Je l'ai faite »

Le mot seul se lisait comme une étiquette d'état — *cette séance est faite* — au lieu d'un
geste. La coche et le verbe disent qu'on agit. Le bouton porte aussi l'annulation quand le
panneau est ouvert, ce qui retire un bouton de la carte.

#### Les confettis

`lib/confetti.ts` — deux gerbes tirées des coins bas vers le centre, en canevas, sans
dépendance. Elles partent quand quelque chose est **accompli** :

| Moment | Où |
|---|---|
| Une séance Cadence consignée | `CircuitCard` |
| Une performance consignée | `Journal` |
| Une course enregistrée | `ActivitySheet` |
| Un objectif clos **parce qu'il est atteint** | `Goals` |

**Jamais sur une correction.** Corriger une série est un rattrapage, pas un accomplissement,
et célébrer les deux reviendrait à ne célébrer ni l'un ni l'autre. Un objectif abandonné se
respecte en silence — c'est `outcome === 'reached'` qui décide, pas la clôture.

**Trois garanties, testées :**

1. `prefers-reduced-motion` est respecté — **rien**, pas une version lente.
2. La surface est `pointer-events: none` et `aria-hidden` : elle ne se met jamais entre le
   doigt et le bouton qu'on vient d'appuyer, et le message de confirmation dit déjà ce qui
   s'est passé.
3. Une célébration ne peut pas faire échouer le geste qu'elle célèbre : sans contexte 2D,
   elle repart en silence.

**La palette vient des jetons** (`--confetti`), une liste par thème. C'est la seule liste de
couleurs du dépôt qui ne porte aucun sens — elle est dans `tokens.css` quand même, parce que
la première exception à « aucune couleur en dur » en appellerait une seconde.

**Un défaut trouvé au test, invisible à l'œil** : `surface()` gardait sa référence sans
vérifier que le nœud était encore dans le document. Tout ce qui vide le corps de la page
laissait la variable pointer sur une surface détachée, et **plus aucune célébration ne
s'affichait** — sans qu'une ligne de code puisse le dire. `isConnected` règle le cas.

### Une base peut porter sa clé d'accès (2 septembre 2026)

L'instance visée est `https://ct.aleksi.systems/?key=2740101265485712` : une installation
privée sert sa clé **dans l'adresse**. La base et son paramètre y sont inséparables, et
`BaseUrl` les refusait — le refus du `?` supposait que toute base était un domaine nu.

**Ce qui change, et ce qui ne change pas :**

- `BaseUrl` **accepte une query string**. `build_url` colle alors son paramètre avec `&`,
  et avec `?` quand il n'y en a pas — une base finissant déjà par `?` ou `&` n'en gagne pas
  un second.
- **`#` reste refusé**, et pour une raison qui n'a pas d'échappatoire : tout ce qui suit une
  ancre est le fragment, jamais un paramètre. `…#x&w=…` n'ouvrirait aucune séance.
- **`?w=` reste refusé**, mais la règle a déménagé du motif vers un validateur. Elle demande
  de lire les noms de paramètres, ce qu'une expression régulière de champ ne fait pas
  lisiblement ; en échange, le message est en français — « cette adresse porte déjà une
  séance » — au lieu du motif brut que pydantic affichait à l'utilisateur.
- **Une seule écriture de la règle.** Le service des réglages appliquait sa propre copie du
  motif en lecture ; il appelle maintenant `usable_base_url`, à côté de `BaseUrl`. Deux
  écritures auraient divergé sur ce lot précisément, et l'écart ne se serait vu qu'au clic.

**Vérifié** : les liens des cinq exemples de la spécification sont inchangés (base sans
query), le lien d'une base à clé se relit par `parse_url` — `_raw_param` cherchait déjà `w`
parmi les paramètres sans supposer qu'il est le premier —, et les quatre formes refusées à
la saisie le sont encore.
