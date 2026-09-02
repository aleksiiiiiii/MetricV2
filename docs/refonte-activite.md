# Refonte de l'activité — un seul monde d'entraînement, plus la course

L'activité porte aujourd'hui **deux systèmes de musculation** : le journal historique
(`workouts.csv` + `exercises.csv` + `exercise_log.csv`, saisie série par série) et les
circuits Cadence (`circuits.csv`, ouverts dans une autre application). Ce lot n'en garde
qu'un — Cadence — et **laisse la course entièrement en place**.

Ce n'est pas un nettoyage cosmétique : sept autres domaines lisent les fichiers qui
partent. La moitié du travail est de les rebrancher **avant** de supprimer quoi que ce soit.

---

## 1. Les décisions prises

| | Décision | Conséquence |
|---|---|---|
| **R1** | **La course reste entièrement** — écrans, `runs.csv`, `run_splits.csv`, `splits.py`, les allures, les paliers | Le lot ne touche pas à `/activite/courses`. C'est la moitié de l'activité qui ne bouge pas |
| **R2** | La musculation historique **disparaît, code et fichiers** : `workouts.csv`, `exercises.csv`, `exercise_log.csv` | Décision explicite de l'utilisateur. **Rien ne la défait** — §7 impose la copie avant la suppression |
| **R3** | Deux fichiers neufs prennent le relais pour les tabatas déclarés faits | Sans eux, supprimer `workouts.csv` coupe le tableau de bord, l'assiduité et le planning d'un coup — §4 |
| **R4** | L'import Apple **garde sa branche course**, perd sa branche séance | La coupe est déjà dans le code : `kind == "run"` contre `kind == "workout"` |
| **R5** | L'IA **propose**, l'écran laisse **ajuster**, l'appui **écrit** | Le vocabulaire existe (`AiBlock`, l'état `proposed`). Un circuit à dix exercices se corrige mal une fois écrit |
| **R6** | Les neuf pistes d'assiduité se **rebranchent**, elles ne se repensent pas | Elles gardent leur sens ; seule leur source change |
| **R7** | **Supprimer après avoir rebranché**, jamais avant | Chaque phase est vérifiable seule, et les trois premières sont réversibles |
| **R8** | L'application apprend **ce que l'utilisateur possède** — matériel et contraintes — dans un réglage | Sans lui, aucun conseil n'est utilisable : proposer un développé couché à qui n'a ni banc ni barre est pire que de ne rien proposer |
| **R9** | La progression de charge se reconstruit sur `circuit_load_log`, pas sur un tonnage | C'est le seul historique de charge qui survit. `C4` tient : pas de tonnage dans le monde tabata |
| **R10** | Le coach **propose**, il n'écrit jamais | Même vocabulaire que la page de création : `AiBlock` et l'état `proposed`. Un conseil qui s'exécute tout seul n'est plus un conseil |

---

## 2. L'inventaire

### Ce qui reste intact

```
activity/runs.csv · run_splits.csv        la course, entière
activity/circuits.csv · circuit_exercises.csv
activity/circuit_loads.csv · circuit_load_log.csv
splits.py · circuit_link.py · exercise_catalog.py
routes/activity/Run.tsx · Runs.tsx · Circuits.tsx · Loads.tsx · CircuitCard.tsx
actions : run.add · run.delete · circuit.create · plan.add
tranches : seances_cadence · exercices_cadence · activites_recentes · tendances
```

### Ce qui saute

| Fichier | Poids | Pourquoi |
|---|---|---|
| `workouts.csv` · `exercises.csv` · `exercise_log.csv` | 3 CSV | **R2** |
| `routes/activity/Journal.tsx` | 23 ko | La saisie série par série n'existe plus |
| `routes/activity/Catalogue.tsx` | 11 ko | Le catalogue de Metric ; celui de Cadence le remplace |
| `routes/activity/Stats.tsx` | 9 ko | Tonnage, 1RM, volume par groupe — tous dérivés d'`exercise_log` |
| `ActivitySheet.tsx` · `NewActivitySheet.tsx` · `NotesStep.tsx` · `History.tsx` | 62 ko | La saisie et l'historique d'une séance muscu |
| `notes.py` | 267 l. | Lecture des notes manuscrites — elle n'a plus de saisie à remplir |
| La moitié de `stats.py` | ~200 l. | `weekly_volume`, `exercise_load`, `_muscles`, `progress` |
| actions `workout.add` · `workout.delete` · `exercise.create` | 3 sur 14 | Leur cible disparaît |
| tranches `exercices` · `progression_charges` · `detail_seances` | 3 sur 14 | Idem |

**Environ 2 200 lignes backend et 6 écrans.** La course, elle, n'en perd aucune.

> **Correction (phase 3 bis).** Une version antérieure de ce tableau rangeait
> `progress.py` avec `notes.py`, sous l'étiquette « progression de charge ». C'est faux :
> [`progress.py`](../backend/app/domains/activity/progress.py) est **entièrement la
> course** (`ACT-20` — bandes de distance, volume mensuel, fenêtre glissante), et il sert
> `/activite/courses` ainsi que les félicitations de record des rappels. Le supprimer
> casserait ce que **R1** protège. La progression de charge est la méthode
> `ActivityStats.progress()` de `stats.py`, déjà couverte par la ligne suivante.
>
> `_neglected` en sort aussi : la phase 3 bis l'a **rebranché** sur
> `circuit_session_sets.csv` au lieu de le supprimer — c'est le coach qui le lit, pas
> `/activite`.

---

## 3. Le point dur — ce que personne ne voit venir

**Aujourd'hui, « j'ai fait ce circuit » écrit dans `workouts.csv` et `exercise_log.csv`.**
C'est par là qu'un tabata compte dans le tableau de bord, l'assiduité et le suivi du
planning. Supprimer ces fichiers sans les remplacer coupe **sept consommateurs** d'un coup.

### Les deux fichiers neufs

```
activity/circuit_sessions.csv       session_id · circuit_id · date · name · rounds
                                    duration_min · rpe · source
activity/circuit_session_sets.csv   session_id · date · exercise_name · muscle_group
                                    · sets · reps
```

**Pourquoi deux et pas un.** Le second est ce qui rend l'assiduité possible : elle compte
des **séries par groupe musculaire et par jour**. Une liste de groupes sérialisée dans une
cellule de `circuit_sessions` perdrait le compte, et une liste dans une cellule n'est plus
lisible dans un tableur (`STO-02`).

**Pourquoi le nom et le groupe sont dupliqués.** C'est la règle d'`exercise_log`, pour la
même raison (`ACT-06`) : supprimer un circuit doit laisser son historique lisible. Sans la
duplication, une ligne d'historique deviendrait muette dès que son patron disparaît.

**Ce que ces fichiers ne portent pas : aucune charge.** `circuit_loads.csv` reste la seule
autorité sur ce qu'on charge (**C4** de [`charges.md`](charges.md)), et le tonnage reste
hors du monde tabata — un exercice au temps porte `reps = -1`, et le multiplier par une
charge produirait un tonnage négatif.

---

## 4. Les sept consommateurs à rebrancher

Chacun garde sa source « course » et ne change que sa source « musculation ».

| Domaine | Ce qu'il lisait | Ce qu'il lira |
|---|---|---|
| **aggregates** | `TrainingTotals` ← runs + workouts | runs + `circuit_sessions` |
| **heatmap** `_muscle_group` | `exercise_log` | `circuit_session_sets` |
| **heatmap** `_duration`, `_entry_count` | runs + workouts | runs + `circuit_sessions` |
| **heatmap** `_runs` | `runs.csv` | **inchangé** |
| **planning** (assiduité au plan) | `RunRow` + `WorkoutRow` | `RunRow` + `circuit_sessions` |
| **notifications** (rappels) | `RunService` + `WorkoutService` | `RunService` + `CircuitSessionService` |
| **imports** (Apple) | `kind: run \| workout` | `kind: run` seul |
| **assistant** | 6 actions, 5 tranches | 3 actions et 3 tranches partent |

---

## 5. La page de création assistée — `/activite/creer`

**Ce qui existe déjà** : l'action `circuit.create`, la tranche `exercices_cadence` qui donne
l'orthographe exacte d'un exercice, et le formulaire de création de `Circuits.tsx`.

**Ce qui manque** : que la proposition du modèle arrive **dans le formulaire** au lieu d'être
écrite directement.

- On décrit ce qu'on veut en une phrase — « bras 30 min, un haltère de 10 kg ».
- Le modèle rend un circuit complet, affiché **marqué comme proposé** : `AiBlock` pour le
  bloc, l'état `proposed` du `Stepper` pour chaque valeur. Aucune cinquième façon de dire
  « proposé » n'est inventée.
- Chaque ligne s'ajuste — nom, reps, repos, groupe musculaire — et **la marque disparaît
  dès qu'on touche la valeur** : corriger, c'est s'approprier.
- « Enregistrer » écrit, et c'est le seul moment où quelque chose est écrit.

**Le lien reste fabriqué par le serveur** (`D7`). Le modèle nomme des exercices ; il
n'assemble aucune URL — la faute du suffixe `x` est silencieuse.

---

## 5 bis. Le coach — ce que la refonte doit reconstruire

**Le trou de la première version de ce plan.** Toute la capacité de conseil de
l'application — `progression_charges`, `groupes négligés`, `ExerciseProgress`, le 1RM
estimé — est bâtie sur `exercise_log.csv`. Le §2 le supprime. Sans cette section, le lot
retirerait le coach et ne le remplacerait pas.

### Ce qu'il faut lui donner

| Brique | D'où elle vient |
|---|---|
| **Ce que tu possèdes** | Un réglage `equipment` — une liste choisie dans les **28 matériels du catalogue Cadence**, plus un champ libre de contraintes (« pas de banc », « épaule droite sensible »). Ni deviné, ni retapé à chaque conversation |
| **Ce que tu as fait** | `circuit_sessions` + `circuit_session_sets`, §3 |
| **Ce que tu charges** | `circuit_loads` (courant) + `circuit_load_log` (l'historique des décisions) |
| **Ce que tu négliges** | `groupes négligés` **reconstruit** sur `circuit_session_sets` — même règle qu'aujourd'hui (`ACT-16`), autre source |
| **Quand monter** | Nouveau : jours depuis le dernier changement de charge, et nombre de séances tenues à cette charge. Deux chiffres, lus dans `circuit_load_log` et `circuit_sessions` |

### Ce que le coach ne fait pas

- **Il ne calcule pas de 1RM.** Un tabata au poids du corps ou à répétitions n'a pas de
  charge maximale lisible, et l'estimer depuis 15 répétitions à 10 kg serait une valeur
  inventée que l'écran prendrait au sérieux.
- **Il ne décide pas de monter la charge.** Il dit « trois séances tenues à 10 kg sur
  Rowing, dernière hausse il y a 24 jours » — le constat, pas l'ordre. C'est **R10** : le
  chiffre est une mesure, la conclusion appartient à l'utilisateur.
- **Il n'écrit rien.** Aucune charge posée automatiquement, aucune séance créée sans appui.

### Où il se voit

- **Dans la page de création** (§5) : les groupes négligés et le matériel disponible
  partent dans la demande, sans qu'on ait à les taper. « Fais-moi 30 minutes » devient
  répondable.
- **Dans la page Charges** : sur la carte d'un exercice, « 3 séances à 10 kg · dernière
  hausse il y a 24 jours ». Le détail l'a déjà à moitié — la courbe des décisions.
- **Dans l'assistant** : une tranche `progression_tabata` remplace `progression_charges`.

---

## 6. L'ordre d'exécution

Les trois premières phases sont **entièrement réversibles** : rien n'est supprimé.

| # | Phase | Ce qui la clôt |
|---|---|---|
| 1 | Les deux CSV neufs, leur service, `mark_done` y écrit **en plus** de l'ancien | Un circuit déclaré fait remplit les deux mondes ; les huit familles de [`patron-domaine.md`](patron-domaine.md) §4 |
| 2 | Rebrancher les sept consommateurs, **un par un** | Tableau de bord, assiduité, planning et rappels donnent les mêmes chiffres qu'avant sur un circuit fait |
| 3 | Le réglage **matériel et contraintes** (**R8**) | Le profil de l'assistant le porte, et la recherche du catalogue s'y filtre |
| 3 bis | Les indicateurs du coach sur le monde circuit — négligés, séances tenues, dernier changement | Les mêmes règles qu'avant, une autre source. `progression_tabata` **s'ajoute** ; `progression_charges` ne part qu'à la phase 5, comme toute suppression |
| 3 ter | `/activite/creer` — la page assistée, **qui lit ces indicateurs** | Une phrase produit un circuit ajustable, et rien n'est écrit avant l'appui |
| 4 | **La copie de sauvegarde**, à la main | `workouts.csv`, `exercises.csv`, `exercise_log.csv` copiés hors de `activity/`, vérifiés lisibles |
| 5 | Supprimer : code, écrans, routes, tests, actions, tranches | `grep -r "exercise_log\|WorkoutService\|ExerciseService"` ne rend plus rien |
| 6 | Supprimer les trois CSV | **Après** la phase 4, jamais avant |
| 7 | Nettoyage : `/activite`, `CLAUDE.md`, `docs/`, table `SURFACES` | `make check` vert, audit 16/16 |

**La phase 4 n'est pas une formalité.** Le projet n'a aucune annulation et ce sont de
vraies données de santé : la suppression est demandée explicitement, elle se fait après la
copie, et pas dans le même geste.

---

## 7. Vérifier

`make check` d'abord — la batterie perdra ~250 tests avec le code qu'ils couvraient, et
c'est normal ; ce qui ne l'est pas, c'est qu'un test **restant** tombe.

```bash
node scripts/audit-mobile.mjs   --base http://localhost:<port> --token "<jeton>"
node scripts/audit-surfaces.mjs --base http://localhost:<port> --token "<jeton>"
```

Puis **regarder les captures, dans les deux thèmes**. Sur les cinq derniers lots, la moitié
des défauts sont sortis là et zéro de la batterie.

### Les trois choses qu'aucun script ne verra

1. **Le tableau de bord après le rebranchement.** Un `TrainingTotals` qui compte deux fois
   ou plus du tout ne fait tomber aucun test — il affiche un chiffre.
2. **L'assiduité sur une vraie semaine.** Les pistes par groupe musculaire changent de
   source : c'est le genre de bascule qui se voit sur un mois, pas sur une fixture.
3. **La page assistée avec un vrai modèle.** Qu'il rende un circuit *ajustable* et non une
   bouillie est la seule chose qui décide si l'écran sert à quelque chose.

---

## 8. Ce que ce lot ne fait pas

- **Il ne touche pas à la course.** Aucune ligne de `splits.py`, `Run.tsx`, `Runs.tsx`.
- **Il ne repense pas l'assiduité.** Les neuf pistes gardent leur sens et leurs réglages.
- **Il n'ajoute aucun tonnage aux tabatas.** `C4` de `charges.md` tient.
- **Il ne migre rien.** Une séance muscu passée ne devient pas un circuit : rien ne
  correspond — pas de rounds, pas de repos, pas de patron. L'historique est copié puis
  supprimé, il n'est pas converti.
- **Il ne donne aucun écran aux séances tabata.** `circuit_sessions.csv` alimente le
  tableau de bord, l'assiduité, le planning et l'assistant, mais aucune page ne le liste.
  `History.tsx` part à la phase 5 et rien ne le remplace : après la phase 6, « qu'est-ce
  que j'ai fait la semaine dernière » n'a plus de réponse directe sur `/activite`. Restent
  `/assiduite`, dont le détail d'une case donne les exercices du jour, et
  `/activite/courses` pour la course. **C'est une décision, pas un oubli** — mais elle n'a
  pas été prise, et elle se prend avant la phase 5, pas après.
- **Il ne fait pas de programmation sur plusieurs semaines.** Le coach lit ce qui s'est
  passé et propose la séance suivante ; il n'écrit pas un cycle de six semaines. C'est un
  lot en soi, et il demande de tenir un plan dans le temps — ce que `plan.csv` fait déjà à
  moitié, pour autre chose.

---


