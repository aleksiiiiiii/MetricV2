# Rappels push — de l'heure fixe à l'écart

Plan de travail. Il dit ce qui change, pourquoi, et ce que ça coûte.

Les rappels d'aujourd'hui partent **à l'heure dite si rien n'est noté**. Ceux-ci partent
**quand l'état le mérite**. Le reste du document découle de cette phrase.

---

## 1. Ce qui ne bouge pas, et qu'il ne faut pas « améliorer »

Trois choses tiennent le domaine debout. Un lot qui les défait ferait plus de mal que
l'absence de rappels.

> **Un rappel dit ce qui n'est pas noté, pas ce qui n'a pas été fait.**

« Tu n'as pas bu aujourd'hui » est une **affirmation fausse** : l'application sait seulement
que rien n'a été consigné. C'est « aucune valeur inventée » appliqué à une notification, et
c'est le cas difficile — elle est lue en trois mots, sur un écran verrouillé, sans moyen de
vérifier.

**Le partage pur / cousu.** [`reminders.py`](../backend/app/domains/notifications/reminders.py)
décide, [`scheduler.py`](../backend/app/domains/notifications/scheduler.py) lit et envoie.
Une règle écrite dans le second échapperait à la batterie du premier — et c'est là que vit
le texte des rappels.

**Les trois décisions de l'ordonnanceur** : `GRACE = 60 min`, jamais deux fois le même
créneau dans la même journée, rien du tout sans clé VAPID. Un serveur redémarré à 23 h ne
délivre pas le rappel de 20 h. Perdre un rappel coûte moins qu'en recevoir un la nuit.

---

## 2. Les décisions

Arbitrées avant écriture, en discussion du 25 août 2026.

| | Décision |
|---|---|
| **N1** | **Dix notifications par jour au plus**, et **quinze minutes** minimum entre deux, tous types confondus |
| **N2** | Hydratation et protéines deviennent **réactives** : c'est l'écart qui déclenche, pas l'heure seule. Trois contrôles d'hydratation — 14 h, 18 h, 22 h 30 |
| **N3** | Une séance prévue rappelle **quinze minutes avant**, à l'heure du planning |
| **N4** | Une séance prévue non notée rappelle **à 21 h, d'un ton sec** — sans jamais affirmer qu'elle n'a pas été faite |
| **N5** | Les félicitations existent, **sur un fait chiffré**, et **quatre par semaine au plus** |
| **N6** | Chaque notification ouvre **l'écran de son sujet**, plus l'accueil |
| **N7** | Les lectures du jour **ne sont pas poussées** |

### Pourquoi N7

Elles sont écrites pour être lues sur une carte, en dix secondes, avec le condensé dépliable
en dessous. Trois mots sur un écran verrouillé en perdent la moitié — et ça ferait trois
notifications de plus par jour pour dire ce que la carte dit mieux.

---

## 3. Les règles, une par une

### Hydratation — deux points de contrôle

**14 h, 18 h et 22 h 30.** À chacun, on n'envoie que si le restant est important.

- 14 h, 1 400 sur 2 000 → rien
- 14 h, 300 sur 2 000 → « 300 ml notés sur 2 000 »

**Pourquoi deux points et non un contrôle continu.** « Tu es en retard » suppose une cadence
horaire que personne n'a réglée : à quel rythme doit-on boire ? L'inventer serait exactement
la valeur inventée que le §1 interdit. Deux instants où l'écart *se lit* — il reste
l'après-midi, il reste la soirée — laissent l'urgence dans les chiffres sans qu'on juge.

**Trois points et non deux.** J'avais écarté un contrôle tardif au motif qu'il ne
resterait plus de marge — c'était faux : un verre se boit à 22 h 30. Le troisième point est
donc **22 h 30**, et c'est le dernier. Au-delà, un rappel ne fait plus que constater.

### Protéines — 18 h 30

Le dernier moment où un repas peut combler l'écart. N'envoie que s'il en reste un.

**18 h 30 et non 19 h** : à 19 h la lecture du soir s'écrit, et deux notifications à la même
minute se balayent d'un geste. Le décalage n'est pas cosmétique.

### Séance prévue — quinze minutes avant

L'heure vient de `plan.csv`. Elle y est **facultative** (`PLAN-02`), et c'est courant : une
séance sans heure n'a pas de « quinze minutes avant ». Elle tombe alors dans le rappel de
21 h, et dans celui-là seulement.

C'est le seul rappel qui peut **remplacer toute la navigation** : `PlannedSession.workout_url`
porte déjà l'adresse Cadence quand la séance en a une. La notification ouvre la séance, pas
l'application.

### Séance non notée — 21 h, ton sec

Le ton peut être ferme **si chaque mot est vrai**.

| Interdit | Retenu |
|---|---|
| « Tu as encore lâché ta séance » | « Séance de 18 h : toujours rien. Il te reste la soirée. » |

Le second engueule sans mentir, et ne se retourne pas contre l'utilisateur le jour où il
l'avait faite sans la noter.

### Suppléments — inchangé

Il n'y a pas d'écart à mesurer : c'est pris ou ça ne l'est pas. L'heure fixe est la bonne
forme, et le texte actuel — « Pas encore noté : créatine » — est déjà juste.

### Félicitations — sur un fait, quatre par semaine

**Ce qui déclenche** : un record par bande de distance, une charge battue, un objectif
atteint. L'application sait déjà les calculer — `progress.py` tient les bandes et leurs
records précisément parce qu'une allure ne se compare qu'à distance comparable, et
`goal.close` porte déjà `outcome === 'reached'`.

**Le texte cite pourquoi.**

| Interdit | Retenu |
|---|---|
| « Bravo pour ta performance de running ! » | « 8,4 km en 44 min — ta meilleure allure sous 10 km depuis trois semaines » |

Sans chiffre, c'est le compliment générique que la consigne interdit déjà au modèle, et qui
cesse d'être lu en trois jours.

**Quatre par semaine au plus.** Si plusieurs tombent le même jour, **le plus fort part et
les autres se taisent** — ils ne s'accumulent pas pour le lendemain. Une félicitation en
retard d'un jour ne félicite plus rien.

**Le déclenchement passe par l'ordonnanceur**, pas par l'écriture. Il voit à sa passe
suivante qu'une course a été notée et qu'elle n'a pas été saluée. Une minute de latence, et
le domaine Activité n'a rien à savoir des notifications.

---

## 4. Les garde-fous

**Quinze minutes entre deux notifications**, tous types confondus. Sans lui, 18 h 30
protéines, 19 h séance et 19 h 05 hydratation se balayent ensemble. Ce qui est repoussé
**attend la passe suivante** plutôt que d'être perdu — sauf si `GRACE` est dépassée.

**Dix par jour au plus.** Le plafond ne sert pas à limiter les rappels prévus — il y en a
moins — mais à borner ce que les félicitations et les rappels réactifs pourraient produire
le jour où une règle est mal écrite.

**Chaque notification ouvre l'écran de son sujet.** `Reminder.payload()` rend `"url": "/"`
en dur pour les quatre types : taper un rappel de suppléments ouvre le tableau de bord, et
il reste deux gestes pour arriver là où l'on note la prise. Le service worker sait **déjà**
router sur `data.url` ; il n'y a rien à écrire côté client.

| Rappel | Ouvre |
|---|---|
| Suppléments, hydratation | `/routine` |
| Protéines | `/nutrition` |
| Séance prévue | l'adresse Cadence si elle existe, sinon `/activite` |
| Félicitation | l'écran du fait cité |

---

## 5. Ce que le code doit gagner

| Fichier | Ce qui change |
|---|---|
| `reminders.py` | Les nouveaux types, l'écart, la priorité entre félicitations. **Tout ce qui décide** |
| `DaySnapshot` | Protéines notées et cible, heure de la séance prévue, records du jour |
| `models.py` | `sent.csv` : le couple (`date`, `kind`) ne suffit plus — deux contrôles d'hydratation dans la même journée sont deux lignes légitimes. Une colonne de créneau, comme `brief.csv` vient d'en gagner une |
| `scheduler.py` | Le délai de quinze minutes, le plafond quotidien, le compteur hebdomadaire des félicitations |
| `payload()` | L'adresse par type |
| Réglages | Les créneaux `reminders_*` : deux heures pour l'hydratation, une pour les protéines |

**Rien à écrire côté service worker.** Il lit déjà `data.url`, pose un `tag` par type et
reprend une fenêtre existante au clic.

---

## 6. Le piège qui peut coûter tout le lot

L'idée évidente est d'ajouter des **boutons d'action** — « J'ai bu 500 ml », « Fait » — pour
noter sans ouvrir l'application.

**Vérifie-le sur un vrai iPhone avant d'écrire une ligne.** Le web push d'iOS est arrivé en
16.4 avec un sous-ensemble de l'API, et les boutons d'action n'y ont historiquement pas été
rendus. Un lot qui les implémente proprement, avec son `notificationclick` par action et sa
route d'écriture, pour qu'ils n'apparaissent jamais sur le seul appareil employé — c'est du
travail dont personne ne verra rien. Si c'est le cas : le dire, et ne pas l'écrire.

Et si ça marche : garder en tête que le geste écrit dans un dossier de santé **sans que
personne ne regarde**, et que le projet n'a aucune annulation. « J'ai bu 500 ml » est une
addition, elle se défait. « Séance faite » écrirait une durée que personne n'a donnée — et
`CircuitDonePayload` exige la durée précisément pour cette raison.

---

## 7. Ordre d'exécution

| # | Portée | Risque |
|---|---|---|
| 0 | ~~**N1** : plafond quotidien et espacement~~ **fait** | nul — une fonction pure, et un garde-fou qui doit exister avant les règles qu'il borne |
| 0 bis | ~~**N2** : l'écart décide, trois contrôles d'hydratation, les protéines~~ **fait** | c'est là que tout se joue — et c'est fait |
| 0 ter | ~~**N3** : une séance s'annonce un quart d'heure avant~~ **fait** | le déclencheur quitte les réglages pour le planning |
| 1 | `payload()` : l'adresse par type | nul — trois lignes dans un module pur déjà testé |
| 2 | `sent.csv` gagne son créneau, et le service qui le lit | faible |
| 3 | `reminders.py` : l'écart, les nouveaux types, les textes | **c'est là que tout se joue** |
| 4 | `scheduler.py` : délai, plafond, compteur hebdomadaire | moyen |
| 5 | Les réglages des nouveaux créneaux | faible |
| 6 | Félicitations : lecture des records, priorité | moyen |
| 7 | `make check`, puis le §0bis sur un vrai téléphone | — |

**N1 est faite** (25 août 2026). Elle passe devant tout : c'est le garde-fou, et il doit
exister *avant* les règles réactives qu'il borne — l'écrire après reviendrait à laisser une
fenêtre où une règle mal réglée part vers un téléphone sans plafond.

Deux choses valent d'être nommées. Le budget se demande **après `compose`**, jamais avant :
un rappel qui n'avait rien à dire est clos pour la journée, un rappel repoussé doit revenir,
et les confondre en tairait un pour de bon. Et la passe **s'arrête** au premier refus plutôt
que d'examiner les suivants — ils sont soumis au même délai, la réponse serait la même.

La phase 1 part ensuite parce qu'elle est déjà utile seule : elle ne change aucune règle et
supprime deux gestes à chaque rappel.

---

## 8. Vérifier

`make check` d'abord. Puis la batterie de `reminders.py` sur **chaque** nouveau cas : ce
module se teste sur des valeurs fixes, sans monter d'application. Un rappel dont la règle
n'y est pas est un rappel qu'on n'a pas jugé.

Et la seule étape qui dira si le lot vaut quelque chose — le §0bis de
[`verifications-manuelles.md`](verifications-manuelles.md) : installer depuis Safari iOS,
recevoir un rappel **application fermée**, taper dessus, et vérifier qu'on arrive au bon
écran. Elle ne se joue que derrière un vrai HTTPS, et **elle n'a jamais été jouée**.

---

## 9. Ce que ce lot ne fait pas

- **Les lectures du jour ne sont pas poussées** (N7).
- **Aucune notification ne félicite une séance ordinaire.** On vient de la faire, on le sait.
- **Aucun rattrapage d'un jour sur l'autre.** Un rappel manqué est perdu, une félicitation
  en retard ne félicite plus rien.
- **Aucune cadence d'hydratation n'est inventée.** Deux points de contrôle, des chiffres
  relevés, et c'est l'utilisateur qui lit l'urgence.


---

## 10. Journal

### N2 — l'écart décide (25 août 2026)

`gap_matters(done, target)` : un écart mérite qu'on en parle s'il vaut **au moins un quart
de la cible**. C'est le seuil qui distingue un rappel réactif d'un rappel à heure fixe —
sans lui, un contrôle à 14 h partirait qu'on soit à 300 ou à 1 900 ml sur 2 000.

**Une part et non un nombre de millilitres.** Quelqu'un qui vise 3 L n'a pas le même « il
reste beaucoup » que quelqu'un qui vise 1,5 L, et un seuil absolu ferait mentir l'un des
deux.

**Sans cible réglée, rien ne part.** Comparer à zéro rendrait tout écart infini, et le
rappel partirait tous les jours pour citer un chiffre sans référence. Une cible absente
n'est pas une cible de zéro — c'est « aucune valeur inventée », appliqué à un dénominateur.

#### Ce que le passage à trois contrôles a coûté

`sent.csv` a dû passer du couple (`date`, `kind`) au **triplet** (`date`, `kind`, `slot`).
Sans l'heure, le contrôle d'hydratation de 14 h éteignait ceux de 18 h et de 22 h 30 — et
c'est le test qui le dit maintenant, nommément.

Une ligne écrite avant ce lot n'a pas de `slot`. Elle est lue comme « ce type est parti
aujourd'hui, à un moment qu'on ne sait plus », ce qui **éteint tous ses contrôles pour la
journée**. Conservateur à dessein : un rappel perdu coûte moins qu'un doublon, et la
divergence dure une journée (`STO-04`).

`pending` rend désormais des `Checkpoint` et non des `ReminderKind`. `parse_slots` lit une
liste séparée par des virgules — le format de `hydration_presets_ml`, pour la même raison —
et **la trie** : un réglage écrit « 22:30,14:00 » ferait sinon examiner la fin de journée en
premier.

#### Deux choses que le code a imposées

**Les signatures prennent un `Mapping`, pas un `dict`.** mypy l'a demandé et il avait
raison : `dict` est invariant, et un test qui construit `{HYDRATION: (t1, t2, t3)}` ne
s'assignait pas à `dict[..., tuple[time, ...]]`. Le corriger dans les tests aurait été
contourner le message.

**Un type qui n'a rien à dire se tait pour la journée entière, pas seulement pour le
contrôle en cours.** L'état du jour ne se relit qu'une fois par passe, et le rouvrir à
chaque contrôle coûterait cinq lectures WebDAV pour une réponse qui n'a pas bougé.
Conséquence assumée : si l'écart d'hydratation redevient important entre 14 h et 18 h, on
ne le dira pas — ça ne peut arriver qu'en effaçant une prise, un cas où se taire est juste.

#### Un défaut d'accessibilité, trouvé par un test qui cassait

Les tests désignaient les champs de rappel **par leur rang**. Insérer les protéines au
milieu de la table décalait tout, et le test envoyait le mauvais créneau sans rien dire.

La cause n'était pas le test : cinq champs portaient le nom accessible « Heure du rappel »
sur le même écran, et rien ne les distinguait à la synthèse vocale — la leçon des pastilles
« Corriger » du catalogue, reproduite ici. Chaque champ porte maintenant son sujet dans son
`aria-label`, l'étiquette visible reste courte, et les tests adressent par le nom.

**Mesuré** : `make check` vert, 1 589 tests backend et 498 d'écran. Les seuils et les
frontières sont vérifiés à la minute et au millilitre près.


### N3 — le déclencheur quitte les réglages (25 août 2026)

L'heure d'un rappel de séance vient maintenant de `plan.csv`, pas d'une clé `reminders_*` :
c'est celle qu'on a posée au calendrier, et elle change d'un jour à l'autre. Une séance
prévue à 18 h construit un contrôle à 17 h 45. **Aucun réglage à poser.**

**Un type à part, `workout_soon`.** Il annonce ce qui vient ; `workout` constatera en fin de
journée qu'il n'y a rien de noté (N4). Un seul type aurait donné un message qui ment dans un
des deux cas.

**`compose` prend le contrôle et non le type.** C'est la conséquence directe de deux séances
le même jour : sans l'heure, le rappel de 17 h 45 pourrait nommer celle de 20 h. Un test le
vérifie nommément.

**Une séance sans heure ne s'annonce pas.** L'heure est facultative dans `plan.csv`
(`PLAN-02`) et le cas est courant. Elle ne compte que dans le rappel de fin de journée.

#### Le coût, mesuré plutôt que craint

Lire le planning à chaque passe est une **troisième** lecture par minute, à côté de celles
des réglages et du journal d'envoi. C'est le même ordre de grandeur, pas une nouvelle
catégorie : ce que l'ordonnanceur évite depuis toujours, c'est la lecture des **cinq
domaines** du `snapshot`, qui ne part que si un contrôle est atteint.

#### Trois cas de silence, tous testés

- La séance a quitté le planning entre la construction du contrôle et l'envoi — on
  n'annonce pas ce qui n'est plus prévu.
- Elle est déjà notée : on n'annonce pas ce qui vient d'être fait.
- Elle commence après minuit : le contrôle tombe la veille, et `pending` situe les créneaux
  dans le jour de `now`. Il n'est donc jamais dû — on ne notifie pas la nuit.

#### Ce que la relecture a rangé

`shift(heure, delta)` est **exportée et employée des deux côtés** : l'ordonnanceur recule
d'un quart d'heure ce que `compose` avance du même quart d'heure. J'en avais écrit deux —
elles se seraient répondu à une minute près le jour où l'une aurait changé.

Et trois messages de `ruff` ont été suivis plutôt que contournés : un `datetime` sans fuseau,
un `__all__` désordonné, et une lambda qui capturait la variable d'une boucle — la dernière
aurait fait partager la même heure aux quatre passes d'un test.
