# `/activite` — refonte des gestes sur les exercices et les séances

> **Document historique (3 septembre 2026).** Ce plan décrit l'écran d'avant la refonte de
> l'activité : le journal série par série, le catalogue de Metric, les statistiques de
> tonnage. La **phase 5** de [`refonte-activite.md`](refonte-activite.md) a supprimé tout
> cela avec `exercise_log.csv`. Ce qui reste vrai ici est le **raisonnement** — pourquoi ce
> qu'on fait passe devant ce qu'on lit, pourquoi un geste n'est jamais la seule porte,
> pourquoi une correction impossible contamine tout ce qui en dérive. Ce qui est faux est
> l'inventaire des écrans et des routes. Ne pas s'en servir comme description de
> l'existant ; pour ça, c'est le code.

Plan de travail. Il décrit ce qui change dans la mise en page, par quelle porte chaque
geste devient accessible, et ce qu'il faut écrire côté serveur.

Point de départ mesuré : **1 399 lignes, 4 763 px de haut** sur un iPhone 16 Pro, cinq
sections, et la saisie en dernière position. Le relevé de gestes fourni avec la demande a
été revérifié route par route sur `router.py` — il est exact.

---

## 1. Le défaut le plus grave n'est pas la fluidité

Je suis d'accord avec l'ordre proposé dans la demande, et je le durcis : **on ne peut rien
corriger, et l'écran ne le dit nulle part.** Une série tapée de travers — 8 kg au lieu de
80 — n'est pas seulement fausse dans le journal. Elle entre dans `max_series`, donc dans
« Progression des charges », donc dans l'écart affiché à la séance suivante. Une mesure
fausse qu'on ne peut pas retirer contamine tout ce qui en dérive, et le projet n'a **aucune
annulation** pour la rattraper.

Cinq des six gestes manquants existent déjà côté serveur. Il ne manque que le client. Le
travail se fait donc dans cet ordre :

1. Les six fonctions clientes absentes, et les gestes qui les appellent.
2. La seule route manquante : `PATCH /api/activity/exercises/{row_id}`.
3. La mise en page, qui rend le reste atteignable.

---

## 2. Mise en page — ce qu'on fait passe devant ce qu'on lit

### L'ordre actuel

| # | Section | Ce qu'on y fait |
|---|---|---|
| 1 | Cette semaine — 4 tuiles + volume par jour | on lit |
| 2 | Charge et équilibre — tonnage, groupes négligés | on lit |
| 3 | Progression des charges | on lit |
| 4 | Journal de séance | **on écrit** |
| 5 | Saisie — historique, 3 formulaires, catalogue | **on écrit** |

C'est un tableau de bord auquel on a ajouté un formulaire. L'écran devrait être l'inverse :
un établi auquel on a ajouté un tableau de bord. On ouvre `/activite` entre deux exercices,
avec le téléphone dans une main — pas pour consulter un tonnage hebdomadaire.

### L'ordre proposé

| # | Section | |
|---|---|---|
| 1 | **Séance** — le journal, avec son formulaire de série | écrire |
| 2 | **Historique** — les activités, corrigeables | corriger |
| 3 | Cette semaine | lire |
| 4 | Charge et équilibre | lire |
| 5 | Progression des charges | lire |
| 6 | Catalogue et imports | régler |

Cible : le bouton **Consigner** atteignable sous 1 000 px, soit un défilement au pouce au
lieu de cinq. Le chiffre se vérifie à la capture, pas dans ce document.

### Une seconde inversion, à l'intérieur du journal

Aujourd'hui, la liste des séries déjà consignées est **au-dessus** du formulaire. À la
huitième série, le formulaire a dérivé de ~400 px vers le bas — précisément au moment où
on s'en sert le plus. Le formulaire passe donc en premier, et la liste dessous, sous un
intitulé qui la nomme : « Déjà consigné · 8 ». La position du geste répété ne dépend plus
du nombre de fois qu'on l'a déjà fait.

### Trois formulaires quittent le document

`Nouvelle séance`, `Nouvelle course` et le catalogue deviennent des **feuilles**. Ce sont
trois gestes rares — une séance par jour au plus, le catalogue une fois pour toutes — qui
occupent aujourd'hui la moitié de la hauteur des deux sections d'écriture.

Ce n'est pas un mécanisme nouveau : `/assistant` a fait exactement ce déplacement, pour
exactement cette raison, et le commentaire de `MemorySheet` le dit — *« Il occupait le bas
de l'écran, sous le fil : deux formulaires et une liste qu'il fallait dépasser pour revenir
à la question. »* Le carnet y est une liste, avec `Corriger` et `Oublier` par ligne et un
formulaire qui bascule entre création et correction. C'est le patron que je reprends,
sans en inventer un second.

Une feuille n'est pas un geste caché : elle s'ouvre depuis un bouton nommé, présent dans le
document, et au-delà de 600 px elle cesse d'être une feuille pour devenir un panneau centré
(`Sheet.module.css` le fait déjà).

### Découpage du fichier

`Activity.tsx` fait 1 399 lignes et 12 sous-composants ; les feuilles l'emmèneraient
au-delà de 1 800. Il se découpe selon la convention déjà posée par `routes/settings/` :

```
routes/Activity.tsx              l'assemblage et les états de l'écran
routes/activity/Journal.tsx      journal, formulaire de série, lignes de séries
routes/activity/History.tsx      l'historique et ses gestes
routes/activity/ActivitySheet.tsx  créer ou corriger une séance / une course
routes/activity/CatalogueSheet.tsx le catalogue, en entier
routes/activity/AppleImport.tsx  déplacé tel quel, aucune modification
```

`Activity.tsx` continue d'exporter `Activity` : les 33 tests d'écran existants ne changent
pas d'import. Chaque fichier porte son module CSS, comme `Tracks.tsx`.

Je profite du passage pour poser `cx('wrap', styles.screen)` sur le conteneur de page —
l'écran est l'un des neuf qui portent encore l'ancienne convention (§ « Ce qui reste » de
`front.md`).

---

## 3. Chaque geste, et par quelle porte

La règle du projet : **un geste n'est jamais la seule porte**, et **deux appuis pour
détruire**. `SwipeRow` porte déjà les deux — le glissement révèle, le premier appui arme, le
second exécute — et sous `(pointer: fine)` son action s'affiche d'emblée, sans glissement.
Je ne crée aucun second vocabulaire.

| Geste | Porte dans le document | Seconde porte | Route |
|---|---|---|---|
| Consigner une série | formulaire du journal, bouton à `--tap-lg` | — | `POST workouts/{id}/exercises` ✅ |
| **Corriger une série** | appui sur sa ligne → le formulaire bascule en correction | — | `PATCH exercise-log/{id}` |
| **Supprimer une série** | glissement de la ligne | bouton visible au pointeur fin | `DELETE exercise-log/{id}` |
| Créer une séance | bouton en tête du journal | l'état vide du journal | `POST workouts` ✅ |
| **Corriger une séance** | `corriger` sur la ligne d'historique | ligne d'en-tête du journal ouvert | `PATCH workouts/{id}` |
| Supprimer une séance | glissement de la ligne | bouton au pointeur fin | `DELETE workouts/{id}` ✅ |
| Dupliquer une séance | `dupliquer` sur la ligne | — | `POST .../duplicate` ✅ |
| Créer une course | bouton en tête du journal | — | `POST runs` ✅ |
| **Corriger une course** | `corriger` sur la ligne d'historique | — | `PATCH runs/{id}` |
| Supprimer une course | glissement de la ligne | bouton au pointeur fin | `DELETE runs/{id}` ✅ |
| **Voir le catalogue** | feuille « Gérer le catalogue » | — | `GET exercises` ✅ |
| **Renommer, regrouper** | `Corriger` sur la ligne de la feuille | — | **`PATCH exercises/{id}` — à écrire** |
| **Retirer du catalogue** | `Retirer` sur la ligne, armé puis confirmé | — | `DELETE exercises/{id}` ✅ |

Les six fonctions clientes absentes s'ajoutent à `features/activity/api.ts` — types et
appels seulement, aucun calcul —, plus `readRun` : corriger une course demande sa FC et sa
note, que l'historique ne porte pas. Relire la ligne avant de la corriger donne au passage
un jeton frais pour l'`If-Match`.

### Corriger, c'est le formulaire qui bascule

Pas de second formulaire de correction : c'est le patron de `/corps` et du carnet de
`/assistant`. Le même formulaire, un état `editing`, un titre et un libellé de bouton qui
changent, un `Annuler` en `quiet`, et une `key` sur le jeton pour que les champs se
réinitialisent quand on passe d'une ligne à l'autre.

Pour une série, ce formulaire est celui du journal — il est déjà à l'écran, juste au-dessus
de la liste. Un `scrollIntoView` l'amène sous les yeux si la liste est longue, comme
`logRef` le fait déjà pour le journal.

---

## 4. Les trois flux

### Le régime n'est pas le même pour les trois

Le projet a déjà tranché cette asymétrie, et ce n'est pas dans une charte mais dans du code
— `actions.py:94`, la documentation d'`Undo` : *« l'annulation est donc un
`DELETE /api/{domain}/{row_id}` avec la garde `If-Match` »*. Une **addition se défait** :
c'est la suppression que l'utilisateur ferait lui-même. Une **suppression ne se défait
pas** — il n'y a rien à réécrire, et le projet n'a pas de corbeille.

| | Coût d'une erreur | Ce que le geste demande |
|---|---|---|
| Ajouter | réparable | un appui, rien à confirmer |
| Corriger | réparable, mais la valeur d'avant disparaît | un appui, l'ancienne valeur sous les yeux jusqu'à l'envoi |
| Supprimer | irréparable | deux appuis |

Cela évite le travers inverse de l'écran actuel : demander une confirmation partout
finirait par la faire ignorer là où elle compte.

### Ajouter

**Deux valeurs inventées à retirer du formulaire de série.** `sets: '3', reps: '8'` sont
écrits en dur (`Activity.tsx:348`) : toute série commence à 3×8, quel que soit l'exercice.
Or `catalogue()` rend déjà `last_sets` et `last_reps` — des valeurs **réelles**, affichées
en texte deux lignes plus bas et jamais employées. **Choisir un exercice remplit donc les
séries et les réps avec sa dernière performance réelle**, et laisse la **charge vide** :
c'est elle qui progresse, c'est le seul nombre qui vaut d'être tapé, et les pastilles
« charges récentes » sont déjà là pour la remplir en un appui.

> Sans le trait discontinu du `Stepper` : `proposed` veut dire « un modèle a suggéré ceci »,
> et le projet n'a qu'une façon de le dire, employée par quatre écrans. Un relevé rappelé
> n'est pas une proposition — le marquer comme telle affaiblirait les quatre.

**Une séance exige sa durée avant d'exister.** `WorkoutPayload.duration_min` est
obligatoire et le bouton reste désactivé tant qu'elle est vide : pour consigner sa première
série, il faut déjà savoir combien de temps la séance a duré. Aujourd'hui cela force un
nombre inventé dans `week.minutes`. C'est ce que le `PATCH` débloque : le champ reste
obligatoire et vide — aucune machine ne devine à la place —, la feuille dit
« approximative, elle se corrige à la fin », et l'en-tête du journal ouvert porte le
`corriger` qui y mène. Rendre la durée facultative était l'autre issue : elle propage un
`None` dans `WeekTotals`, `DayVolume` et le calcul de `rest`, pour un gain que la correction
donne déjà.

**L'exercice manquant, en pleine séance.** Aujourd'hui : descendre tout l'écran, déclarer
l'exercice, remonter, le re-choisir. Sous le sélecteur, « cet exercice n'est pas dans la
liste ? » ouvre la feuille du catalogue sur le champ du nom ; à la création la feuille se
referme et **le nouvel exercice est sélectionné**. La feuille rend le focus d'où il venait,
elle le fait déjà.

**Le sélecteur ne passe pas l'échelle.** Vingt-cinq exercices font treize rangées de
`LogButton`, soit ~730 px au-dessus des pas-à-pas. Une `ChipStrip` de groupes musculaires
filtre la grille — le groupe est déjà sur chaque entrée, filtrer est de la présentation.
Sans filtre par défaut. (J'écarte le tri par récence : il changerait l'ordre de la liste
sous les doigts d'une fois sur l'autre, et l'ordre appartient au serveur.)

**Les deux derniers menus natifs partent.** Le projet a déjà tranché, à `Activity.tsx:458` :
*« La liste déroulante native demandait un appui, un panneau système, un défilement et un
second appui — pour le geste le plus répété de l'écran. »* L'argument vaut identiquement
pour le type de séance (`datalist`) et le groupe musculaire (`<select>`). Le groupe est une
énumération fermée de neuf valeurs : pastilles seules. Le type doit rester libre (`ACT-03`) :
pastilles des sept suggestions **plus** le champ libre. `.select` et `.field` quittent le
module.

**La date vient de l'horloge du téléphone.** `isoDay(new Date())` dans les deux formulaires,
dans la duplication, et pour `today` qui met en avant la colonne du jour. C'est l'heure
locale et non `toISOString`, donc pas le défaut UTC — mais la règle du projet est que le
jour **vient du serveur**, et `/nutrition` a été corrigé pour exactement cela à la passe D.
`ActivityOverview` ne porte pas de `today` : je l'ajoute au schéma, et l'écran le lit.

### Corriger

**Une correction montre ce qu'elle remplace.** Sans annulation, le dernier moment pour
repérer une erreur est avant l'envoi. Le formulaire en correction porte la valeur intacte en
`mono` : « était : 80 kg · 3×8 ». Une ligne, avec des données déjà chargées.

**Le titre nomme la ligne** — « Corriger la séance du 12 août », jamais « Corriger » nu.
C'est le défaut contre lequel le carnet de `/assistant` met déjà en garde : deux
« Corriger » indistincts à la synthèse vocale.

**L'exercice d'une série reste corrigeable.** `update_entry` accepte `exercise_id` : une
série consignée sur le mauvais exercice se répare. Le sélecteur reste donc actif en mode
correction — c'est l'erreur la plus fréquente après une charge fausse.

**Un conflit n'est pas une erreur de l'utilisateur.** `id` est la position de la ligne dans
le fichier : supprimer la ligne 3 décale toutes les suivantes. La garde `If-Match` rattrape
(409, rien n'est écrit), mais « Suppression impossible » est un mauvais message alors que le
serveur en donne un bon — « Recharge la donnée avant de la modifier. » Décision sur
`code === 'conflict'` : invalider, et afficher **le message du serveur en place** plutôt
qu'un toast qui passe. Et la feuille de correction **ne se referme pas** sur un conflit :
elle garde ce qui a été tapé.

### Supprimer

**Dire ce qu'on emporte.** Supprimer une séance purge ses séries (`ACT-04`). L'état armé dit
aujourd'hui « Confirmer ? », les mêmes mots qu'elle emporte zéro ou douze séries.
`ActivityItem` ne porte pas ce compte : j'ajoute `entries: int` au schéma — compté par le
serveur — et la ligne le dit d'elle-même, « musculation · 78 min · 8 séries ». Le coût se
lit **avant** d'armer, ce qui vaut mieux qu'un libellé plus long dans un panneau de 96 px.

**Retirer du catalogue n'est pas supprimer.** `ExerciseService.delete` laisse le journal
intact : l'historique survit (`ACT-06`). Le mot doit suivre l'acte — « Retirer » et non
« Supprimer », et la ligne dit ce qui reste : « 34 séries conservées ». `actionLabel` et
`confirmLabel` sont des paramètres de `SwipeRow` ; aucun composant nouveau.

**Ce que je ne propose pas : ni corbeille, ni « Annuler » en bandeau.** `notify(message,
tone)` ne porte pas d'action, et la seule annulation du projet défait des **additions**.
Une vraie annulation de suppression demande une corbeille ou une réécriture avec sa
provenance : c'est une décision de stockage (`STO-*`), pas une décision d'écran. Deux appuis
restent la réponse.

---

## 5. Le catalogue

Il est aujourd'hui en ajout seul et **n'affiche pas ce qu'il contient**. La feuille le
reprend en entier, sur le modèle de `MemorySheet` :

* une ligne par exercice : le nom, son groupe en `Badge`, et sa dernière performance —
  `catalogue()` la rend déjà (`ACT-08`), rien à calculer ;
* `Corriger` charge la ligne dans le formulaire du bas, qui passe de « Ajouter » à
  « Enregistrer » ;
* `Retirer` s'arme puis se confirme ;
* le formulaire d'ajout reste en bas, inchangé.

Les quatre états valent pour la feuille comme pour un écran. L'état vide dit ce que coûte
le prochain geste — « Un exercice déclaré, et le journal sait quoi te proposer » — et
n'affiche aucun compte inventé.

Dans le document, la carte se réduit à son titre, au nombre d'exercices déclarés et au
bouton qui ouvre la feuille. La liste vit là où sont les actions ; l'afficher deux fois
donnerait deux endroits où chercher.

---

## 6. Côté serveur

### `PATCH /api/activity/exercises/{row_id}`

Le routeur reste mince, comme ses voisins :

```python
@router.patch("/exercises/{row_id}", response_model=Exercise, summary="Corriger un exercice")
async def update_exercise(
    row_id: RowId, payload: ExercisePayload, store: StoreDep, if_match: IfMatch = None
) -> Exercise:
    return await ExerciseService(store).update(row_id, _token(if_match), payload)
```

`ExercisePayload` existe déjà et valide le groupe musculaire contre `MuscleGroup`. Garde
`If-Match` obligatoire, absent traité comme un conflit — jamais comme une permission.

**Le point dangereux de tout le lot tient en une ligne** : `ExerciseRow.id` — le
`exercise_id` stable — doit **survivre** à la correction. C'est la clé à laquelle
`exercise_log.csv` rattache tout l'historique. En régénérer un orphelinerait des années de
relevés, sans erreur, sans message. `WorkoutService.update` fait déjà exactement cela pour
`id` et `source` ; je reprends le même geste et le même commentaire.

### Ce que devient l'historique quand un exercice est renommé

C'est la question posée, et elle a une réponse mesurable. `exercise_log.csv` **duplique**
`exercise_name` et `muscle_group` à côté de `exercise_id`. Trois lecteurs se servent de la
copie du journal, jamais du catalogue :

| Lecteur | Ce qu'il lit |
|---|---|
| `stats.py:396` — progression | `name=latest.exercise_name` |
| `stats.py:274`, `296` — tonnage par groupe, groupes négligés | `model.muscle_group` |
| `heatmap/sources.py:152` — détail d'une journée | `label=row.model.exercise_name` |

Donc, **sans rien de plus**, corriger « Développé couhé » en « Développé couché » laisse la
barre de progression étiquetée avec la faute, pendant que le sélecteur juste au-dessus
affiche la forme corrigée. Le même exercice, deux noms, le même écran — et la bascule se
ferait toute seule à la série suivante, ce qui est pire qu'une incohérence stable.

Changer un groupe musculaire est plus grave encore : le tonnage passé resterait dans
l'ancien groupe et le futur irait dans le nouveau. Un exercice compté dans deux groupes,
« Groupes négligés » faussé des deux côtés, et les pistes d'assiduité coupées en deux.

**Décision : la correction répercute les copies du journal** pour ce `exercise_id`. La
duplication existe pour qu'un exercice **supprimé** garde son historique lisible (`ACT-06`,
`STO-02`) — pas pour figer un nom contre sa propre correction.

Et parce que le projet n'a pas d'annulation, la feuille l'annonce **avant** le geste :
« Corriger le nom ou le groupe met aussi à jour les 34 séries déjà consignées. » Le compte
vient du serveur.

La limite, énoncée franchement : cela fait du renommage une **correction**, pas un
recyclage. Renommer « Développé couché » en « Développé incliné » pour économiser une
entrée réétiquetterait à tort les séries passées. Le bon geste est alors un nouvel
exercice, et la phrase ci-dessus dit laquelle des deux choses est en train de se produire.

### L'ordre des écritures

La ligne du catalogue part **en premier**, sous garde ; la répercussion ensuite. C'est
l'ordre de `WorkoutService.delete`, et pour la même raison : si la garde refuse, rien n'a
bougé. Si la répercussion échoue après coup, le journal garde ses anciennes copies et
rejouer la même correction converge — le projet n'a pas de transaction, et cela vaut d'être
écrit dans le code plutôt que découvert.

### Une méthode de dépôt

`CsvRepository` sait supprimer en masse (`remove_where`) mais pas modifier en masse.
J'ajoute `update_where(matches, apply) -> int` juste à côté : une lecture fraîche, une
écriture, et la même justification que sa voisine — la ligne visée n'est pas désignée par
l'utilisateur, elle est déduite d'une correction qu'il a déjà confirmée, donc pas de garde
par jeton ligne à ligne. La mettre dans le dépôt plutôt que dans le service évite qu'un
`overwrite` du fichier entier soit écrit à la main dans un domaine.

### Deux champs de schéma, réclamés par le flux

Les deux viennent du §4 et pèsent quelques lignes chacun :

* **`ActivityOverview.today`** — le jour, dans le fuseau local du serveur. L'écran cesse de
  dater ses formulaires et sa colonne du jour à l'horloge du téléphone. `today_local()`
  existe et alimente déjà `overview()`.
* **`ActivityItem.entries`** — le nombre de séries rattachées à une séance, compté par
  `ActivityStats` en même temps que le reste. C'est ce qui permet à une ligne de dire ce que
  sa suppression emporte, sans que le client ne compte quoi que ce soit.

### Les tests

Backend, sur les familles de `patron-domaine.md` :

- l'écriture réelle dans le CSV — en-tête, ordre des colonnes, accents ;
- **`exercise_id` inchangé après correction** ;
- les copies du journal suivent, **et seulement pour cet exercice** ;
- `progress()` nomme l'exercice tel que corrigé ;
- un changement de groupe déplace le tonnage passé ;
- `If-Match` absent → 409, fichier intact ;
- `If-Match` périmé → 409, fichier intact ;
- groupe musculaire inconnu → 422 ;
- correction d'un exercice sans aucune série au journal ;
- `today` suit le fuseau du serveur, et `entries` compte les séries de la bonne séance.

Frontend : pour chacun des six appels, que le jeton lu sur la ligne est bien celui renvoyé
en `If-Match` ; que corriger une série pré-remplit le formulaire et envoie un `PATCH` et
non un `POST` ; que chaque destruction demande deux appuis ; les quatre états de la feuille
du catalogue.

---

## 7. Ce que je ne fais pas, et pourquoi

* **Aucune action d'assistant `exercise.update`.** Le catalogue d'actions de `actions.py`
  est un contrat à part, avec son schéma et son `Undo` ; rien dans la demande ne le
  concerne. Nommé ici pour ne pas l'oublier.
* **Déplacer une série d'une séance à l'autre.** `update_entry` préserve délibérément
  `workout_id` et `date` ; je ne touche pas à ce choix.
* **Transformer une course en séance.** Deux fichiers, deux identifiants. La feuille
  propose le choix à la création, pas à la correction.
* **Deux calculs métier côté client, trouvés au passage.** La tuile « Tonnage » somme
  `data.muscles[].volume_kg` dans l'écran (`Activity.tsx:1240`), et les deux `Bars`
  dérivent leur ratio d'un `Math.max(...)`. Le premier est un chiffre métier calculé côté
  client, ce que le §7 de `front.md` interdit — il devrait venir du service. Hors périmètre
  de ce lot ; signalé pour être traité pour lui-même.

---

## 8. Vérification

1. `make check` — ruff, ruff format, mypy, pytest, prettier, eslint, tsc, vitest.
2. `node scripts/audit-mobile.mjs --base … --token …`, puis la même passe en `--theme light`
   avec ses captures à part : sans cela l'audit ne regarde qu'une moitié de l'application.
3. **Puis regarder les captures.** Ce que je vise en particulier, parce qu'aucune mesure ne
   l'attrape : la feuille par-dessus la barre d'onglets à 402 × 874 avec le clavier levé ;
   la liste « déjà consigné » à douze séries ; le catalogue vide ; et le texte de la feuille
   de correction sur un exercice à 34 séries.

### Le risque tactile nommé — tranché, il n'existe pas

Rendre la ligne d'une série tapable place un bouton dans `.swipeContent`, qui appelle
`setPointerCapture` dès le `pointerdown` (`lib/swipe.ts:163`). Quand une capture est
active, Chrome peut dispatcher le `click` sur l'élément capturant plutôt que sur le bouton
intérieur : au doigt, l'appui de correction n'aurait jamais démarré.

**Vérifié avec un vrai pointeur tactile** — `Input.dispatchTouchEvent`, et non
`dispatchMouseEvent` : `touchOnly` désactive le geste à la souris, ce qui aurait masqué
exactement le défaut cherché. Résultat : l'appui atteint le bouton, la correction s'arme,
et le glissement continue de révéler la suppression sur la même ligne. Les deux gestes
cohabitent. Aucun changement à `lib/swipe.ts`.

---

## 9. Ce que « regarder » a rapporté

Six défauts, tous sortis des captures et **aucun d'une mesure** — l'audit annonçait
`12/12 sans défaut mesurable` dans les deux thèmes avant comme après.

| Ce qui n'allait pas | Pourquoi c'était faux |
|---|---|
| `Nouvelle séance` en `ghost`, `Nouvelle course` en `quiet` | deux portes de même rang, dont l'une passait pour un lien |
| `Corriger` et `Retirer` du catalogue sans bordure | ils se lisaient comme du texte posé sous la ligne |
| « Cet exercice n'est pas dans la liste ? » sans bordure | une légende sous la grille, et rien ne disait qu'on pouvait appuyer |
| …et large comme la carte, collée aux deux bords | nommer l'action vaut mieux que poser la question : « Déclarer un exercice » |
| « était : … » en tête d'un formulaire haut | hors de l'écran au moment de l'appui, donc invisible quand elle sert |
| Le formulaire du catalogue, sous huit lignes | appuyer sur `Corriger` ne montrait rien du tout |

Les deux derniers sont le même défaut : **une correction qui ne se voit pas est une
correction qu'on croit n'avoir pas déclenchée.** Les deux formulaires amènent désormais
sous les yeux ce qui décide — les chiffres, le bouton, et la valeur qu'ils remplacent.

### Ce qui reste, et que je n'ai pas touché

**`LogButton` se casse sur les noms longs.** « Soulevé de terre » tient sur trois lignes
avec son groupe en regard, « Traction · poids du corps » aussi, et les tuiles de la grille
prennent des hauteurs inégales. C'est visible sur les captures. Ce n'est pas une régression
— la grille et le composant n'ont pas changé — mais c'est une correction dans
`primitives.tsx`, qui vaut pour la saisie rapide autant que pour cet écran. À traiter pour
elle-même plutôt qu'en passant.

**Le champ de date affiche `08/11/2026` en headless.** C'est la locale du navigateur de
test (`en-US`) rendant un `<input type="date">`, pas une donnée fausse : le serveur envoie
bien `2026-08-11`. Sur un appareil français, l'ordre est celui attendu. Tous les écrans du
projet sont dans ce cas.
