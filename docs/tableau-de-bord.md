# Refonte du tableau de bord — plan

Plan écrit **avant** le code, comme les six autres documents de `docs/`. Il dit ce qui
change, pourquoi, et ce que ça coûte.

Point de départ : `Dashboard.tsx` (507 l.) et son module (174 l.), un seul appel
`aggregatesApi.dashboard()`, quatre tuiles de poids égal et une carte « Assistant » qui ne
contient que trois boutons.

Le reproche, dans les mots de l'utilisateur : « **c'est très neutre, on ne comprend pas
grand-chose, et on ne sait pas où on va** ». L'écran dit *où j'en suis* et jamais *ce que ça
vaut*, ni *ce qui vient ensuite*.

---

## 1. Les cinq décisions prises avant d'écrire

| Question | Décision |
|---|---|
| Quand la lecture du jour est-elle produite | **Ordonnanceur + bouton de repli** |
| Ce qui manque pour « savoir où on va » | **Objectif actif**, **prochaine séance**, **écart aux cibles du jour** |
| D'où vient la hiérarchie | **La journée comme une liste à finir**, enrichie de chiffres et de texte |
| Périmètre | Carte + backend + **les trois défauts de cet écran** |
| Cible | **Mobile d'abord, iPad ensuite** — 390 px plancher, 402 cible, 820 et 1180 ensuite |

## 2. La piste `WeeklyInsightService` : la recette, pas la donnée

Elle a été proposée comme source du message. **Elle ne l'est pas**, pour trois raisons
mesurables — et elle reste malgré tout le bon patron.

**Il n'y a presque jamais de contenu.** `generate` part d'un `POST` déclenché depuis
`/objectif`, et `keep` n'écrit que sur un second appui. `insights/weekly.csv` est vide tant
que les deux gestes n'ont pas eu lieu. Une carte d'accueil qui en dépend est blanche.

**Le bilan porte sur la semaine révolue** — jusqu'à treize jours de retard le dimanche. La
plainte est « je ne sais pas où je vais **ce matin** ».

**Sa forme ne rentre pas.** `WeeklyReview` porte `progress[]`, `setbacks[]` et `action` ;
conservé, `to_summary()` les aplatit en une phrase continue pour tenir dans une cellule de
tableur. Affiché tel quel sur une carte, c'est un mur de texte.

**Ce qui se recopie, c'est son découpage**, et il se recopie à l'identique : un condensé
factuel assemblé par le serveur, une consigne JSON stricte, une relecture dans un module
**pur** qui ne lit aucun fichier, un objet rendu, une ligne CSV par période. `brief/` est
bâti sur ce plan et sur aucun autre.

**Une correction à la prémisse de coût** : `AiService` n'interroge que le catalogue
**gratuit** d'OpenRouter (`free_models()`). L'appel ne se paie pas ; ce qui se paie est la
latence — jusqu'à cinq modèles en cascade — et le non-déterminisme. C'est pourquoi la
lecture est **produite une fois par jour et rangée**, et jamais au chargement de l'écran.

## 3. Le vocabulaire existait déjà dans la charte

`GuidelinesUI.html` §10 « **Lecture assistée** » (l. 653-666) contient exactement cette
carte : bloc `.ai`, tag « Lecture du 26 juillet », un paragraphe court dont les chiffres
sont en gras, deux boutons dessous. C'est `AiBlock` avec `tag="Lecture du <jour>"`.

**Aucune cinquième façon de dire « proposé » n'est inventée.** Rendre le corps du bloc
tappable est une **variante d'apparence d'un composant existant** : elle va dans
`primitives.tsx` et son module, jamais en style en ligne dans l'écran.

## 4. L'écran, de haut en bas

À 390 px. Le conteneur passe enfin à `cx('wrap', styles.screen)`.

```
PageHead                     mercredi 19 août · Tableau de bord

● LECTURE DU JOUR            AiBlock, corps tappable → ouvre le fil semé
  « … »                      [ Ouvrir l'assistant ] à côté, sans le message

IL RESTE AUJOURD'HUI         la liste à finir — eau, protéines, suppléments, séance
  ○ Eau        1,4 / 2,5 L   jauge + « encore 1,1 L »
  ○ Protéines   96 / 150 g   jauge + « encore 54 g »
  ● Suppléments    3 / 3     « fait »
  ○ 18:30 · Haut du corps    la séance prévue du jour, ou la prochaine

OÙ JE VAIS                   objectif actif : ratio, jauge, résumé chiffré, échéance
                             à défaut : la cible de poids ; à défaut : l'état vide

78,4 kg   2:10   12 jours    la bande de chiffres — sans carte, trois colonnes
                             (l'hydratation a quitté la bande : elle est dans la liste)

TENDANCE                     graphique croisé, sept derniers jours
ENTRAÎNEMENT                 huit dernières semaines, répartition
```

### Ce qui disparaît

* La carte « Journée » de la section Tendance : ses trois jauges **sont** la liste à finir,
  remontées d'un écran et demi.
* La tuile « Hydratation » de la bande : elle disait le total quand la liste dit le
  restant. Deux lectures de la même mesure à deux endroits, c'est une de trop.
* Le `Stat` « Objectif » du bas de page : il devient le repli de « Où je vais ».
* La carte Assistant sans contenu : ses trois boutons se répartissent entre la lecture du
  jour (ouvrir) et le pied de la section (discussions, mémoire).

### Les quatre états, sur chacune des trois surfaces nouvelles

| Surface | Chargement | Vide | Erreur | Données |
|---|---|---|---|---|
| Lecture du jour | ligne de squelette dans le bloc | « pas encore de lecture » + un bouton | message du serveur + réessayer | le message + les actions |
| Il reste aujourd'hui | avec l'écran | jamais vide : les cibles existent toujours | avec l'écran | les quatre lignes |
| Où je vais | avec l'écran | « aucun objectif » + lien vers `/objectif` | avec l'écran | ratio, jauge, échéance |

**Zéro n'est pas une mesure** : une ligne dont le fait du jour vaut `0` affiche `—` et
l'objectif, jamais « 0 / 2,5 L » qui se lirait comme un relevé.

**Si l'IA est indisponible** (`IA-07`), la carte de lecture **n'apparaît pas du tout** — pas
de bouton mort, pas d'explication à lire. Les portes vers l'assistant restent.

## 5. Backend

### 5.1 Domaine `brief/` — la lecture du jour

Quatre fichiers plus un module pur, selon `docs/patron-domaine.md`.

| Fichier | Rôle |
|---|---|
| `models.py` | `BriefRow` → `insights/brief.csv` : `day`, `created`, `message`, `thread_id`, `source` |
| `compose.py` | **pur** : la consigne, l'assemblage du prompt, la relecture. Aucun fichier, aucune horloge |
| `schemas.py` | `BriefView` — `day`, `state`, `message`, `basis[]`, `thread_id` |
| `service.py` | lit, génère, sème le fil |
| `router.py` | `GET /brief` · `POST /brief` · `POST /brief/thread` |
| `scheduler.py` | `BriefScheduler` — `tick()` fait une passe, `run()` boucle |

**Le condensé n'est pas réécrit** : `assistant.context.build` le produit déjà, ligne à
ligne, à partir des services qui détiennent chacun leur règle. Deux condensés divergeraient
au premier ajout — c'est l'argument écrit dans `goals/service.py`, il vaut ici mot pour mot.
`adherence` est **fourni** par l'appelant (routeur ou ordonnanceur), jamais recalculé :
`PLAN-06` en détient l'unique implémentation.

**`GET` lit, `POST` écrit.** Un `GET` qui générerait fausserait le cache autant que la
promesse du projet. `GET` rend `state: 'absent'` tant que le jour n'a pas sa ligne.

**Pourquoi `POST` écrit sans second appui**, alors qu'un objectif et un bilan en demandent
un : « rien sans validation » protège les **données de l'utilisateur** — ses pesées, ses
repas, ses objectifs. Une lecture du jour n'en est pas une : c'est un cache daté, du même
genre que `notifications/sent.csv`. La ligne se supprime, elle ne se corrige pas.

**Le fil est semé paresseusement.** `POST /brief/thread` crée, **au premier appui
seulement**, un fil dont le message n°0 est `role=assistant` et porte la lecture, puis rend
son identifiant. Le modèle voit alors son propre message dans `_history` et répond vraiment
à ça. Créer le fil à la génération remplirait « Discussions » de lectures jamais ouvertes.

**L'ordonnanceur est indépendant des notifications.** `ReminderScheduler` ne démarre qu'avec
une paire VAPID ; celui-ci démarre dès que l'IA et le stockage sont configurés. Même
découpage testable : `tick()` prend l'instant qu'on lui donne et ne dort jamais, `run()`
boucle. Une passe par heure ; elle ne génère que si le jour n'a pas déjà sa ligne et que
l'heure locale a dépassé le seuil du matin.

### 5.2 `aggregates` — trois champs de plus sur `DashboardView`

```python
day: DayPlan                    # les lignes de « il reste aujourd'hui »
goal: ActiveGoal | None         # l'objectif en cours, avec sa progression calculée
next_session: PlannedSession | None
```

Les restants **existent déjà** : `HydrationStats.remaining_ml`,
`DayTotals.protein_remaining_g`, `DayRatio.complete`. `DayPlan` les assemble en lignes
ordonnées et **écrit la phrase française du restant côté serveur** — « encore 1,1 L » — au
même titre que `GoalProgress.summary` et `.basis`.

`GoalService` et `PlanningService` s'importent **dans le corps de la fonction** et non en
tête de module : `goals/service.py` importe `aggregates.service` pour le registre `METRICS`,
et une flèche en retour poserait un cycle. C'est le procédé déjà employé par
`context.plan_lines`, et il est commenté sur place.

### 5.3 Le défaut de calcul métier côté client

`Dashboard.tsx:451` dérive la part de chaque barre d'un `Math.max` sur la série des huit
semaines. Un maximum sur une série **est** une dérivation. `WeekVolume` gagne donc un champ
`ratio`, calculé dans `activity/stats.py` là où les semaines sont construites.

## 6. Frontend

| Fichier | Ce qui change |
|---|---|
| `features/brief/api.ts` | **nouveau** — types et appels, aucun calcul |
| `lib/query.ts` | la clé `brief` |
| `features/aggregates/api.ts` | les trois types nouveaux |
| `components/ui/primitives.tsx` | `AiBlock` accepte un corps tappable |
| `routes/Dashboard.tsx` | restructuré ; découpé en `routes/dashboard/` s'il passe ~800 l. |
| `routes/Dashboard.module.css` | la liste, la bande de chiffres, la carte de lecture |

**Aucune couleur en dur, aucun style en ligne, aucun calcul.** La bande de chiffres et les
lignes de la liste sont de la mise en page d'un seul écran : leur CSS vit dans le module de
l'écran, pas dans `primitives`. Seule la variante tappable d'`AiBlock` remonte dans la
bibliothèque, parce qu'elle change un composant de charte.

## 7. Mobile d'abord, iPad ensuite

Les feuilles s'écrivent pour **390 px**. Les deux points de rupture existants suffisent et
aucun troisième n'est ajouté :

| Largeur | Ce que ça vise | La forme |
|---|---|---|
| 390 – 599 | iPhone, plancher | tout en une colonne, bande de chiffres à 3 |
| 600 – 959 | **iPad portrait (820 × 1180)** | liste et « où je vais » côte à côte, bande à 3 |
| ≥ 960 | **iPad paysage (1180)**, ordinateur | la tendance reprend sa colonne latérale |

Le corps tappable de la lecture dépasse `--tap-lg` par sa seule hauteur de texte ; le bouton
qui l'accompagne est à `--tap`. Aucun geste de glissement n'est ajouté — rien ici ne détruit.

## 8. Ce que ça coûte

* **Un fichier CSV de plus** sur Nextcloud, une ligne par jour. Il se supprime sans perte.
* **Une tâche de fond de plus**, la deuxième du projet. Elle lit `insights/brief.csv` une
  fois par heure, et n'interroge un modèle qu'une fois par jour.
* **`DashboardView` grossit** de trois champs, dont un objectif et une séance : deux
  lectures de fichiers supplémentaires sur l'appel d'accueil. Le `prefetch` groupé de
  `FileStore` les absorbe ; à mesurer si l'accueil s'alourdit.
* **Un second appel au chargement** — `GET /brief` — à côté de `dashboard()`. `AGG-01`
  promet un seul appel pour **les indicateurs**, ce qui reste vrai ; la lecture est une
  surface indépendante avec ses propres quatre états, et l'écran peint sans l'attendre.
* **Les tests d'écran du tableau de bord** sont à reprendre : la carte « Journée » et la
  tuile « Hydratation » changent d'adresse.

## 9. Ce que ce lot ne fait pas

* **Les tuiles de `/activite`** — le tonnage sommé côté client et les deux `Bars` à
  `Math.max` — restent. Le champ `ratio` ajouté à `WeekVolume` corrige la barre du tableau
  de bord ; les autres sont un lot à prendre pour lui-même, comme le dit `CLAUDE.md` §7.
* **La liste ne coche rien.** Elle dit ce qui reste, elle n'écrit pas : le `⊕` de la barre
  d'onglets sait déjà noter un verre et un supplément, et `/routine` détient la case à
  cocher. Deux vocabulaires pour le même geste, c'est exactement ce qu'on évite.
* **La séance du jour n'est pas dite « faite ».** Le rapprochement prévu/réalisé est la
  règle de `PLAN-06` ; la reproduire ici en donnerait une seconde version. La ligne dit ce
  qui est **prévu**, et rien de plus.
* **Aucune feuille n'est ajoutée**, donc rien à inscrire dans `SURFACES` de
  `audit-surfaces.mjs`. Si cela change en cours de route, ce sera fait.
