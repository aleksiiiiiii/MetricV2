# Charges — les poids d'une séance Cadence

Cadence Tabata a changé : sa bibliothèque est passée de 35 illustrations à 1324
démonstrations, et sa grammaire de lien accepte un **4ᵉ champ par exercice**, une note
libre affichée sous le nom pendant l'effort. Ce lot fait deux choses, et la seconde est la
raison de la première.

1. **Mettre Metric à jour sur la spécification v2** — le 4ᵉ champ, la fin de la liste
   fermée de 35 noms, le catalogue des 1324.
2. **Une page `/activite/charges`** où l'on note le poids de chaque exercice de tabata,
   et où ce poids **remplit le 4ᵉ champ du lien**. C'est ce qui fait qu'une séance ouverte
   dans Cadence affiche « 12 kg » sous « Rowing », sans qu'on ait à s'en souvenir.

La grammaire du lien ne bouge pas par ailleurs. **Tous les liens déjà collés dans une note
de planning restent valides**, et aucun n'est à réécrire : le 4ᵉ champ est une addition
rétrocompatible, un exercice à trois champs se comporte exactement comme avant.

Le format reste spécifié dans [`llms.txt`](../llms.txt) ; ce document ne le recopie pas.
[`cadence.md`](cadence.md) reste la feuille de route du pont vers Cadence — ce lot en
révise deux paragraphes, signalés au §9.

---

## 1. Les décisions prises

Toutes arbitrées avant écriture. Elles sont ici pour être relues, pas rediscutées en cours
de route.

| | Décision | Conséquence |
|---|---|---|
| **C1** | La charge vit **par nom d'exercice**, dans `activity/circuit_loads.csv` | Noter « 12 kg » sur Rowing le met à jour dans les trois circuits qui l'emploient. Un seul geste, une seule vérité |
| **C2** | **Chaque modification écrit une ligne datée** dans `activity/circuit_load_log.csv` | Le graphique montre les décisions de charge, pas les séances. Il bouge même une semaine sans tabata — c'est voulu, §2 |
| **C3** | « Poids du corps » se **déclare**, il ne se devine pas | Trois états : jamais renseigné · poids du corps · une charge. Aucune correspondance approximative avec le catalogue, aucune valeur inventée |
| **C4** | `mark_done` **ne change pas** : `exercise_log.weight_kg` reste à 0 | Aucun chiffre existant ne bouge, `stats.py` reste intact. Le coût est nommé au §9 |
| **C5** | Le catalogue des 1324 est **figé dans le dépôt**, dérivé du jeu de données MIT | Zéro dépendance réseau vers Cadence. Un script le régénère, la donnée seule — pas les médias, §4 |
| **C6** | Le pas des boutons + / − est **1 kg** | Le réglage réel d'un tabata se fait au kilo. Le champ reste saisissable pour 7,5 kg |
| **C7** | La note du lien est **fabriquée par le serveur**, jamais saisie | `12 kg`, ou rien. Le client ne compose aucune URL — l'invariant du §2 de `CLAUDE.md`, mot pour mot |
| **C8** | À l'import d'un lien collé, la note est **ignorée** | Relire « haltères 12 kg » en `12.0` serait la correspondance approximative que ce dépôt s'interdit. §9 |

### Le point où la décision est inconfortable — C4

Déclarer un tabata fait continue d'écrire `weight_kg = 0` dans `exercise_log.csv`, c'est-à-dire
« poids du corps » (`ACT-07`). **Le journal de `/activite` dira donc « poids du corps » pour
un Rowing effectué à 12 kg.** C'est faux, et c'est assumé pour cette raison précise :

`stats.py` calcule `weight_kg × sets × reps` à quatre endroits (lignes 184, 298, 407, 413),
et un exercice au temps porte `reps = -1`. Avec une charge non nulle, un gainage à 20 kg
produirait un tonnage de **−320 kg** — un chiffre faux, négatif, et parfaitement muet. Ouvrir
cette porte demande de garder `reps == -1` aux quatre endroits, plus partout où le volume se
recalculera un jour ; en oublier un ne casse rien et ment.

Le lot fait donc le choix de ne pas y toucher. **Si la charge doit compter dans le tonnage,
c'est C4 qu'on rouvre**, avec les quatre gardes comme premier ticket — pas en passant.

---

## 2. Les deux fichiers

```
activity/circuit_loads.csv      name · weight_kg · bodyweight · updated
activity/circuit_load_log.csv   name · date · weight_kg · bodyweight
```

**Pourquoi un fichier à part et pas une colonne sur `exercises.csv`.** Le catalogue de
Metric porte des exercices de musculation, dont la charge est déjà journalisée série par
série dans `exercise_log.csv`. Une colonne « charge » y vivrait à côté d'une mesure qui dit
la même chose autrement : deux vérités pour un chiffre, et la garantie qu'elles divergeront.

**Pourquoi pas une colonne sur `circuit_exercises.csv`.** Le même exercice apparaît dans
plusieurs circuits. Une colonne par ligne autoriserait Rowing à 12 kg ici et 16 kg là, et
la page devrait alors choisir laquelle afficher — un arbitrage qu'aucune règle ne tranche.

### `circuit_loads.csv`

| Colonne | Bornes | Note |
|---|---|---|
| `name` | `Label` | Le nom **tel qu'il est écrit dans le circuit**. Le rapprochement passe par `fold` (`app/core/text.py`), celui du reste du domaine |
| `weight_kg` | 0 – 500, ou vide | Vide **n'est pas zéro** : zéro serait une mesure, vide est une absence |
| `bodyweight` | booléen | Vrai = poids du corps. **Exclusif de `weight_kg`** : le service en efface un en posant l'autre |
| `updated` | date | Serveur. Le jour de la dernière décision, jamais celui d'une séance |

**Une ligne n'existe qu'une fois quelque chose déclaré.** L'absence de ligne est le
troisième état, « jamais renseigné », et c'est celui qui affiche un tiret.

### `circuit_load_log.csv`

Une ligne par changement **confirmé**, jamais une par appui sur `+` : le pas-à-pas ajuste
une valeur locale, c'est l'enregistrement qui écrit. Sans cette règle, monter de 10 à 16 kg
laisserait six lignes dans le journal et six points sur la courbe.

Le passage en « poids du corps » y entre aussi, avec `bodyweight` vrai et `weight_kg` vide :
c'est un vrai événement de la courbe — la charge s'arrête — et l'omettre ferait mentir le
graphique par le silence.

---

## 3. Le 4ᵉ champ du lien

`circuit_link.py` est le seul fichier touché, et il ne touche à aucun écran.

```python
@dataclass(frozen=True)
class LinkExercise:
    name: str
    duration_s: int = DEFAULT_DURATION_S
    reps: int = TIMED
    rest_s: int = 0
    note: str = ""          # nouveau — le 4ᵉ champ
```

- `build_url` n'ajoute `:{_encode(note)}` **que si la note est non vide**. Un lien sans
  charge garde exactement les octets qu'il avait hier — c'est ce qui rend le lot
  vérifiable : la batterie existante doit rester verte sans être retouchée.
- `_encode` échappe déjà `~` en `%7E`, `:` en `%3A` et l'espace en `+`. La note passe par
  la même fonction, sans exception : deux échappements différents dans un même lien
  finiraient par diverger.
- `parse_url` lit un 4ᵉ champ quand il est là, `""` sinon. L'aller-retour
  `parse_url(build_url(base, c)) == c` couvre alors les notes, y compris celles qui
  contiennent `~`, `:` et des accents.

**Aucune borne haute sur la note dans ce module**, et c'est délibéré : `circuit_link`
reproduit Cadence, qui ne tronque pas. La note qui y arrive est fabriquée par le service à
partir d'une charge déjà bornée — `12 kg` fait huit caractères — donc courte par
construction. Un plafond arbitraire ne protégerait de rien et casserait l'aller-retour sur
un lien fabriqué ailleurs, qu'on doit pouvoir relire tel quel.

Un `:` non échappé dans une note d'un lien fabriqué ailleurs **coupe la note au premier
deux-points**, et on ne recolle pas les morceaux : c'est là que Cadence coupe, et afficher
autre chose ferait diverger les deux écrans.

---

## 4. Le catalogue figé

```
backend/app/domains/activity/exercise_catalog.json     ~110 ko, 1324 entrées
scripts/build-exercise-catalog.mjs                     le régénère depuis la source
```

La source est [`hasaneyldrm/exercises-dataset`](https://github.com/hasaneyldrm/exercises-dataset),
`data/exercises.json` — 17 Mo, dont on ne garde que quatre champs par exercice :

```json
{ "n": "barbell full squat", "b": 8, "e": 2, "t": 8 }
```

`b`, `e`, `t` sont des indices dans les listes `bodyParts`, `equipment` et `targets` posées
à la racine du fichier — la même forme que le `catalog.json` que Cadence sert, pour que les
deux restent lisibles côté à côté.

**Ce qu'on ne reprend pas, et pourquoi.** Le champ `f` (nom de fichier du média) reste
dehors : les images et les GIF appartiennent à **Gym visual** et ne sont redistribuables
que sous leurs conditions. Les **données** — noms, zones, matériel, cibles — sont sous
licence MIT, et ce sont les seules qu'on fige. Le fichier porte une clé `"license"` qui le
dit, et le script la réécrit à chaque génération.

**Ce qui disparaît.** `circuit_link.ILLUSTRATED` et ses 35 noms, en trois endroits :

| Fichier | Ce qu'il devient |
|---|---|
| [`circuit_link.py`](../backend/app/domains/activity/circuit_link.py) | La constante part. Le module ne connaît plus aucun nom d'exercice — il fabrique un lien, c'est tout |
| [`service.py`](../backend/app/domains/activity/service.py) `CircuitService.suggestions()` | Devient une **recherche**, §5 |
| [`assistant/context.py`](../backend/app/domains/assistant/context.py) `_cadence_circuits` | La liste des 35 laisse place à une consigne : écrire des noms **précis**, en français si besoin — « fentes marchées » plutôt que « jambes » |

**On n'injecte pas 1324 noms dans la consigne du modèle.** La règle de Cadence est
qu'en dessous de la moitié des mots reconnus, aucune démonstration ne s'affiche — et
qu'un nom sans démonstration reste une séance parfaitement valide. Un nom précis suffit ;
une liste de 1324 coûterait la fenêtre de contexte pour un gain nul.

---

## 5. Le domaine

### Les routes

```
GET    /api/activity/loads                    → LoadList
GET    /api/activity/loads/detail?name=…      → LoadDetail
POST   /api/activity/loads                    → crée la ligne (aucune n'existe encore)
PATCH  /api/activity/loads/{row_id}           → corrige, If-Match exigé
GET    /api/activity/circuits/exercises?q=…   → la recherche du catalogue (remplace l'existante)
```

`POST` **et** `PATCH`, et ce n'est pas une redondance : tant qu'aucune charge n'a été
déclarée, il n'y a pas de ligne, donc pas de jeton, donc rien à garder. Poser la première
charge est une **addition** ; la corriger est une **modification**, et `STO-05` s'applique
mot pour mot. La liste rend `id` et `token` à `null` sur un exercice jamais renseigné, et
c'est l'écran qui choisit le verbe.

**La recherche par nom et non par position.** `/loads/detail?name=…` : une position se
décale à la première suppression, et un exercice jamais renseigné n'a aucune ligne dont on
pourrait donner la position. Le rapprochement passe par `fold`.

### Ce que la liste rend

```
{ "loads": [
    { "id": 3, "token": "…", "name": "Rowing", "state": "weighted",
      "weight_kg": 12.0, "updated": "2026-08-31", "circuits": 2 },
    { "id": null, "token": null, "name": "Fentes", "state": "unset",
      "weight_kg": null, "updated": null, "circuits": 1 }
] }
```

`state` vaut `weighted`, `bodyweight` ou `unset`, **décidé par le serveur**. L'écran groupe
sur cette étiquette ; il ne déduit pas « non renseigné » d'un `null`, ce qui reviendrait à
lui faire porter la règle.

`circuits` est le nombre de circuits qui emploient cet exercice. C'est la réponse à la seule
question que la carte pose — « pourquoi celui-là est ici ? » — et elle coûte une lecture déjà
faite.

**La liste vient de `circuit_exercises.csv`**, dédoublonnée par `fold`, et d'elle seule.
Un exercice de musculation n'y entre pas : la page ne montre que ce qui est constitutif
d'une séance tabata.

### Ce que le détail rend

```
{ "name": "Rowing", "state": "weighted", "weight_kg": 12.0,
  "history":  [ { "date": "2026-07-02", "weight_kg": 10.0 }, … ],
  "sessions": [ { "date": "2026-08-02", "count": 1 }, … ],
  "circuits": [ "Haut du corps", "Full body" ] }
```

- `history` vient de `circuit_load_log.csv`, dans l'ordre chronologique **relu**, jamais
  supposé : le fichier peut être trié dans un tableur.
- `sessions` fait **exactement 30 entrées**, du plus ancien au jour du serveur, une par
  jour, `count` compris. Les jours sans séance portent `0` — ici zéro est une mesure, pas
  une valeur inventée : on a bien compté, et il n'y en a pas eu. La source est
  `exercise_log.csv`, celui que `mark_done` remplit déjà.

Le compte des 30 jours est fait **côté serveur**. Le client reçoit 30 nombres et dessine
30 points — il ne connaît ni la fenêtre, ni le jour d'aujourd'hui (`CLAUDE.md` §2, « le
jour vient du serveur »).

### La recherche d'exercices

`GET /api/activity/circuits/exercises?q=&body_part=&equipment=` rend **au plus 50**
résultats : le catalogue de Metric d'abord — ce sont les seuls qui portent un groupe
musculaire — puis le catalogue figé. Le filtrage est serveur ; servir 1324 entrées à un
téléphone pour qu'il les filtre serait 110 ko sur le réseau et un calcul de plus côté
client.

`CircuitSuggestion.illustrated` disparaît : avec 1324 démonstrations et un rapprochement
tolérant, le booléen ne distinguait plus rien d'utile — et le calculer aurait demandé de
réimplémenter l'algorithme de Cadence, c'est-à-dire d'en tenir une seconde version.

---

## 6. L'écran — `/activite/charges`

Une page, `routes/activity/Loads.tsx`, atteinte depuis `/activite` à côté de « Catalogue »
et « Statistiques ». Conteneur `cx('wrap', styles.screen)` — le défaut a déjà été trouvé
deux fois.

### Trois sections, dans cet ordre

| Section | Ce qu'on y voit |
|---|---|
| **À renseigner** | Les `unset`. En tête, parce que c'est le seul endroit où il reste un geste à faire |
| **Chargés** | Une carte par exercice : le nom, le contexte, un `Stepper` à `step={1}`, `min={0}` |
| **Poids du corps** | Les `bodyweight`, en liste dense — rien à régler, juste à savoir qu'ils sont classés |

Une **barre de recherche** au-dessus des trois : elle porte sur la page et non sur une
section, parce que chercher « rowing » sans savoir s'il est chargé ou au poids du corps est
exactement la raison d'avoir un champ. Le filtre est **local** — il range des cartes déjà
reçues, il ne décide pas que deux noms désignent le même exercice, ce qui reste
`app/core/text.py`. Le `Combobox` filtre de la même façon et porte la même distinction.

### La carte, et les trois fois où elle a rétréci

```
┌──────────────────────────────────────────┐
│  Rowing                  dans 3 séances  │
│  [ − ]  [  12      kg ]  [ + ]      ☖    │
└──────────────────────────────────────────┘
```

Une ligne d'identité, une ligne de commande, et rien d'autre. Trois décisions l'ont amenée
là, chacune mesurée en capture :

1. **Le libellé « CHARGE » est masqué à l'œil** (`Stepper labelHidden`), pas supprimé : il
   reste lu et il nomme toujours les deux touches (« Charge : augmenter »). Huit fois le
   même mot l'un sous l'autre coûtaient 160 px de défilement et n'apprenaient rien à la
   huitième.
2. **« Au poids du corps » est devenu une icône**, à droite du `+` et centrée sur lui. En
   toutes lettres, il occupait 44 px de haut sur **chaque** carte pour un geste qu'on fait
   une fois par exercice. Le libellé vit dans `aria-label` et `title` — il a quitté la
   hauteur, pas l'interface.
3. **Le bouton « Enregistrer » n'existe que quand il y a quelque chose à enregistrer.** Un
   bouton désactivé en permanence occupe la place et n'apprend rien ; celui-ci apparaît au
   premier appui sur `+`, et sa présence *est* le signal qu'un geste reste.

**Deux colonnes dès 600 px**, une seule en dessous — les deux points de rupture du projet,
tous deux en `min-width`. Pas de troisième colonne à 960 : elle ramènerait le pas-à-pas
sous la largeur où son champ tient ses 44 px.

**La carte est une colonne pleine hauteur, sa commande poussée en bas** (`margin-top: auto`).
Sans ça, un nom qui passe sur deux lignes décale son pas-à-pas par rapport à celui d'à côté
— c'est le défaut de hauteurs inégales que `LogButton` traîne déjà, et il n'entre pas ici en
même temps que la deuxième colonne.

**Un appui confirme.** Le pas-à-pas ajuste une valeur locale ; « Enregistrer » écrit. C'est
ce qui fait qu'un passage de 10 à 16 kg est **une** ligne de journal et **un** point sur la
courbe, pas six. L'enregistrement n'écrit rien si la valeur n'a pas changé.

### Revenir d'un poids du corps

Une seconde icône, sur la ligne dense : elle **n'écrit rien**, elle rend le pas-à-pas. Sans
cette étape, l'appui poserait une charge que personne n'a choisie — et rien ne se défait
dans ce projet. La ligne reste sous « Poids du corps » tant que rien n'est enregistré :
c'est encore son état, et la faire sauter de section avant l'écriture mentirait sur ce que
le fichier porte.

Les quatre états de l'écran : chargement · vide · erreur · données. **L'état vide n'est pas
« aucune charge »** mais « aucune séance » — sans circuit, il n'y a aucun exercice à
charger, et le geste qui coûte le moins est un lien vers `/activite/seances`. Une recherche
sans résultat est un **cinquième** état, distinct : « aucun exercice ne correspond » et
« aucune séance » ne proposent pas le même geste suivant.

### La feuille de détail

Elle s'ouvre à l'appui sur une carte, et porte deux choses, dans cet ordre vertical :

```
  ┌─ Rowing ──────────────────────────────┐
  │                                       │
  │  poids ┤          ╭──14──             │   ← Chart, depuis `history`
  │        ┤     ╭─12─╯                    │
  │        ┤─10──╯                         │
  │        └────────────────────────────   │
  │                                       │
  │  30 derniers jours                    │
  │  ·◦·●·· ··◦●· ·◦··● ●··◦· ··●·◦ ·◦·   │   ← DotRow, depuis `sessions`
  │  2 séances cette semaine              │
  └───────────────────────────────────────┘
```

- Le graphique est le `Chart` existant. **Avec moins de deux points, il ne s'affiche pas** :
  une ligne d'un seul point n'est pas une évolution, et la dessiner laisserait croire à une
  tendance. À la place, la valeur et sa date.
- La ligne de 30 points est un **nouveau composant `DotRow`**, dans
  `components/ui/data.tsx` — la place des composants de données. Un point par jour, son
  intensité selon `count`, et un libellé accessible par point. Sur 390 px, 30 points font
  13 px de pas : c'est un **affichage**, pas une cible — rien ne s'y appuie, donc le
  plancher de 44 px ne s'y applique pas. À vérifier en capture, pas au script.

**Cette feuille s'ajoute à la table `SURFACES`** de
[`scripts/audit-surfaces.mjs`](../scripts/audit-surfaces.mjs), dans ce lot. C'est écrit
noir sur blanc dans `CLAUDE.md` §5, et l'angle mort d'où ce script vient de sortir avait
coûté six surfaces à 32 px.

### L'invalidation

Écrire une charge invalide `keys.loads.all()` **et `keys.circuits.all()`** — parce qu'une
charge change le lien de chaque circuit qui emploie cet exercice, et qu'un lien périmé dans
le cache est un bouton qui ouvre la mauvaise séance.

Elle n'invalide **pas** `CROSS_CUTTING` : aucune mesure n'est écrite, ni agrégat ni
assiduité ne bougent. C'est la conséquence directe de **C4**, et si C4 se rouvre un jour,
cette ligne est la seconde à changer.

---

## 7. Le lien porte la charge

`CircuitService._to_link` lit les charges — **une seule lecture pour toute la liste**,
comme `_items_of` — et pose sur chaque exercice :

| État de la charge | Note du lien |
|---|---|
| `weighted`, 12 kg | `12 kg` |
| `bodyweight` | aucune — un tabata au poids du corps n'a rien à dire de plus |
| `unset` | aucune |

`CircuitExercise` gagne un champ `note: str | None`, qui est **exactement** ce que le lien
porte. L'écran des séances peut donc l'afficher sous l'exercice sans le recomposer, et il
n'y a qu'un endroit au monde où « 12 » devient « 12 kg ».

---

## 7 bis. L'assistant, et l'orthographe d'un exercice

`circuit.create` existe déjà : le modèle nomme des exercices, le serveur fabrique le lien.
Ce qui a disparu avec les 35 noms, c'est le **moyen** pour le modèle de connaître une
orthographe qui affiche une démonstration.

### Pourquoi ce n'est pas une action

La première idée était une action `exercise.search` que le modèle appellerait. **Elle ne
pouvait pas marcher**, et la raison est dans la forme du code : `_run_actions` s'exécute
**après** que le modèle a rendu sa réponse ([`service.py`](../backend/app/domains/assistant/service.py),
« la seconde passe, et il n'y en a jamais de troisième » — `IA-16`). Une recherche déclarée
en action se serait exécutée dans le même paquet que le `circuit.create` qu'elle devait
informer, c'est-à-dire trop tard, et personne ne l'aurait vu échouer.

Le mécanisme qui rend une information **avant** d'agir existe déjà : c'est `need`, et sa
seconde passe est exactement l'aller-retour demandé. Il lui manquait un argument.

### Ce qui a été ajouté

| | |
|---|---|
| `Need` gagne `query` | `nom@jour:recherche`. Le découpage prend la recherche **en premier** — elle est le dernier morceau et peut contenir n'importe quoi, y compris un `@` |
| `Slice` gagne `search` | Synchrone et **sans `FileStore`** : elle lit le catalogue figé du dépôt, pas les données de l'utilisateur. La signature le dit mieux qu'un commentaire |
| La tranche `exercices_cadence` | Sans mot-clé, elle dit quoi demander ; avec, elle rend ≤ 20 noms exacts avec zone et matériel |
| Le libellé de `circuit.create` | Renvoie vers elle. Il promettait encore les noms illustrés |
| `_PERIODS` | Décrit la syntaxe `:` au modèle. **Une possibilité non décrite est une possibilité morte** — c'est la leçon écrite au-dessus des périodes elles-mêmes |

**`IA-09` ne bouge pas d'un pouce.** Le nom de la tranche reste choisi dans une liste
fermée ; seul le mot-clé varie, et il ne désigne aucun fichier — exactement le raisonnement
déjà tenu pour les dates.

### La règle de langue — noms en anglais, tout le reste en français

**Elle a d'abord été écrite à l'envers, et la contradiction valait moins que rien.** En
retirant la liste des 35 noms, la tranche `seances_cadence` disait « écris-les
naturellement, en français si tu veux » pendant que la recherche du catalogue ne répondait
qu'en anglais. Le modèle lit les deux dans la même consigne.

La règle tient en une phrase, et elle est posée aux **quatre** endroits où le modèle la
lit : la ligne de `circuit.create` (lue à chaque tour), la description de la tranche (lue
au moment de choisir), la tranche `seances_cadence` elle-même, et le message rendu quand
on cherche sans mot-clé.

> **Les `name` des exercices s'écrivent en anglais**, repris mot pour mot du catalogue.
> Le nom de la séance, et tout ce que le modèle dit à l'utilisateur, restent en français.

Un test la fixe ([`test_assistant_context.py`](../backend/tests/test_assistant_context.py)) :
les deux lignes doivent dire « anglais » **et** « français », et `seances_cadence` ne doit
plus porter l'ancienne phrase. Deux consignes qui se contredisent valent moins qu'une seule.

**Ce que ça coûte, dit franchement** : les exercices d'un circuit fabriqué par l'assistant
s'affichent en anglais — dans la carte de `/activite/seances`, et dans la page Charges, qui
lit `circuit_exercises.csv`. « push-up » et « mountain climber » à côté d'une interface
française. C'est le prix de la démonstration garantie, et il se paie sur un écran qu'on
regarde entre deux séries.

### La limite qui reste

**Le catalogue est en anglais, et la recherche ne traduit pas.** « pompes » ne rend rien,
et la tranche le dit au modèle plutôt que de le corriger en silence : traduire mot à mot
côté serveur serait une seconde implémentation du rapprochement de Cadence, celle que le §4
s'interdit. Le modèle traduit — c'est ce qu'il sait faire — et le serveur confirme
l'orthographe. Vérifié : `push up`, `pull up`, `burpee`, `mountain climber`, `jump rope`
rendent tous le nom exact en tête.

Certains mots n'ont **aucune** entrée nue — il n'existe ni `plank` ni `squat` seuls dans le
jeu de données. La recherche rend alors les vingt voisins réels, ce qui est le service
attendu : montrer ce qui existe, pas inventer ce qui manque.

---

## 8. L'ordre d'exécution

Chaque phase est vérifiable seule. Les trois premières ne montrent rien à l'écran, et c'est
volontaire : le format est ce qui casse en silence.

| # | Phase | Ce qui la clôt |
|---|---|---|
| 1 | `circuit_link` — le 4ᵉ champ | L'aller-retour sur des notes à `~`, `:`, accents. Et la batterie existante verte **sans retouche** |
| 2 | Le catalogue figé + la recherche | `ILLUSTRATED` n'existe plus nulle part ; `grep -r ILLUSTRATED` est vide |
| 3 | Le domaine `loads` — 2 CSV, schémas, service, 4 routes | Les 8 familles de [`patron-domaine.md` §4](patron-domaine.md) |
| 4 | Le lien porte la charge | Un circuit dont un exercice est à 12 kg produit `…:30s:15:12+kg` |
| 5 | La page `/activite/charges` | Renseigner, corriger, basculer en poids du corps, ouvrir le détail |
| 6 | Vérification | §9 |

---

## 9. Vérifier

`make check` d'abord, sans exception. Puis ce qu'il ne couvre pas, et qui trouve le reste —
**sur les cinq derniers lots, la moitié des défauts sont sortis en regardant la page** :

```bash
node scripts/audit-mobile.mjs   --base http://localhost:<port> --token "<jeton>"
node scripts/audit-surfaces.mjs --base http://localhost:<port> --token "<jeton>"
```

`/activite/charges` entre dans le premier, sa feuille de détail dans la table `SURFACES` du
second, aux trois largeurs — 402, 390, 360. **Puis regarder les captures, dans les deux
thèmes.**

### Ce que la mesure a dit — et ce que l'œil a trouvé ensuite

Mesuré sur une doublure d'API (jeu d'essai couvrant les trois états), à 402 px dans les
deux thèmes, plus 402 / 390 / 360 pour la feuille :

```
/activite/charges        0 cible < 44 px · aucun débordement · 0 zoom · min 12 px · 1784 px
détail d'une charge      0 · 0 · 12 px · ok · non recouvert     — aux trois largeurs
16/16 écrans sans défaut mesurable, dans les deux thèmes
```

**Deux défauts que rien de tout ça n'a vus, trouvés en regardant les captures :**

1. **La ligne de trente points était illisible en thème sombre.** Un jour à une séance
   tombait à 0,675 d'opacité sur `--signal`, c'est-à-dire à peine distinguable d'un jour
   vide. Le plancher est passé à 0,7 dans `DotRow` : ce qu'on vient lire ici est « quels
   jours », pas « combien de fois » — la nuance entre une et deux séances peut être
   discrète, celle entre zéro et une ne le peut pas.
2. **La feuille de détail n'écrivait nulle part la charge courante.** Elle se lisait sur
   l'axe de la courbe, ce qui demande de savoir lequel des cinq points est le dernier — et
   ne se lit pas du tout quand il n'y a pas assez de points pour une courbe. Le chiffre est
   maintenant en tête, en `--t-num-xl`.

### Les trois choses qu'aucun script ne verra

1. **Le clavier système sur une carte de charge.** Un `Stepper` sur 390 px avec le clavier
   ouvert : exactement le genre d'écran que l'émulation rend confortable.
2. **Le lien avec ses notes, ouvert dans Cadence.** C'est le seul endroit où l'on verra si
   « 12 kg » s'affiche bien sous le nom, et s'il tient sur une ligne.
3. **La page avec de vraies données.** Le jeu d'essai a huit exercices ; une base réelle en
   aura peut-être trente, et trois sections de dix cartes est un autre écran que celui-ci.

### Les documents à réviser dans ce lot

- [`cadence.md` §5](cadence.md) — « Le catalogue des 35 noms » ne décrit plus rien.
- [`cadence.md` §11](cadence.md) — « aucune correspondance entre les deux catalogues »
  reste vrai (on ne stocke aucun rapprochement), mais la phrase sur les 35 noms tombe.
- [`CLAUDE.md` §1](../CLAUDE.md) — une ligne vers ce document.

---

## 10. Ce que ce lot ne fait pas

Nommé plutôt qu'oublié.

- **Les tabatas n'ajoutent toujours aucun tonnage.** C4, et son prix est écrit au §1 : le
  journal dira « poids du corps » pour un exercice chargé.
- **Aucune charge n'est relue depuis un lien importé.** C8. Un lien collé qui porte
  « haltères 12 kg » crée le circuit sans la charge ; il faudra la saisir. Deviner `12.0`
  dans un texte libre est la faute silencieuse que le dépôt refuse partout ailleurs.
- **Aucune suppression de charge.** On corrige une valeur, on bascule en poids du corps,
  on ne revient pas à « jamais renseigné ». Le geste manquant est réel ; il vaut mieux
  qu'un second vocabulaire de destruction sur une surface neuve.
- **Aucun filtre par zone du corps ou par matériel à l'écran.** Le catalogue les porte et
  la route les accepte ; aucun écran ne les propose encore. C'est un lot en soi.
- **Le catalogue figé vieillira.** Si le jeu de données grandit, le fichier du dépôt ne le
  saura pas. Le script le régénère en une commande, et c'est le prix admis de l'absence de
  dépendance réseau.
- **La pastille d'un exercice non renseigné contient un tiret seul.** Un chiffre dans une
  pastille se lit ; un tiret dans une pastille ressemble à une case vide. Gardé tel quel
  malgré tout : c'est la **même** pastille qui portera « 12 kg », et la retirer donnerait
  aux cartes non renseignées une structure différente des autres. Vu en capture, laissé.
- **Aucun écran n'a été touché sur un vrai téléphone**, comme tout le reste du projet.
