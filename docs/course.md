# `/activite/course` — la page spécialisée Course

Plan écrit avant de coder, comme [`CLAUDE.md`](../CLAUDE.md) §1 le demande. Il dit ce qui change, pourquoi,
et ce que ça coûte.

**Ce qui manque aujourd'hui.** [`RunRow`](../backend/app/domains/activity/models.py) garde huit champs — date, distance, durée, allure,
FC, dénivelé, cadence, note. Une course y entre entière et en ressort plate : aucun palier,
aucune dérive d'allure, aucune comparaison entre le début et la fin. La capture Apple porte
trois fois plus d'information que le CSV n'en retient, et c'est cette perte que ce lot
arrête.

---

## 1. Ce que les deux captures apprennent

Course du 21/08/2026, 8,14 km en 40:59. Les deux images sont **cohérentes entre elles**, et
cette cohérence est la seule chose qui permette de vérifier une extraction :

| Contrôle | Calcul | Résultat |
|---|---|---|
| Somme des paliers | 1→8 = 2 415 s, + 44 s | **2 459 s = 0:40:59** = *Workout Time* |
| Distance | 8 paliers pleins + 0,14 | **8,14 km** = *Distance* |
| Allure moyenne | 2 459 ÷ 8,14 | **302 s/km = 5'02"/km** = *Avg. Pace* |

**Le neuvième palier n'est pas un kilomètre.** Il fait `00:44`, soit ~140 m. Apple affiche
quand même une allure — `5'06"/km` — qui est une **extrapolation**, pas une mesure. Le
compter comme un palier plein fausse toute moyenne, tout écart-type, toute « dérive
d'allure ». C'est le piège central de ce lot, et il n'existe que parce qu'on lit une image :
une API le dirait.

**Deux chiffres de calories, pas un.** *Active* 439, *Total* 492. Le second inclut le
métabolisme de base. `RunRow` n'en garde aucun aujourd'hui ; s'il en garde un, il garde
**les deux ou le nommé** — « calories » sans qualificatif est un champ qui veut dire deux
choses.

**La cadence par palier existe** (166 → 174 → 163) et raconte quelque chose que la moyenne
de 168 efface : elle monte de 158 à 174 entre le 3ᵉ et le 7ᵉ km.

---

## 2. Le prompt d'extraction

Il **étend** [`imports/analysis.py`](../backend/app/domains/imports/analysis.py), il ne le remplace pas. Le partage du
travail y est déjà tranché et ne se rediscute pas :

> **Le modèle lit, il ne convertit pas.** La conversion vit dans `app/core/parsing.py`, où
> les miles, les `28:45` et les décimales françaises ont **une seule** grammaire (`ACT-01`).
> **Ce qui n'est pas lisible reste vide** (`IMP-03`) — aucun zéro de remplissage.

Ce qui change : **plusieurs images** au lieu d'une, et les paliers.

```text
Tu lis une ou plusieurs captures d'écran d'une même séance de course (Apple Fitness,
Apple Watch, Strava…). L'une montre le résumé, les autres la liste des paliers
(« Splits »). Réponds par un unique objet JSON, sans phrase avant ni après, sans bloc
de code.

{"kind": "run", "activity": "…", "date": "…", "start_time": "…", "end_time": "…",
 "distance": "…", "duration": "…", "pace": "…", "cadence_spm": "…", "avg_hr": "…",
 "elevation": "…", "active_calories": "…", "total_calories": "…",
 "weather": "…", "humidity": "…", "air_quality": "…",
 "split_length": "…", "splits_seen": 0, "splits_contiguous": true,
 "splits": [{"index": 1, "time": "…", "pace": "…", "cadence_spm": "…",
             "avg_hr": "…", "elevation": "…", "partial": false}],
 "readable": true}

RÈGLE GÉNÉRALE — recopie, ne calcule pas.
Chaque valeur est recopiée telle qu'elle est affichée, unité comprise : « 8.14 KM »,
« 5'02"/KM », « 0:40:59 », « 439 ». Ne convertis aucune unité, ne déduis aucun champ
d'un autre, n'arrondis rien. Mets null sur tout champ absent des captures.
N'invente jamais une valeur pour compléter une ligne.

LE RÉSUMÉ
- "activity" : le titre affiché (« Outdoor Run », « Course en extérieur »).
- "date" : telle qu'affichée (« August 21, 2026 », « Hier »). Ne la calcule pas.
- "start_time" / "end_time" : les deux bornes horaires si une plage est affichée
  (« 7:40 – 8:21 PM » → « 7:40 PM » et « 8:21 PM »). Garde AM/PM tel quel.
- "duration" : le temps de séance (« Workout Time »), pas la plage horaire. Les deux
  diffèrent dès qu'il y a eu une pause.
- "active_calories" et "total_calories" sont DEUX champs distincts. Si un seul chiffre
  est affiché sans qualificatif, mets-le dans "active_calories" et laisse l'autre null.
- "weather", "humidity", "air_quality" : recopie si affichés, sinon null.

LES PALIERS — le point important
- "split_length" : l'en-tête de la liste, recopié (« 1 Kilometer », « 1 Mile »).
- "splits" : UNE entrée par ligne visible, dans l'ordre affiché.
- "index" : le numéro écrit sur la ligne. Lis-le, ne le recompte pas : une capture peut
  être défilée et commencer au palier 7.
- "time", "pace", "cadence_spm", "avg_hr", "elevation" : les colonnes présentes. Toute
  colonne absente de la capture vaut null pour toutes les lignes.
- "partial" : true UNIQUEMENT pour une ligne dont le temps est nettement plus court que
  les autres — typiquement la dernière, qui est le reliquat de distance et NON un palier
  entier. Exemple : huit lignes autour de 05:00 et une dernière à 00:44 → cette dernière
  porte partial: true, les huit autres partial: false. L'allure affichée sur une ligne
  partielle est une extrapolation de l'application, pas une mesure : recopie-la quand
  même, le drapeau dit comment la lire.
- "splits_seen" : le nombre de lignes que tu as effectivement relevées.
- "splits_contiguous" : true si les index vont de 1 à splits_seen sans trou. false si
  une capture manque au milieu ou si la liste ne commence pas à 1.

PLUSIEURS IMAGES
Fusionne-les en une seule liste. Si un même index apparaît sur deux captures qui se
recouvrent, garde-le une seule fois. Ne complète jamais un index que tu n'as pas vu.

"readable" : false si les images ne montrent pas une séance de course.
```

### Ce que ce prompt rendrait sur les deux captures

```json
{"kind": "run", "activity": "Outdoor Run", "date": "August 21, 2026",
 "start_time": "7:40 PM", "end_time": "8:21 PM",
 "distance": "8.14 KM", "duration": "0:40:59", "pace": "5'02\"/KM",
 "cadence_spm": "168", "avg_hr": null, "elevation": "66 M",
 "active_calories": "439", "total_calories": "492",
 "weather": "17°", "humidity": "69%", "air_quality": "2",
 "split_length": "1 Kilometer", "splits_seen": 9, "splits_contiguous": true,
 "splits": [
   {"index": 1, "time": "05:06", "pace": "5'06\"/KM", "cadence_spm": "166", "partial": false},
   {"index": 2, "time": "04:59", "pace": "4'59\"/KM", "cadence_spm": "167", "partial": false},
   {"index": 3, "time": "05:05", "pace": "5'05\"/KM", "cadence_spm": "158", "partial": false},
   {"index": 4, "time": "05:06", "pace": "5'06\"/KM", "cadence_spm": "169", "partial": false},
   {"index": 5, "time": "05:11", "pace": "5'11\"/KM", "cadence_spm": "172", "partial": false},
   {"index": 6, "time": "05:00", "pace": "5'00\"/KM", "cadence_spm": "173", "partial": false},
   {"index": 7, "time": "04:53", "pace": "4'53\"/KM", "cadence_spm": "174", "partial": false},
   {"index": 8, "time": "04:55", "pace": "4'55\"/KM", "cadence_spm": "173", "partial": false},
   {"index": 9, "time": "00:44", "pace": "5'06\"/KM", "cadence_spm": "163", "partial": true}],
 "readable": true}
```

### La relecture, côté serveur — c'est elle qui rattrape le modèle

Le modèle recopie ; **nous vérifions**, et le brouillon porte le verdict :

- **somme des paliers ≈ durée totale** (ici 2 459 s des deux côtés). Un écart de plus de
  quelques secondes veut dire une ligne mal lue ou une capture manquante ;
- **paliers pleins ≈ partie entière de la distance** (8 pleins pour 8,14 km) ;
- `splits_contiguous: false` ou une somme qui ne tombe pas → le brouillon s'affiche
  **avec ses paliers marqués douteux**, il ne se refuse pas. L'utilisateur tranche.
- bornes de vraisemblance déjà posées dans `_BOUNDS` : cadence 30–300, FC 1–260. Un
  palier hors bornes laisse **son champ** vide, pas la course entière.

Rien de tout cela n'est demandé au modèle : un modèle qui vérifie son propre travail
rend un verdict aussi faux que son extraction.

---

## 3. Le stockage — un fichier de plus

`activity/runs.csv` ne change pas de forme, il **gagne des colonnes** ; les lignes écrites
avant portent une cellule vide, ce qui est légitime et non un fichier cassé (`STO-04`).

```
RUN_SPLITS = "activity/run_splits.csv"
```

| Colonne | Pourquoi |
|---|---|
| `run_id` | identifiant **stable** de la course, pas la position de ligne. Une suppression décale les index ; c'est la règle que `workout_id` porte déjà. |
| `index` | le numéro du palier, tel que lu |
| `duration_s` | le temps du palier, en secondes |
| `distance_km` | la longueur **réelle** du palier — 1,0 pour un plein, calculée pour le reliquat |
| `pace_min_km` | recopiée, y compris sur un partiel |
| `cadence_spm`, `avg_hr`, `elevation_m` | nullables, selon les colonnes de la capture |
| `partial` | ce qui empêche toute moyenne de mentir |

**`runs.csv` gagne** : `run_id` (stable), `total_calories`, `start_time`, `end_time`, et
`split_length_km`. Pas la météo — trois colonnes pour un contexte qu'aucun écran ne
demande, ce sera un lot à part s'il en faut un.

---

## 4. La page

Route `/activite/course` — le motif de `/activite/statistiques` et `/activite/catalogue`.
Conteneur `cx('wrap', styles.screen)`, **quatre états** : chargement, vide, erreur, données.

**Tout ce qui suit est calculé par le serveur.** Aucune moyenne, aucun écart, aucun ratio
en TypeScript — c'est l'invariant que le lot précédent vient de retirer du tableau de bord,
et il ne revient pas ici.

1. **L'en-tête** — distance, durée, allure moyenne. Trois chiffres sur une ligne de base
   commune : c'est le défaut corrigé au lot précédent, il ne se refait pas.
2. **La courbe d'allure par palier**, en `Chart`. Axe inversé — une allure basse est une
   course rapide, et une courbe qui descend quand on accélère se lit à l'envers.
   [`chart-axis.ts`](../frontend/src/components/ui/chart-axis.ts) décide du pas des étiquettes ; l'écran ne le calcule pas.
3. **La dérive d'allure** — moyenne de la seconde moitié moins la première, paliers pleins
   seulement. Ici : (4'53" + 4'55") contre (5'06" + 4'59"), soit une **accélération** de
   ~8 s/km. C'est le seul chiffre de cette page qui n'est nulle part dans la capture, et
   c'est ce qui justifie la page.
4. **La cadence par palier**, en `Bars`, avec sa part servie (`ratio`) — jamais un
   `Math.max` à l'écran.
5. **Le tableau des paliers**, lignes à 44 px francs. Le partiel porte un `Badge` qui dit
   ce qu'il est ; son allure s'affiche **grisée**, parce qu'elle est extrapolée.
6. **Les deux calories**, nommées. Jamais un chiffre seul appelé « calories ».

**Sur historique vide** : un tiret et ce que coûte le prochain geste. Jamais un zéro.

---

## 5. Ce que ce lot ne fait pas

- **Pas de trace GPS.** La carte est dans la capture, pas dans les données : une image ne
  rend pas des coordonnées. Ce serait un import de fichier `.gpx`, un autre lot.
- **Pas de FC par palier** tant qu'une capture n'en montre pas — la colonne existe et
  reste vide (`STO-04`), on ne l'invente pas.
- **Pas de météo stockée.**
- **Pas de rétro-remplissage** des courses déjà dans `runs.csv` : elles n'ont pas de
  paliers, et leur en fabriquer serait la pire des valeurs inventées.

---

## 6. Ce qui a été fait, et où cela s'écarte du plan

Écrit **après** le lot, parce qu'un plan qui ne dit pas où il a été démenti ne sert plus à
relire la décision.

**La dérive vaut -4,2 s/km, pas ~8.** Le §4 la calculait sur deux paliers contre deux.
Elle porte sur les **moitiés** des paliers pleins : 1 216 s contre 1 199 s sur quatre
kilomètres chacune. Le palier du milieu est écarté quand le compte est impair — il
appartiendrait autant à l'une qu'à l'autre —, et en dessous de quatre paliers pleins on
rend `None` plutôt qu'une tendance qu'un seul kilomètre lent expliquerait.

**Deux adresses et non une.** `/activite/course` ouvre la dernière course, comme prévu ;
`/activite/course/:id` en ouvre une précise depuis l'historique. S'en tenir à la première
aurait rendu les paliers de toutes les courses antérieures définitivement invisibles —
une donnée écrite que rien n'affiche jamais.

**Le drapeau `partial` ne vient pas du modèle.** Le §2 le lui demande, et la consigne
continue de le faire : le lui faire nommer améliore sa lecture du reste. Mais celui qui
compte se déduit des durées, côté serveur, par la médiane. Un test lui fait déclarer
l'inverse de la vérité sur toute la ligne ; le bon reliquat sort quand même.

**La courbe ne trace que les paliers pleins.** Le §4 ne tranchait pas. L'allure d'un
reliquat de 44 secondes est une extrapolation : la poser sur la même courbe que huit
mesures en ferait un point de mesure de plus. Le tableau la montre, grisée et marquée.
Les barres de cadence, elles, comptent **tous** les paliers — 163 pas par minute sur
44 secondes est une mesure aussi valable que sur cinq minutes.

**Deux défauts trouvés en chemin**, tous deux dans `parsing.py` et tous deux invisibles
jusqu'ici : aucun mois écrit en toutes lettres n'était lu — « August 21, 2026 » rendait
une date vide —, et `5'02"/KM`, la forme réellement affichée, ne se lisait pas non plus.

**Trois défauts trouvés en regardant la page**, aucun par la batterie :

- la phrase des barres de cadence citait « seize pas par minute d'écart », l'amplitude de
  la course de référence — un nombre écrit en dur dans une phrase est une valeur inventée
  comme une autre ;
- la tuile de dérive répétait son chiffre dans son propre détail ;
- à 390 px, le triangle du palier le plus rapide passait à la ligne et rendait deux
  rangées plus hautes que les sept autres.

La colonne « Cadence » du tableau a été **retirée** : à 360 px elle se coupait au premier
chiffre, et les barres juste au-dessus portent déjà la même information en entier.

**Non vérifié à l'œil** : la grille d'aperçus de l'écran d'import à deux captures. Elle
n'entre dans le DOM qu'après un choix de fichier, ce qu'aucune sonde du dépôt ne fait.

---

## 7. Lot C09 — la page de plein droit

Plan écrit avant de coder. Le lot C08 a posé les paliers et une page qui les montre ; ce
lot-ci en fait **la** page d'une course. La contrainte n'a pas bougé et c'est elle qui
dicte tout le découpage : **aucun de ces chiffres ne peut naître dans un `.tsx`**.

### 7.1 Ce que les paliers permettent encore de dire

Rien de ce qui suit n'est sur la capture. Tout se déduit de ce qui y est.

| Chiffre | Ce qu'il dit | Comment |
|---|---|---|
| **Écart-type d'allure** | la régularité, en une valeur | écart-type des allures des paliers pleins |
| **Amplitude** | le plus lent moins le plus rapide | en s/km |
| **Écart à la moyenne**, par palier | quel kilomètre a coûté | allure du palier − allure moyenne |
| **Négative split** | seconde moitié plus rapide | vrai/faux, pas un pourcentage |
| **Vitesse**, par palier | l'autre lecture de l'allure | `60 ÷ allure` |
| **Longueur de foulée** | mètres par pas | `distance ÷ (cadence × durée)` |
| **Dérive de cadence** | la foulée s'accélère-t-elle | même méthode que la dérive d'allure |

**La foulée mérite sa ligne.** `distance ÷ (cadence × durée)` donne 1,18 m par pas sur le
premier kilomètre de la course de référence. C'est la seule grandeur du lot qui combine
deux mesures indépendantes, et c'est aussi celle qu'aucune application n'affiche : elle
dit si un kilomètre plus rapide a été couru en allongeant ou en accélérant la foulée.

### 7.2 Ce que l'historique permet de dire

Une course seule ne se compare à rien. Le service relit `runs.csv` et rend un **contexte** :
rang d'allure et de distance parmi toutes les courses, meilleure allure jamais courue,
moyennes, et les douze dernières sorties pour une courbe de tendance.

**Comparer des allures sur des distances différentes est bancal**, et l'écran doit le dire
plutôt que le taire : le rang s'affiche avec le nombre de courses comparées, jamais comme
un classement absolu.

### 7.3 Ce que l'écran gagne

Un graphique combiné — allure en courbe, moyenne en repère, cadence en contexte —, des
barres divergentes pour l'écart à la moyenne, la foulée par palier, et la tendance des
douze dernières courses.

**Une primitive nouvelle** : `Deviation`, des barres qui partent d'un centre. `Bars` ne
sait afficher qu'une part de 0 à 1, et un écart signé dessiné avec elle perdrait son
signe. Elle va dans `data.tsx` et son module, jamais en style en ligne (§2).

### 7.4 Ce que ce lot ne fait toujours pas

Pas de prédiction de temps de course : extrapoler un 10 km depuis huit kilomètres est un
modèle, pas une mesure, et cette page ne montre que ce qui a eu lieu. Pas de zones de
fréquence cardiaque tant qu'aucune capture n'en porte. Pas de trace GPS.
