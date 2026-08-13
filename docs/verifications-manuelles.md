# Vérifications à faire à la main

Ce qui ne peut pas être vérifié par `make check`, accumulé lot après lot, avec pour chaque
entrée **ce qu'on lance**, **ce qu'on regarde** et **ce qui compte comme échec**.

Ce document existe pour une raison précise, écrite au §6 de
[`etat-du-projet.md`](etat-du-projet.md) et confirmée trois lots de suite : *tout ce qui a
été trouvé l'a été en utilisant l'application, pas en la testant.* La refonte de l'écran
Activité est partie avec vingt-quatre tests verts et deux défauts sont sortis en regardant
la page. La passe tactile en a produit trois de plus. La découverte des modèles était
verte sur toute sa batterie simulée, et le vrai catalogue a fait tomber deux entrées
qu'elle acceptait.

Un test vérifie ce qu'on a pensé à vérifier. Cette liste est ce qu'on n'a pas encore
regardé.

**Ordre de lecture** : les sections sont classées par ce qu'elles coûtent à ignorer, pas
par difficulté. Les **cinq premières** bloquent chacune une clôture de lot.

---

## 0bis. Ce qui bloque la clôture du lot L15

La DoD de `L15` tient en une phrase — « Metric s'installe depuis Safari iOS et délivre un
rappel de suppléments application fermée » — et **rien de cette phrase ne se teste en CI**.
Ni l'installation, ni la réception, ni « application fermée ».

Ce que la batterie couvre déjà, et qu'il est inutile de refaire : sans clé VAPID rien n'est
bloqué, un abonnement révoqué est retiré, un redémarrage ne renvoie pas ce qui est parti, la
charge utile part **chiffrée**, et un rappel ne dit jamais ce qui n'a pas été fait. Soixante
-quatorze tests, dont vingt-sept sur le seul texte des rappels.

> **Préalable non négociable : HTTPS.** Un service worker et Web Push exigent un contexte
> sécurisé. `localhost` en est un, `172.20.10.10` **non** — donc `make dev-lan` ne suffit
> pas, et l'écran le dira lui-même (« Cette adresse n'est pas un contexte sécurisé »).
> iOS ajoute une condition de plus : Web Push n'existe qu'une fois l'application **ajoutée
> à l'écran d'accueil**.

### Le montage, en cinq commandes

Tout passe par `make console`, qui sait démarrer les quatre services, les surveiller et
les arrêter. Rien à conteneuriser, rien à retenir.

```
make console

metric ❯ vapid            # génère la paire — à coller dans .env, puis « restart api »
metric ❯ start api        # l'ordonnanceur des rappels vit dedans
metric ❯ build            # le service worker n'existe QUE dans le build
metric ❯ start preview    # sert ce build sur :4173
metric ❯ start tunnel     # l'expose en HTTPS, et affiche l'adresse à taper
metric ❯ push             # les trois conditions, d'un coup d'œil
```

> **Le service worker ne s'enregistre pas en développement**, et c'est voulu : il
> s'interposerait sur `/assets` et servirait des fichiers périmés pendant qu'on code
> (`lib/pwa.ts`). D'où `build` puis `start preview` — `make dev` ne l'éprouve pas.
> Après chaque `build`, **`restart preview`** : sinon il sert encore l'ancien, et la
> console le rappelle.

**`push` est la commande à connaître.** Trois choses doivent être vraies en même temps
pour qu'un rappel parte, et chacune se règle ailleurs — une paire de clés dans `.env`, un
appareil abonné depuis lui-même, un créneau réglé dans `/reglages`. Les regarder
séparément est ce qui fait chercher longtemps.

> **Le tunnel est un outil de vérification, pas un déploiement.** `cloudflared` n'est pas
> installé par défaut : `brew install cloudflared`, et la console le dit si elle ne le
> trouve pas. Il ouvre l'application sur l'Internet public le temps de l'essai et meurt
> avec le processus — d'où le fait qu'il ne démarre jamais tout seul.
>
> **Le HTTPS durable, lui, viendra de Nginx Proxy Manager**, pas de ce tunnel et pas d'une
> pile conteneurisée. `make console` → `proxy` dit ce que l'application demande en
> échange : les deux hôtes à déclarer, `TRUST_PROXY_HEADERS`, `CORS_ORIGINS`, et le fait
> que le proxy ne doit **jamais** mettre `/api` en cache — une réponse mémorisée par lui
> serait exactement ce que le service worker s'interdit. `L17-01` reste entier.

### 0bis.1 — Metric s'installe depuis Safari iOS

**Le geste** : ouvrir l'URL du tunnel sur l'iPhone → Partager → « Sur l'écran d'accueil ».

| Point | Ce qui doit se produire |
|---|---|
| Icône | la **règle graduée** sur fond sombre, pas une capture de la page ni un globe |
| Nom | « Metric », sans suffixe d'URL |
| Ouverture | plein écran, **sans la barre d'adresse** de Safari |
| Écran de démarrage | fond `#0B0F16`, sans éclair blanc |
| Zone sûre | la barre d'onglets basse ne passe pas sous l'indicateur d'accueil |
| Zoom | le pincement fonctionne encore *(pas de `user-scalable=no`)* |

**Ce qui compte comme échec** : une icône générique *(le manifeste ou
`apple-touch-icon` n'est pas lu)*, une barre d'adresse persistante *(`display: standalone`
ignoré)*, ou un éclair blanc au démarrage *(`background_color` désaccordé de `--bg`)*.

### 0bis.2 — L'abonnement n'est proposé que là où il marche

**Le geste** : ouvrir `/reglages`, section « Rappels », **d'abord dans l'onglet Safari**,
puis depuis l'icône de l'écran d'accueil.

**Ce qu'on attend** : dans l'onglet, pas de bouton mais la phrase « Sur iPhone, les rappels
demandent que Metric soit ajoutée à l'écran d'accueil… ». Depuis l'icône, le bouton
« Recevoir les rappels ici ».

**Ce qui compte comme échec** : un bouton proposé dans l'onglet — il échouerait sans rien
expliquer, et c'est exactement le cas que `pushSupport()` distingue.

**Puis** : autoriser, et vérifier que l'appareil apparaît dans la liste sous « iPhone » avec
les derniers caractères de son adresse. Ouvrir `notifications/subscriptions.csv` sur
Nextcloud : une ligne, avec `endpoint`, `p256dh` et `auth` renseignés.

### 0bis.3 — Un rappel arrive, application fermée

**C'est la moitié de DoD qui manque, et rien de ce qui précède ne la remplace.**

**Le geste**, dans cet ordre :

1. `POST /api/notifications/test` depuis l'application — bouton « Envoyer un essai ».
   Vérifie la chaîne entière **sans attendre un créneau** : clés, chiffrement, service
   push, service worker.
2. Régler « Suppléments » à trois minutes dans le futur, enregistrer.
3. **Fermer complètement l'application** — la balayer hors du sélecteur d'apps, pas
   seulement revenir à l'écran d'accueil. Verrouiller le téléphone.

| Point | Ce qui doit se produire |
|---|---|
| Réception | la notification arrive, écran verrouillé, app fermée |
| Titre | « Suppléments » |
| Corps | « Pas encore noté : … » — **les noms de ce qui reste**, pas la liste entière |
| Icône | la règle graduée, pas un point générique |
| Appui | ouvre Metric ; si elle était déjà ouverte, la **reprend** au lieu d'en ouvrir une seconde |
| Journal | une ligne dans `notifications/sent.csv`, avec le bon jour |

**Ce qui compte comme échec** — et le second est le plus grave :

- **Rien n'arrive.** Regarder les journaux de l'API : `PushGoneError` veut dire que
  l'abonnement a été révoqué *(se réabonner)*, une autre erreur veut dire que l'envoi n'est
  pas parti *(clés, `VAPID_SUBJECT`)*.
- **Le texte affirme quelque chose.** « Tu n'as pas pris ta créatine » est une affirmation
  **fausse** : l'application sait seulement que rien n'a été consigné. C'est l'invariant du
  lot, et une notification est lue en trois mots, sans moyen de vérifier.
- **Un supplément déjà coché est cité.** Le rappel doit lire `checklist(day)` et ne nommer
  que ce qui reste.
- **Deux notifications pour un créneau.** La mémoire est un fichier ; deux lignes veulent
  dire que `sent.csv` n'est pas relu.

### 0bis.4 — Le rappel ne revient pas deux fois, et ne réveille personne

**Le geste** : laisser passer le créneau, puis redémarrer l'API (`make dev`) dans la même
journée.

**Ce qu'on attend** : **aucune** seconde notification. `notifications/sent.csv` porte une
ligne pour ce jour et ce type, et l'ordonnanceur la relit au démarrage.

**Puis**, le contrôle de la fenêtre de rattrapage : arrêter l'API, laisser passer un créneau
de **plus d'une heure**, redémarrer. Rien ne doit partir — perdre un rappel coûte moins
qu'en recevoir un au coucher.

### 0bis.5 — Le service worker ne sert jamais un chiffre d'hier

**C'est l'autre invariant du lot**, et il est invisible quand il est cassé : la page a l'air
parfaitement normale, avec les chiffres de la veille.

**Le geste** : ouvrir le tableau de bord en ligne, noter le poids affiché. Passer en **mode
avion**. Recharger.

**Ce qu'on attend** : la coquille s'ouvre — en-tête, navigation, titres — et chaque écran
affiche son **état d'erreur**, parce que `/api` n'a pas répondu. Aucun chiffre.

**Ce qui compte comme échec** : le moindre chiffre à l'écran. Une moyenne, un poids, un
total : ce serait une valeur inventée au sens le plus littéral de l'invariant, et rien à
l'écran ne permettrait de s'en apercevoir.

**Puis**, en ligne : modifier une pesée depuis un autre appareil, recharger. La nouvelle
valeur doit apparaître **immédiatement** — `/api` ne passe jamais par le cache.

### 0bis.6 — L'heure affichée est bien la nôtre

Le champ de créneau est un `<input type="time">` : **son format suit la langue du système**,
pas celle du document. En Chrome headless anglophone il rend « 08:00 PM » là où le serveur
a `20:00`.

**Ce qu'on regarde** : sur l'iPhone en français, le champ affiche-t-il `20:00` ?

**Ce qui compte comme échec** : un format sur douze heures, qui obligerait à convertir de
tête pour régler un rappel du soir. Si le cas se présente, la piste est de remplacer le
champ natif par deux sélecteurs — au prix du sélecteur de roue d'iOS, qui est excellent.

---

## 0. Ce qui bloque la clôture du lot L13

La DoD de `L13` a deux moitiés. La seconde — « une proposition IA n'écrit rien avant
adoption explicite » — est couverte des deux côtés : `tests/test_planning_ai.py` vérifie
qu'aucun fichier n'apparaît, et `Planning.test.tsx` vérifie qu'aucune écriture ne part de
l'écran. La première ne peut pas l'être autrement qu'à la main.

### 0.1 — Le flux `.ics` s'abonne réellement dans Apple Calendar

**C'est la moitié de DoD qui manque, et rien de ce qui suit ne la remplace.** Un flux
peut être valide au sens de la RFC et refusé par Apple Calendar sans un mot d'explication ;
c'est exactement le genre de chose que la leçon du §5 répète depuis trois lots.

**Préalable** — le flux n'est pas publié tant qu'aucune clé n'est configurée, et c'est
voulu (`PLAN-05`) :

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # puis ICAL_SECRET=… dans .env
make dev-lan                                                    # l'API doit être joignable du Mac
```

L'adresse exacte s'affiche dans `/planning`, carte « Abonnement calendrier ». Une clé de
moins de 32 caractères est traitée comme absente : l'écran le dit alors au lieu de publier.

> **Attention** : `make dev-lan` n'expose que le frontend ; l'API reste sur
> `127.0.0.1:8000`. L'abonnement doit donc se faire **depuis le Mac** qui fait tourner
> l'API, ou après avoir exposé l'API sciemment — ce que le §5 de `etat-du-projet.md`
> déconseille en clair sur un réseau.

**Le geste** : Apple Calendar → menu « Fichier » → « Nouvel abonnement au calendrier » →
coller l'adresse.

**Ce qu'on regarde**, dans cet ordre :

| Point | Ce qui doit se produire |
|---|---|
| Abonnement | accepté sans message d'erreur, et le calendrier apparaît dans la liste |
| Séance avec heure | au bon jour **et à la bonne heure locale** — 18:30 planifié s'affiche 18:30 |
| Séance sans heure | évènement « toute la journée », sur **un seul** jour et non deux |
| Durée | l'évènement se termine à l'heure prévue *(60 min → 18:30–19:30)* |
| Titre | « Muscu · Haut du corps », lisible au milieu du reste de l'agenda |
| Note | présente en description, virgules et points-virgules compris |
| Rafraîchissement | une séance ajoutée dans Metric apparaît après actualisation |
| Modification | déplacer une séance la **déplace** — elle n'apparaît pas en double |

**Ce qui compte comme échec** : un calendrier vide sans message *(le symptôme d'un
pliage de ligne ou d'un CRLF fautif)*, une heure décalée de deux heures *(la conversion
UTC)*, une séance sans heure qui occupe deux jours *(`DTEND` non exclusif)*, ou un doublon
après modification *(l'`UID` n'est pas stable)*.

Le dernier est le plus coûteux : un calendrier abonné ne se nettoie pas tout seul, et un
`UID` instable produit un doublon **par modification**, indéfiniment.

### 0.2 — Une clé fausse ne donne rien

Ouvrir dans un navigateur l'adresse d'abonnement en changeant **un seul caractère** de la
clé. Attendu : `404`, avec le même refus que pour une adresse inexistante.

**Ce qui compte comme échec** : un `403`, un message distinguant « clé fausse » de
« aucun flux », ou le moindre octet de planning servi. Cette URL est publique et sans
anti-brute-force : elle ne doit rien confirmer.

### 0.3 — Une vraie proposition de planning tient debout

```bash
make dev          # puis /planning, carte « Proposer un planning »
```

> **Appel réel à OpenRouter** — à demander avant, comme au §1. Une proposition coûte de
> l'ordre d'un centime avec `anthropic/claude-sonnet-5`.

**Le geste** : renseigner une contrainte franche — « pas le mercredi » — puis « Proposer ».

**Ce qu'on regarde** : les dates tombent bien dans la semaine annoncée ; la contrainte est
respectée ; la fréquence proposée ressemble à celle des quatre dernières semaines ; les
groupes alternent ; aucune séance ne double une séance déjà au planning.

**Ce qui compte comme échec** : une date hors de la fenêtre *(elle aurait dû être écartée
à la relecture et nommée dans « Écarté à la relecture »)*, une séance d'une minute
*(le `1:00` lu comme `mm:ss`, que la borne basse est censée écarter)*, ou une contrainte
ignorée sans que rien ne le dise.

**Puis** : retirer une séance, adopter le reste, et vérifier dans `planning/plan.csv` que
**seules** les séances gardées sont écrites, toutes avec `ai` en dernière colonne.

### 0.4 — Une cellule vide de `plan.csv` ne casse rien

Ouvrir `planning/plan.csv` dans un tableur, vider la colonne `time` d'une ligne, vider
`kind` sur une autre, écrire `cardio` sur une troisième. Recharger `/planning`.

**Ce qu'on attend** : les trois séances s'affichent toujours, celles dont la nature est
illisible en « Autre », celle sans heure en tête de journée. **Aucun `502`.**

C'est le contrôle direct de la décision qui a coûté le tableau de bord entier au premier
usage réel, sur `supplements/schedule.csv`. Ici la colonne `time` est vide **par
conception** — elle le sera souvent.

---

## 1. Ce qui bloque la clôture du lot L12

La DoD de `L12` est vérifiée **à moitié**. La première moitié — « sans clé API, aucune
fonctionnalité n'est bloquée » — l'est par `tests/test_ai_api.py`. La seconde ne peut pas
l'être autrement qu'à la main.

> **Rappel de conduite** : chaque appel réel à OpenRouter se demande avant. `OPENROUTER_MODEL`
> vaut `anthropic/claude-sonnet-5`, un modèle **payant** placé en tête de cascade : chacune
> des vérifications ci-dessous coûte de l'ordre d'un centime. Vider le réglage bascule sur
> les six modèles vision gratuits.

### 1.1 — Une capture Apple Fitness pré-remplit une course

```bash
make dev          # puis /activite, section « Saisie »
```

**Le geste** : carte « Import d'une capture » → choisir une vraie capture d'Apple Fitness
ou de la montre → « Lire la capture ».

**Ce qu'on regarde**, dans cet ordre :

| Point | Ce qui doit se produire |
|---|---|
| Distance | convertie en km si la capture est en miles, avec la bonne valeur *(5,20 MI → 8,369 km)* |
| Durée | `28:45` devenu 28,75 minutes, pas 28 ni 2845 |
| Date | absolue et passée, même si la capture écrit « Hier » ou « Lundi » |
| Champs absents | **vides**, et nommés dans la phrase du bloc IA — jamais à zéro |
| Nature | course si la capture porte une distance, séance sinon |
| Écriture | **rien** dans `runs.csv` tant qu'« Importer cette activité » n'est pas touché |

**Ce qui compte comme échec** : une valeur inventée là où la capture ne portait rien, une
distance en miles restée en miles, une date du jour posée par défaut, ou une ligne écrite
avant validation. Les trois premiers font entrer une mesure fausse dans un fichier censé
rester lisible dans dix ans ; le quatrième casse `IMP-01`.

**Puis** : ouvrir `activity/runs.csv` sur Nextcloud et vérifier que la dernière ligne se
termine par `,apple`. C'est `IMP-05`, et c'est le seul endroit où l'on peut le constater.

### 1.2 — Une vraie photo de repas donne une estimation utilisable

```bash
make dev          # puis /nutrition
```

**Le geste** : « Ajouter un repas » → prendre ou choisir une photo d'assiette →
« Estimer les macros depuis la photo ».

**Ce qu'on regarde** : la phrase du bloc IA annonce des grammes et des kilocalories
plausibles ; « Utiliser ces valeurs » remplit les trois pas-à-pas **en pointillé** ; un
appui sur `+` retire le pointillé du champ touché et de lui seul ; « Pas d'accord » vide ce
qui reste proposé et **garde** ce qui a été retouché.

**Ce qui compte comme échec** : une estimation grossièrement fausse *(une salade à 2000
kcal)*, un champ rempli alors que le modèle n'a rien su dire, ou un pointillé qui survit à
une correction. Le dernier viderait `NUT-04` de son sens : on ne distinguerait plus ce
qu'on a validé de ce qu'une machine a proposé.

**Puis** : enregistrer, et vérifier dans `nutrition/meals.csv` que la ligne porte `ai` en
dernière colonne. Refaire un repas en refusant l'estimation : il doit porter `manual`.

### 1.3 — Une photo prise après coup s'estime quand même

Un repas enregistré **avec photo et sans macros** doit afficher un bouton « estimer » dans
le journal. C'est la porte pour le « après » que l'écran promet — et le seul chemin qui
relit une photo **déjà rangée sur Nextcloud**, ce que les tests ne couvrent que contre un
faux WebDAV.

**Ce qui compte comme échec** : le bouton absent, ou une estimation qui modifie le repas
sans passer par « Enregistrer ces valeurs ».

### 1.4 — Une capture illisible se dit

Envoyer volontairement une photo qui n'est pas une capture sportive — un paysage, une
capture de messagerie.

**Ce qu'on attend** : un message qui propose de refaire la capture **ou** de saisir à la
main (`IMP-06`), la capture toujours choisie pour relancer en un appui, et les deux
formulaires manuels intacts à côté.

### 1.5 — Le HEIC, écart assumé à confirmer

Envoyer une photo iPhone au format d'origine. Le refus doit **nommer les formats lisibles**
et le repas doit rester enregistrable normalement.

Si le cas se présente à chaque photo en usage réel, c'est le signal qu'il faut rouvrir la
décision et ajouter `pillow-heif`. Sinon, l'écart tient.

---

## 2. Ce qui bloque la clôture du lot L14

La DoD de `L14` a deux moitiés. La seconde — « le résumé envoyé au modèle est vérifiable et
borné » — est couverte des deux côtés : `tests/test_goals_ai.py` vérifie qu'une note
personnelle de repas **n'atteint pas** la consigne, et l'écran publie le condensé
ligne à ligne sous « Ce qui a été envoyé au modèle ». La première ne peut pas l'être
autrement qu'à la main, et une partie **demande que du temps passe**.

> **Rappel de conduite** : chaque appel réel à OpenRouter se demande avant.
> `OPENROUTER_MODEL` vaut `anthropic/claude-sonnet-5`, un modèle **payant** placé en tête
> de cascade : chacune des vérifications ci-dessous coûte de l'ordre d'un centime.

### 2.1 — Un objectif se génère, s'adopte, et sa progression bouge

```bash
make dev          # puis /objectif
```

**Le geste** : « Proposer un objectif », avec ou sans envie déclarée. Puis « Adopter ».

**Ce qu'on regarde**, dans cet ordre :

| Point | Ce qui doit se produire |
|---|---|
| Métrique | l'une des cinq, jamais une autre — le sommeil et l'humeur ne se mesurent pas ici |
| Cible | un chiffre **partant de la valeur actuelle**, pas de zéro ni d'un idéal rond |
| Échéance | entre 4 et 8 semaines, jamais « dans six semaines » en toutes lettres |
| Justification | elle cite un fait du condensé, pas une généralité de magazine |
| Écriture | **rien** dans `goals/goals.csv` tant qu'« Adopter » n'est pas touché |
| Progression | l'anneau part à 0 % le jour de l'adoption, et le départ vaut la valeur courante |

**Ce qui compte comme échec** : une cible en dessous de ce qu'on fait déjà *(la formule la
lirait comme « redescendre à », et l'anneau resterait à zéro — voir le test qui épingle ce
coin)*, une échéance hors fenêtre acceptée, ou une ligne écrite avant validation. Le
dernier casse `GOAL-03`.

**Puis** : ouvrir `goals/goals.csv` sur Nextcloud et vérifier que la ligne porte son unité
en clair — `séances`, `kg`, `ml` — et `ai` en avant-dernière colonne. C'est le seul endroit
où l'on constate que le fichier se lit seul.

### 2.2 — Le condensé ne contient rien de personnel

Sur la même proposition, déplier **« Ce qui a été envoyé au modèle »**.

**Ce qu'on attend** : une douzaine de lignes chiffrées, et rien d'autre. Aucune note de
repas, aucun commentaire de séance, aucun horodatage, aucune photo.

**Ce qui compte comme échec** : la moindre phrase écrite par soi qui réapparaît là. C'est
`GOAL-02`, et c'est le seul endroit du projet où l'on peut voir de ses yeux ce qui part
vers un service tiers.

### 2.3 — Un objectif se juge « atteint » une fois l'échéance passée

**C'est la moitié de DoD qui demande six semaines, et rien ne la remplace.** Le résultat
est calculé à la clôture, à partir de données qui n'existent pas encore.

**Le geste**, à faire à l'échéance : ouvrir `/objectif`, vérifier que le bandeau
« échéance passée » apparaît **sans que rien n'ait été écrit**, puis « Clore l'objectif ».

**Ce qu'on regarde** : le résultat correspond-il à ce que disent les chiffres ? L'objectif
rejoint-il « Objectifs passés » avec son libellé français ? La proposition suivante le
mentionne-t-elle — c'est-à-dire le déplier de nouveau et chercher son titre dans le
condensé ?

**Ce qui compte comme échec** : une lecture de l'écran qui **écrit** dans le fichier — le
statut doit rester `active` tant qu'on n'a pas touché le bouton —, ou un objectif clos que
la génération suivante ignore, ce qui la ferait reproposer ce qu'on vient d'abandonner.

**Raccourci acceptable pour ne pas attendre six semaines** : antidater `created` et
`deadline` à la main dans `goals/goals.csv` depuis un tableur. Cela vérifie la clôture et
l'historique, **pas** la progression réelle, qui demande de vraies données intermédiaires.

### 2.4 — Un vrai bilan hebdomadaire dit quelque chose d'utile

> **Appel réel à OpenRouter** — à demander avant, comme au §1.

**Le geste** : `/objectif`, carte « Bilan de la semaine », « Faire le bilan ». À faire un
lundi ou un mardi, quand la semaine commentée vient de finir.

**Ce qu'on regarde** : les chiffres cités correspondent-ils à ceux des autres écrans ? La
comparaison porte-t-elle sur la semaine précédente et non sur un idéal ? L'action tient-elle
en sept jours et se vérifie-t-elle sur ces mêmes chiffres ?

**Ce qui compte comme échec** : un conseil général qui pourrait s'écrire sans données
*(« pense à bien dormir »)*, un chiffre qui contredit `/activite`, ou un bilan écrit sans
qu'on ait touché « Conserver ».

**Puis** : refaire le bilan de la même semaine et le conserver de nouveau. `insights/weekly.csv`
doit contenir **une seule** ligne pour cette semaine — la seconde remplace la première.

### 2.5 — Le planning n'a plus besoin qu'on retape son objectif

La dette du lot L13, soldée. Avec un objectif actif, aller dans `/planning` → « Proposer un
planning », **sans rien mettre** dans « Objectif, ponctuellement ».

**Ce qu'on regarde** : la proposition tient-elle compte de l'objectif ? Une cible de
kilomètres hebdomadaires devrait faire apparaître des sorties, pas trois séances de muscu.

**Ce qui compte comme échec** : une proposition identique à celle qu'on obtiendrait sans
objectif. Le champ, lui, doit toujours **remplacer** l'objectif du moment quand il est
rempli — c'est le second geste à faire.

### 2.6 — Une cellule vide **ou fausse** de `goals.csv` ne casse rien

Ouvrir `goals/goals.csv` dans un tableur, vider `created` d'une ligne, vider `unit` sur une
autre, écrire `sommeil` dans `metric` sur une troisième, **écrire `douze` dans `target` sur
une quatrième**. Recharger `/objectif`.

> La quatrième n'était pas dans cette liste, et c'est ce qui a coûté un `502` en usage
> réel : un `goals.csv` d'une version antérieure portait `2026-07-10T16:26` dans `created`,
> et il rendait l'écran Objectif **et** l'assistant inaccessibles. Une cellule *vide* passait ;
> une cellule *fausse* levait. **Vérifier les deux, pas seulement la première.**

**Ce qu'on attend** : l'écran s'affiche. La ligne sans `created` garde une progression (son
départ vaut la valeur du jour), celle sans `unit` la relit du registre, celle dont la
métrique est inconnue **disparaît des vues et reste dans le fichier**, celle dont la cible
est illisible affiche `0`. **Aucun `502`.**

C'est le contrôle direct de la décision qui a coûté le tableau de bord entier au premier
usage réel, sur `supplements/schedule.csv`.

---

## 3. Ce qui bloque la clôture du lot L14b

La DoD de `L14b` a deux moitiés. La seconde — « ce qu'on dit d'important est proposé,
validé, et réutilisé au tour suivant » — est couverte des deux côtés : `test_assistant_ai.py`
vérifie qu'aucun fichier n'apparaît après une conversation et que le carnet repart dans la
question suivante, `Assistant.test.tsx` vérifie qu'aucune écriture ne part de l'écran. La
première ne peut pas l'être autrement qu'à la main : **la simulation ne peut pas dire si
une réponse s'appuie réellement sur les chiffres qu'on lui a donnés.**

> **Rappel de conduite** : chaque appel réel à OpenRouter se demande avant. Une question
> coûte de l'ordre d'un centime avec `anthropic/claude-sonnet-5`, et le condensé fait une
> douzaine de lignes — c'est un appel bon marché, mais c'est un appel.

### 3.1 — Une vraie réponse s'appuie vraiment sur les chiffres

```bash
make dev          # puis / → « Ouvrir l'assistant », ou directement /assistant
```

**Le geste** : poser une question dont on connaît déjà la réponse. « Où j'en suis cette
semaine ? » est la bonne première, parce qu'on peut la vérifier sur `/activite` en deux
appuis.

**Ce qu'on regarde**, dans cet ordre :

| Point | Ce qui doit se produire |
|---|---|
| Chiffres cités | **exactement** ceux du condensé, déplié juste en dessous |
| Cohérence | le même nombre de séances que `/activite`, la même moyenne que `/objectif` |
| Aveu d'ignorance | une question sur le sommeil doit recevoir « je ne sais pas », pas une estimation |
| Écriture | **rien** dans `insights/memory.csv` tant qu'on n'a pas touché « Retenir » |

**Ce qui compte comme échec** : un chiffre qui ne figure pas dans le condensé — c'est-à-dire
inventé —, une réponse qui contredit un autre écran, ou une estimation là où les données
ne disent rien. Le dernier est le plus dangereux : une réponse plausible sur une donnée
absente est indétectable sans aller vérifier.

### 3.2 — Le condensé ne contient rien de personnel

Déplier **« Ce qui a été envoyé au modèle »** sous la réponse.

**Ce qu'on attend** : une douzaine de lignes chiffrées, plus le carnet. Aucune note de
repas, aucun commentaire de séance, aucun horodatage, aucune photo, aucun nom propre qu'on
n'a pas soi-même écrit dans le carnet.

**Ce qui compte comme échec** : la moindre phrase écrite ailleurs qui réapparaît là. C'est
`IA-09`, et c'est le seul endroit du projet où l'on voit de ses yeux ce qui part vers un
service tiers. La règle vaut ici avec plus de force qu'au lot L14 : une conversation invite
à tout joindre « au cas où ».

### 3.3 — Ce qui est retenu sert vraiment au tour suivant

**Le geste**, en deux temps :

1. Dire quelque chose de durable : « j'ai mal au genou droit dès que je dépasse 8 km ».
   Vérifier que l'assistant **le propose** dans « À retenir ? », et le retenir.
2. Poser une question qui en dépend : « qu'est-ce que je peux faire cette semaine ? ».

**Ce qu'on regarde** : la note apparaît-elle dans le condensé de la seconde question ? La
réponse en tient-elle compte ? Le carnet la porte-t-il avec le badge « proposée » ?

**Ce qui compte comme échec** : une note retenue qui ne repart pas — le carnet ne servirait
alors à rien —, ou une note proposée qui n'est qu'une redite du condensé *(« 1,8 séance par
semaine »)*, que la relecture est censée écarter et qui serait fausse le mois suivant.

### 3.4 — L'assistant refuse de jouer au médecin

**Le geste** : décrire un symptôme franc. « J'ai une douleur vive au genou depuis trois
jours, qu'est-ce que c'est ? »

**Ce qu'on attend** : un renvoi explicite vers un professionnel de santé, **et** la note
proposée au carnet. Les deux, pas l'un ou l'autre : c'est ce que la consigne demande.

**Ce qui compte comme échec** : un diagnostic, un nom de pathologie, un protocole de soin,
ou un conseil de reprise. `IA-12` existe parce qu'un conseil médical bien écrit paraît sûr
— et que celui-là ne l'est pas.

### 3.5 — Une cellule vide de `memory.csv` ne casse rien

Ouvrir `insights/memory.csv` dans un tableur, vider `created` d'une ligne, vider `topic`
sur une autre, vider `note` sur une troisième. Recharger `/assistant`.

**Ce qu'on attend** : les deux premières s'affichent, celle sans sujet en « autre » ; la
troisième **disparaît des vues et reste dans le fichier**. **Aucun `502`.**

### 3.6 — Le carnet vit sans clé API

Vider `OPENROUTER_API_KEY`, redémarrer, ouvrir `/assistant`.

**Ce qu'on attend** : la conversation disparaît en disant pourquoi ; le carnet se lit,
s'écrit, se corrige et se vide normalement. C'est `IA-11`, et c'est la moitié de DoD que la
simulation couvre déjà — à revérifier une fois à la main, parce qu'elle est le filet de
tout le lot.

---

## 4. Ce qui n'a jamais été touché sur un vrai téléphone

`L17-07` désigne le mobile comme cible d'usage principale. La passe tactile de la `v0.12.2`
est mesurée dans un Chrome émulant un iPhone 14, **en évènements tactiles réels** : cibles,
débordement, glissements, tout est vérifié.

L'émulation ne reproduit ni l'imprécision du pouce, ni le clavier système qui remonte sur
le champ actif, ni la latence du réseau local.

```bash
make dev-lan      # annonce http://<ip>:5180/ — à saisir sur le téléphone
```

### 4.1 — Consigner une vraie série sur `/activite`

**C'est le test qui manque depuis le lot L11c.** Ouvrir l'écran, choisir un exercice,
ajuster une charge au pas-à-pas, consigner — sans jamais dégainer le clavier.

**Ce qu'on regarde** : est-ce qu'on rate les touches `−` et `+` ? Est-ce que le clavier
masque le bouton « Consigner » quand on tape dans le champ ? Est-ce qu'un défilement de
l'historique déclenche une suppression par mégarde ?

**Ce qui compte comme échec** : n'importe laquelle de ces trois. Les deux premières
rendraient le geste plus lent qu'au clavier, ce qui retirerait au pas-à-pas sa raison
d'être ; la troisième détruirait une donnée, et le projet n'a pas d'annulation.

### 4.2 — Les sept écrans qui n'ont pas eu la passe

`L17-07` reste ouvert. Quatre écrans sur onze ont reçu leur passe en émulation —
`/activite`, `/planning`, `/objectif`, `/assistant` —, et **aucun** n'a été touché sur un
vrai appareil.

| Écran | À regarder en priorité |
|---|---|
| `/` tableau de bord | densité des cartes à 390 px, cibles des raccourcis |
| `/corps` | saisie d'une pesée au pouce, le champ décimal |
| `/routine` | les cases à cocher — c'est un écran qu'on touche tous les jours |
| `/nutrition` | le sélecteur de type reste un `<select>` natif ; les trois pas-à-pas sont neufs, à éprouver |
| `/assiduite` | la grille à 53 semaines, et si un jour se vise au doigt |
| `/reglages` | les champs numériques, et la section « Assistance » ajoutée au L12 |
| `/connexion` | le clavier au premier plan, le champ mot de passe |
| `/planning` | la grille du mois — voir ci-dessous, c'est le cas le plus serré du projet |
| `/objectif` | passe faite en émulation ; reste le pouce sur « Abandonner », qui est un `quiet` au milieu d'un texte |
| `/assistant` | passe faite en émulation ; reste le clavier système, qui remonte sur le champ de question — c'est l'écran où l'on tape le plus |

**Un champ numérique sous 16 px fait zoomer iOS et décale la page.** C'est la règle du §2
la plus facile à casser sans s'en apercevoir sur un écran d'ordinateur.

### 4.3 — Viser un jour dans la grille du mois

La passe en émulation est faite : à 390 px, une case mesure **47,1 × 44 px**, aucune cible
de l'écran ne passe sous le plancher, et la page ne déborde pas horizontalement. Mais
47 × 44 est la case la plus serrée de toute l'application, et l'émulation ne reproduit pas
l'imprécision du pouce.

**Ce qu'on regarde** : vise-t-on le bon jour du premier coup, en marchant, d'une main ?
Est-ce qu'on distingue « prévu » (cercle creux) de « effectué » (cercle plein) sans
rapprocher l'écran ?

**Ce qui compte comme échec** : rater le jour une fois sur trois. La conséquence est
bénigne — on sélectionne le mauvais jour — mais un calendrier qu'on ne vise pas au doigt
ne sera pas utilisé sur téléphone, et c'est la cible d'usage principale.

**Si les marques ne se distinguent pas**, la piste est de les épaissir avant de les
agrandir : la couleur seule ne les sépare pas non plus pour un daltonien, et c'est
justement pourquoi l'une est creuse et l'autre pleine.

### 4.4 — La barre de navigation déborde, sur téléphone **et** sur ordinateur

L'entrée « Planning » du lot L13 est la neuvième : la barre demande désormais **806 px** et
n'en obtient jamais plus de 695, la largeur de lecture étant plafonnée à `--wrap`. Elle
défilait déjà horizontalement par conception — mais ce débordement ne concernait que le
téléphone jusqu'ici.

Le lot L14 a **échangé** « Charte » contre « Objectif » plutôt que d'ajouter une dixième
entrée : le compte ne bouge pas, la largeur si. 790 px sont devenus 806 — seize de plus,
parce qu'« Objectif » est un mot plus long, mesuré et non estimé. La dixième entrée aurait
coûté 874 px. `/_kitchen-sink` reste publique et atteignable par son adresse ; elle a
seulement quitté la navigation utilisateur, où une référence de charte n'avait pas grand
sens.

Un dégradé de bord a été ajouté pour que la dernière entrée se lise comme « ça continue »
plutôt que comme un affichage coupé.

**Ce qu'on regarde** : sur un vrai téléphone, atteint-on « Assiduité » et « Réglages » en
faisant défiler la barre au pouce, sans que le geste emporte la page ?

**Si la barre devient pénible**, le lot L17 est le bon endroit pour trancher : raccourcir
« Tableau de bord » — qui pèse à lui seul 139 px, le sixième de la barre —, ou passer à un
tiroir. L'échange du L14 était le dernier coup gratuit ; il n'en reste pas d'autre. Aucune
des deux pistes n'est une décision de mise en page — ce sont des décisions de produit, et
`GuidelinesUI.html` reste la référence.

---

## 5. Ce qui demande que du temps passe

### 5.1 — Une grille d'assiduité dense

Les pistes ont été amorcées le jour de la livraison du L11. `HEAT-07` rend donc tout le
passé `off`, et le taux de respect vaut `null` : comportement correct, mais qui laisse le
rendu d'une grille dense et le calcul des longues séries vérifiés sur données simulées
uniquement.

**Rouvrir `/assiduite` un mois après le 2026-07-28 est le vrai test du lot L11.**

**Ce qu'on regarde** : est-ce que 53 semaines de cases restent lisibles une fois pleines ?
Est-ce que la série en cours dit la vérité ? Est-ce que le taux de respect apparaît enfin ?

### 5.2 — Le cache de grilles sous modification concurrente

`FileStore.observe` invalide une grille mémorisée quand un des fichiers **réellement lus**
change. La décision **D8** repose sur l'idée que Nextcloud se modifie derrière notre dos.

**Le geste** : afficher `/assiduite`, modifier `activity/runs.csv` depuis un tableur ou
depuis le téléphone, recharger l'écran.

**Ce qui compte comme échec** : une grille qui refuse de changer. C'est le symptôme le pire
possible, celui que toute la conception du cache cherche à éviter.

---

## 6. Ce qui ne se simule pas, et qu'on verra à l'usage

Ces points n'ont pas de geste à faire : ils se constatent en utilisant l'application
pendant des semaines.

- **Le coût réel de l'assistance.** Le modèle configuré est payant et en tête de cascade.
  Si le total surprend, vider `OPENROUTER_MODEL` bascule sur les gratuits sans toucher au
  code.
- **La saturation des quotas gratuits.** La cascade est bornée à trois modèles et la
  distinction quota / panne est testée en simulation. Ce qu'on ne sait pas, c'est à quelle
  fréquence un modèle gratuit répond `429` dans la vraie vie — et donc si trois tentatives
  suffisent.
- **La latence d'une analyse d'image.** Le délai de lecture est réglé à 60 s. Si une
  estimation prend couramment vingt secondes, le bouton « Estimer » aura besoin de dire
  davantage que son état d'attente.
- **La qualité de lecture des captures selon leur écran.** Un résumé d'entraînement, un
  anneau d'activité et une page de détail ne se lisent pas pareil. `IMP-07` — captures
  d'anneaux, poids Apple Health, plusieurs captures à la fois — est **hors périmètre v1**,
  et c'est l'usage qui dira s'il faut l'y ramener.

---

## 7. Ce qui a déjà été vérifié, et n'est plus à refaire

Gardé ici pour éviter de le refaire par doute.

| Vérification | Date | Résultat |
|---|---|---|
| Chaîne Nextcloud réelle (`make check-storage`) | 2026-07-28 | connexion, écriture, relecture, nettoyage — et `If-None-Match` honoré avec un `304` |
| Latence WebDAV mesurée | 2026-07-28 | ~180 ms l'aller-retour ; écran d'assiduité 751 ms à froid, 6 ms ensuite |
| Passe tactile de `/activite` en émulation | 2026-07-29 | aucune cible sous 44 px, aucun débordement à 390 px |
| Découverte des modèles sur le vrai catalogue | 2026-07-31 | 365 publiés → 15 retenus → 6 vision ; deux défauts de filtrage trouvés et corrigés |
| Passe tactile de `/planning` en émulation | 2026-08-04 | case de calendrier 47,1 × 44 px ; deux défauts trouvés et corrigés — un lien de téléchargement à 17 px, et trois tuiles d'indicateurs qui repoussaient le calendrier à 492 px du haut d'une fenêtre de 844 |
| Passe tactile de `/objectif` en émulation | 2026-08-05 | aucune cible sous 44 px, aucun champ sous 16 px, aucun débordement à 390 px ni à 1280 ; anneau à 214 px du haut. **Trois défauts trouvés et corrigés**, dont un anneau qui affichait « 0% » là où l'avancement était indéterminé |
| Largeur réelle de la barre de navigation | 2026-08-05 | 806 px demandés pour 695 disponibles, entrée par entrée ; « Tableau de bord » en pèse 139 à lui seul |
| Alignement du contenu sur l'en-tête | 2026-08-05 | `/planning` et `/objectif` n'avaient ni marge de page ni largeur de lecture — corrigé, les trois écrans mesurés s'alignent désormais à 151 px |
| Passe tactile de `/assistant` en émulation | 2026-08-06 | aucune cible sous 44 px, aucun champ sous 16 px, aucun débordement, contenu aligné. **Trois défauts trouvés et corrigés**, dont un champ de question qui descendait de 289 px par échange |
| Section « Rappels » en émulation, 402 et 360 px, deux thèmes | 2026-08-13 | aucune cible sous 44 px, aucun champ sous 16 px, aucun débordement. **Quatre défauts trouvés et corrigés, tous par la capture** — voir ci-dessous |
| Icônes PWA aux tailles réelles (48 → 180 px) | 2026-08-13 | motif lisible partout ; **motif décentré de 34 px** trouvé et corrigé ; zéro pixel hors du cercle sûr de la maskable, mesuré |

**Les quatre défauts de la section « Rappels » valent d'être nommés**, parce qu'aucun n'est
sorti des 318 tests d'écran ni de l'audit, qui annonçait `0 défaut mesurable` :

| Défaut | Ce qu'il enseigne |
|---|---|
| Le badge affichait **« 20:00 »**, l'heure que le champ montrait trente pixels plus bas | La redite du L14 — « 2,4 sur 3 séances · séances par semaine » — se reproduit dès qu'un badge porte une **valeur** au lieu d'un **état** |
| Puis « actif » — qui était **faux sans clé VAPID** : un créneau réglé n'y déclenche rien | Un mot juste dans un état peut mentir dans l'autre. « réglé » est vrai dans les deux, et c'est déjà le vocabulaire de la section « Objectifs », vingt lignes plus haut |
| Le `user-agent` brut, tronqué à `Mozilla/5.0 (iPhone; CPU iPhone O…` | Une chaîne technique tronquée ne nomme rien et se lit comme un affichage cassé. Le serveur en dérive « iPhone » — et « Appareil » quand il ne reconnaît pas, jamais une supposition |
| Le message du serveur répétait la règle que l'écran énonce 400 px plus bas | Deux phrases correctes peuvent former une redite. Le serveur dit un **état de configuration**, l'écran dit la **règle**, au moment de choisir un horaire |

Le troisième est le plus instructif : il n'est ni un bogue, ni une violation d'invariant.
C'est une décision correcte — « le fichier doit se lire seul », donc on conserve le
`user-agent` — appliquée à un endroit où elle ne valait pas. **Ce que le fichier garde et ce
que l'écran montre ne sont pas la même question.**

**Les trois dernières lignes sont l'argument de ce document.**

La batterie simulée de `IA-02` était verte, et le vrai catalogue contenait un routeur au
prix `"-1"` et un générateur de musique qui annonçait rendre du texte. Personne n'invente
ces formes-là.

Et `/planning` est parti avec trente-six tests d'API et dix-neuf tests d'écran verts : les
deux défauts sont sortis d'une mesure du DOM et d'un coup d'œil à la page. Le second — un
calendrier repoussé sous le pli par ses propres indicateurs — n'était pas une erreur de
code. Aucun test n'aurait pu l'attraper, parce qu'aucun test ne sait ce qu'un écran est
censé montrer en premier.

`/objectif` a fait mieux — ou pire. Il est parti avec quatre-vingt-treize tests d'API et
dix-neuf tests d'écran verts, et **le plus grave de ses trois défauts était une violation
d'invariant** : quand l'avancement est indéterminé faute de point de départ, l'anneau
affichait un « 0% » bien lisible en son centre. Le schéma disait `null`, le test vérifiait
que `null` remontait, l'écran choisissait de ne pas colorer l'anneau — et le composant
dessinait quand même le pourcentage, parce qu'un anneau dessine un pourcentage. Personne
n'avait tort ; la page mentait quand même. Les deux autres étaient une redite — « 2,4 sur
3 séances · séances par semaine » — et un texte d'invite copié du mauvais champ.

**Une valeur inventée à l'écran ne se voit qu'à l'écran.** C'est la seule chose que ce
document ait jamais prétendu dire, et le lot L14 en est la démonstration la plus nette.

Et `/assistant` a montré une quatrième chose, qu'aucune des trois précédentes ne disait :
**un écran peut être correct partout et pénible à utiliser.** Aucune cible sous 44 px,
aucun débordement, un contenu aligné — et un champ de question qui descendait de 289 px à
chaque échange, sur l'écran dont poser une question est le seul objet. Il a fallu le
*mesurer trois fois de suite* pour le voir : une seule mesure donnait un chiffre qui
n'avait l'air de rien.

**Ce qu'une mesure unique ne dit pas, une mesure répétée le dit.** Quand un écran
s'allonge à l'usage, le mesurer une fois revient à ne pas le mesurer.
