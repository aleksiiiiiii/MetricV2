# Prompt — améliorer les rappels push

> À copier tel quel dans une session neuve. Le terrain a été relu ; ce document dit ce qui
> manque, ce qui est déjà bon, et les trois pièges où ce lot peut se retourner contre
> l'utilisateur.

---

## Lis ça d'abord, ou tu vas casser ce qui marche

Les rappels sont **la fonctionnalité la plus facile à rendre nuisible du projet**, et
[`notifications/reminders.py`](../backend/app/domains/notifications/reminders.py) est déjà
écrit autour de cette idée. Sa règle gouvernante :

> **Un rappel dit ce qui n'est pas noté, pas ce qui n'a pas été fait.**

« Tu n'as pas bu aujourd'hui » est une affirmation fausse : l'application sait seulement que
rien n'a été consigné. Et son corollaire : **un rappel qui arrive au mauvais moment se
désinstalle en un geste et ne revient jamais.**

Tout ce qui suit se juge à cette aune. Un ajout qui augmente le nombre de notifications sans
augmenter ce qu'elles apportent est une régression, même s'il marche.

## Ce qui manque vraiment — par ordre de rapport

### 1. Toutes les notifications ouvrent l'accueil

`Reminder.payload()` rend `"url": "/"` en dur, pour les quatre types. Taper « Suppléments —
pas encore noté : créatine » ouvre le tableau de bord, et il reste deux gestes pour arriver
là où l'on note la prise.

**Le service worker sait déjà router** :
[`sw/index.ts`](../frontend/src/sw/index.ts) lit `data.url` et fait `client.navigate(target)`
sur une fenêtre existante. Il n'y a rien à écrire côté client — seulement à cesser d'envoyer
la même adresse pour tout.

Ce qui va où : suppléments et hydratation sur `/routine`, repas sur `/nutrition`, séance sur
`/activite`. **C'est le meilleur rapport du lot** : quelques lignes dans un module pur, déjà
couvert par sa batterie, et trois gestes économisés à chaque rappel.

### 2. Rien ne rappelle ce que le projet a gagné depuis

`NOT-02` date d'avant les séances Cadence et les trois lectures du jour. Deux candidats,
et **ils ne se valent pas** :

- **Une séance Cadence prévue** — `plan.csv` porte le lien dans sa note, et
  `PlannedSession.workout_url` l'expose déjà. Un rappel de séance qui ouvre directement
  Cadence est le seul cas où la notification remplace toute la navigation.
- **Les lectures du jour** — matin, midi, soir. Attention : ce serait **trois
  notifications de plus par jour**, et la règle 1 du module dit qu'un rappel qui ne dit rien
  se désinstalle. Si tu le fais, ne pousse que celle du matin, et seulement si elle
  contient une action à faire.

### 3. Le `tag` remplace en silence

`showNotification` reçoit `tag` mais pas `renotify`. Une seconde notification du même type
remplace la première **sans re-sonner** : c'est voulu pour ne pas empiler, mais ça veut dire
qu'un rappel manqué à 12 h et renvoyé à 20 h peut passer inaperçu. À trancher explicitement,
dans un sens ou dans l'autre — aujourd'hui personne ne l'a décidé, c'est un défaut de
`showNotification`.

## Les trois pièges

### Les boutons d'action ne s'affichent probablement pas sur l'appareil visé

L'idée évidente est d'ajouter `actions: [{action: 'bu', title: 'J'ai bu 500 ml'}]` pour noter
sans ouvrir l'application. **Vérifie-le sur un vrai iPhone avant d'écrire une ligne.** Le web
push d'iOS est arrivé en 16.4 avec un sous-ensemble de l'API, et les boutons d'action n'y ont
historiquement pas été rendus. Un lot qui les implémente proprement, avec son
`notificationclick` par action et sa route d'écriture, pour qu'ils n'apparaissent jamais sur
le seul appareil que l'utilisateur emploie — c'est du travail dont personne ne verra rien.

Si c'est bien le cas : dis-le et n'écris pas la fonctionnalité. Une ligne dans le document
vaut mieux qu'une implémentation invisible.

### Écrire depuis une notification, c'est écrire sans écran

Si les actions marchent, garde en tête que le geste écrit dans un dossier de santé **sans
que personne ne regarde**. Le projet n'a aucune annulation. Une action « j'ai bu 500 ml »
est défendable — c'est une addition, elle se défait ; une action « séance faite » qui écrit
une durée inventée ne l'est pas (voir `CircuitDonePayload`, où la durée est exigée
justement pour ça).

### Ne touche pas à l'ordonnanceur sans relire ses trois décisions

`GRACE = 60 min`, jamais deux fois le même créneau par jour, et rien du tout sans clé VAPID.
Les trois sont écrites en tête de
[`scheduler.py`](../backend/app/domains/notifications/scheduler.py) avec leur raison. Un
serveur redémarré à 23 h ne doit pas délivrer le rappel de 20 h.

## Ce qui est déjà bon, et qu'il ne faut pas « améliorer »

- Le partage **pur / cousu** : `reminders.py` décide, `scheduler.py` lit et envoie. Une
  règle écrite dans le second échapperait à la batterie du premier.
- Le vocabulaire des textes. « Hydratation — rien de noté » n'est pas une formulation
  timide, c'est la seule qui soit vraie.
- Le `tag` par type, et la reprise d'une fenêtre existante au clic — sur iOS en mode
  autonome, ouvrir une seconde fenêtre remplace l'application par elle-même.

## Vérifier

- `make check` vert.
- La batterie de `reminders.py` sur chaque nouveau cas : ce module se teste sur des valeurs
  fixes, sans monter d'application. Un rappel dont la règle n'y est pas est un rappel qu'on
  n'a pas jugé.
- **Et le §0bis de [`verifications-manuelles.md`](verifications-manuelles.md)** : installer
  depuis Safari iOS, recevoir un rappel **application fermée**, taper dessus et vérifier
  qu'on arrive au bon écran. Elle ne se joue que derrière un vrai HTTPS, et **elle n'a
  jamais été jouée**. C'est la seule étape qui dit si ce lot vaut quelque chose.
