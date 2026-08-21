# Journal des modifications

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Versionnement : une version mineure par lot de la [feuille de route](docs/ROADMAP.md).

## [0.16.0] — 2026-08-06

**Un assistant qui lit tes données, et un carnet qui retient ce qu'elles ne disent pas.**
Le premier lot où l'IA écrit du texte plutôt qu'une mesure — et le premier où l'on peut
*voir*, à l'écran, exactement ce qui part vers un service tiers.

1026 tests backend *(978 → +48)*, 230 frontend *(215 → +15)*.

### Ajouté — la conversation

- **`POST /api/assistant/chat`** (`IA-09`) : une question en français, une réponse appuyée
  sur un **condensé** d'une douzaine de lignes — les cinq métriques et leurs fenêtres,
  l'objectif en cours et sa progression, la série d'assiduité, le respect du planning, les
  bilans récents, les objectifs passés. Rien n'est calculé dans ce domaine : chaque ligne
  vient du service qui en détient la règle.
- **Le condensé est publié** avec la réponse et affiché sous le fil, ligne à ligne. C'est
  ce qui rend `IA-09` vérifiable plutôt que déclaratif — et la règle « jamais les fichiers
  entiers » vaut ici avec plus de force qu'ailleurs, parce qu'une conversation invite à
  tout joindre « au cas où ».
- **Le serveur ne se souvient de rien.** Aucune session, aucun fil stocké : le client rend
  l'historique à chaque question, borné à six échanges. Deux onglets ne se mélangent
  jamais, et il n'existe aucun fichier de discussions qui grossirait sans fin.

### Ajouté — la mémoire de santé

- **`insights/memory.csv`** (`IA-10`, `IA-11`) : un carnet de faits durables — blessure,
  sommeil, traitement, contrainte — que le condensé emporte à chaque question.
- **Proposée, jamais retenue d'office.** Le modèle repère ce qu'on vient de dire sur soi,
  l'écran le montre dans un `AiBlock`, un appui l'écrit. C'est `NUT-04`, `PLAN-04` et
  `GOAL-03` appliqués à du texte.
- **Un carnet, pas une fonction IA** : lire, ajouter, corriger et retirer marchent **sans
  clé OpenRouter**.

### Ajouté — le garde-fou médical

- **`IA-12`** : la consigne interdit diagnostic, traitement et interprétation de symptôme ;
  l'écran porte la mention en permanence, sans possibilité de la fermer. La relecture, elle,
  ne censure rien — filtrer une réponse qu'on a demandée donnerait un texte amputé dont
  personne ne saurait ce qu'il a perdu.

### Décidé

- **La conversation est éphémère, la mémoire est durable.** Historiser les échanges
  coûterait un fichier illisible dans un tableur pour une valeur que trois lignes de carnet
  couvrent mieux.
- **La mémoire porte ce qu'on a dit, pas ce que les CSV savent.** La relecture écarte une
  note dont tous les mots porteurs figurent déjà dans une ligne du condensé : elle serait
  fausse le mois suivant, et contredirait un chiffre recalculé à chaque question.
- **Aucune entrée de navigation.** La barre demandait 806 px pour 695 disponibles ; une
  dixième entrée l'aurait portée à ~897. L'écran s'ouvre depuis une carte du tableau de
  bord et un lien de l'écran Objectif. Le coût est réel et assumé — à rouvrir avec
  `L17-07`.
- **`L14b` est un lot, pas une correction.** La lettre évite de renuméroter `L15` → `L18`,
  ce qui casserait `L17-07`, référencé dans les tokens, trois feuilles de style et cinq
  documents. Les versions des lots suivants glissent d'une mineure.

### Corrigé

- **Un fichier de planning rempli de travers faisait tomber deux écrans en `502`.** Trouvé
  en usage réel, sur `/api/assistant/chat` : un `goals/goals.csv` écrit par une version
  antérieure portait `2026-07-10T16:26` dans une colonne de date, et rendait l'écran
  Objectif **et** l'assistant inaccessibles.

  La cause est plus large que le symptôme. Le §2 promet qu'un fichier de configuration,
  de catalogue ou de planning tolère « une cellule vide, **un nombre illisible**, une
  source mal orthographiée » — mais un défaut de colonne ne couvre que la cellule *vide* :
  `CsvModel.from_csv` ne l'applique qu'à celle-là. Toute cellule remplie de travers levait
  encore, dans `plan.csv`, `goals.csv`, `weekly.csv` et `memory.csv` — quatre fichiers,
  dont un livré au lot L13.

  `CsvDate` et `CsvNumber` (`app/storage/model.py`) retombent désormais sur leur repli au
  lieu de lever. Un horodatage est **récupéré** — le jour y est écrit, le lire n'est pas
  l'inventer — et ce qui est relu de travers se réécrit droit.

- **`/planning` et `/objectif` n'avaient ni marge de page ni largeur de lecture.** L'en-tête
  était plafonné à 1080 px, les cartes touchaient les bords, et le titre collait à zéro —
  deux alignements sur une même page. Trouvé en écrivant [`docs/front.md`](docs/front.md),
  qui a mis l'incohérence en tableau.

### Non vérifié

- **Aucune question n'est passée dans un vrai modèle.** La simulation ne peut pas dire si
  une réponse *s'appuie* réellement sur les chiffres qu'on lui a donnés, ni si ce qu'elle
  propose de retenir vaut d'être retenu. Geste exact au §3 de
  [`docs/verifications-manuelles.md`](docs/verifications-manuelles.md).
- **`/assistant` n'a pas été touché sur un vrai téléphone** — c'est pourtant l'écran où
  l'on tape le plus, et le clavier système ne s'émule pas.

### La leçon du lot

L'écran était correct partout : aucune cible sous 44 px, aucun débordement, un contenu
aligné, trente tests verts. Et le champ de question descendait de **289 px à chaque
échange** — 726, puis 1015, puis 1304 — sur l'écran dont poser une question est le seul
objet. Il a fallu le mesurer *trois fois de suite* pour le voir : une mesure unique donnait
un chiffre qui n'avait l'air de rien.

**Quand un écran s'allonge à l'usage, le mesurer une fois revient à ne pas le mesurer.**

Et une seconde, arrivée le lendemain par un `502` en usage réel : **un test qui vérifie une
cellule vide ne vérifie pas une cellule fausse.** Quatre fichiers promettaient de tolérer
« un nombre illisible » ; quatre batteries ne testaient que le vide, et la promesse était
fausse depuis le lot L13 sans que rien ne le dise.

---

## [0.15.0] — 2026-08-05

**Un objectif chiffré, daté, et une progression qui vient des données.** Le lot qui donne
enfin une réponse à « pour quoi je fais tout ça » — et le premier où l'IA écrit une
intention plutôt qu'une mesure.

Le lot a aussi une leçon, et elle est nette : **trois défauts trouvés en regardant la page,
zéro par les tests**, dont une violation d'invariant que quatre-vingt-treize tests d'API et
dix-neuf tests d'écran laissaient passer.

978 tests backend *(885 → +93)*, 215 frontend *(196 → +19)*.

### Ajouté — les objectifs

- **`goals/goals.csv`**, la deuxième famille de dates futures du projet après le planning.
  Un objectif : un titre, une métrique, une cible, une échéance à 4–8 semaines, une
  justification, un statut, un résultat.
- **Génération** (`GOAL-01`) via `AiService.ask_json`. Le modèle reçoit les cinq métriques
  mesurables avec leurs bornes, les deux dates entre lesquelles l'échéance doit tomber, et
  un condensé factuel. La couche IA du L12 a resservi telle quelle — troisième lot de
  suite, ni modèle à choisir ni cascade à écrire.
- **Données maigres → objectif de régularité** : sous quatre séances en quatre semaines,
  la demande impose `weekly_sessions`, et la relecture refuse tout le reste. Proposer
  « 12 km par semaine » à qui n'a jamais couru n'est pas un objectif mais un vœu.
- **Aperçu, régénération, adoption, abandon** (`GOAL-03`) — le même `AiBlock` et la même
  discipline que `NUT-04`, `IMP-01` et `PLAN-04`. Rien n'est écrit avant l'appui.
- **Progression** (`GOAL-04`) sur les cinq métriques, avec libellé chiffré, fenêtre
  d'observation dite en français, et un anneau qui **disparaît** quand il n'y a rien à
  mesurer.
- **Historique et résultat final** (`GOAL-06`) : atteint, partiel, abandonné. Réinjecté
  dans la génération suivante — sans cela, le modèle reproposerait indéfiniment ce qu'on
  vient de refuser.

### Ajouté — le bilan hebdomadaire

- **`IA-08`** et `insights/weekly.csv` : ce qui a progressé, ce qui a décroché, **une**
  action pour la semaine qui commence. Sur la semaine **révolue** — un « décrochage »
  constaté le mardi peut se rattraper le samedi.
- L'écart plan / réalisé lui est **fourni** par `PLAN-06`, jamais recalculé.

### Ajouté — trois métriques au registre

`daily_protein_g`, `weekly_sessions` et `weekly_distance_km` rejoignent `METRICS`. Elles
manquaient à `GOAL-04` ; les écrire dans le domaine Objectifs aurait donné deux définitions
de « séances par semaine ». `/api/aggregates/series` y gagne trois courbes au passage.

### Décidé

- **La progression part d'un point de départ, pas de zéro.** `courant / cible` afficherait
  105 % d'avancement le jour où l'on vise 78 kg en en pesant 82. Le point de départ est la
  valeur qu'avait la métrique à l'adoption, **redéduite** de `created` : rien n'est stocké
  en plus des onze colonnes de l'annexe, et une seule formule couvre les cinq métriques.
- **Ce n'est pas un quatrième taux de respect.** `AGG-03` mesure le suivi, `HEAT-27` un
  engagement de cadence, `PLAN-06` un rendez-vous. Celui-ci mesure la distance parcourue
  vers un chiffre qu'on s'est fixé. Quatre questions, quatre algorithmes.
- **Les fenêtres s'arrêtent à la période révolue**, et une cadence se divise par le nombre
  de périodes de la fenêtre — jamais par celles qui portent une donnée. Quatre semaines de
  repos puis une semaine à six séances font 1,5 séance par semaine, pas six.
- **Un objectif à la fois, et le refus tombe avant l'appel** : proposer pour se faire
  refuser ensuite serait payer pour apprendre une règle déjà connue du serveur.
- **Une échéance passée ne clôt rien toute seule.** Un `GET` qui écrirait fausserait le
  cache autant que la promesse « rien sans validation ». Le résultat, lui, est calculé par
  le serveur.
- **Une semaine, un bilan** : `week` est la clé naturelle du fichier, et reconserver
  remplace.
- **La navigation échange « Charte » contre « Objectif »** plutôt que de passer à dix
  entrées. 806 px demandés pour 695 disponibles, mesurés — contre 874 pour une dixième
  entrée. `/_kitchen-sink` reste publique et atteignable par son adresse.

### Corrigé

- **Dette du L13 soldée** : le serveur remplit lui-même l'objectif d'une proposition de
  planning depuis `goals.csv`. Le champ de l'écran reste un remplacement ponctuel.

### Non vérifié

- **Aucun objectif n'a encore atteint son échéance.** Le résultat final se calcule sur des
  données qui n'existent pas encore ; c'est la moitié de DoD qui manque, et elle demande
  six semaines. Geste exact au §2 de [`docs/verifications-manuelles.md`](docs/verifications-manuelles.md).
- **Aucun objectif ni bilan n'est sorti d'un vrai modèle.** Développement et tests sur
  réponses simulées ; chaque appel réel se demande avant.
- **`/objectif` n'a pas été touché sur un vrai téléphone**, comme les neuf autres écrans.

### La leçon du lot

L'anneau de progression affichait **« 0% »** quand l'avancement était indéterminé faute de
point de départ. Le schéma rendait `null`, un test vérifiait que `null` remontait, l'écran
choisissait de ne pas colorer l'anneau — et le composant dessinait quand même le
pourcentage, parce qu'un anneau dessine un pourcentage. Aucune de ces quatre décisions
n'était fautive ; la page mentait quand même, et c'était l'invariant le plus ancien du
projet qui tombait.

**Une valeur inventée à l'écran ne se voit qu'à l'écran.**

---

## [0.14.0] — 2026-08-04

**Planning sport, génération assistée, et un flux `.ics` abonnable.** Le premier lot dont
une partie du résultat sort de l'application : un calendrier iPhone affiche les séances
prévues sans que Metric soit ouvert.

C'est aussi le premier domaine à porter des **dates futures**, ce qui suffit à retourner
deux habitudes prises en douze lots — les bornes de saisie refusaient le futur, et la
protection des routes exigeait un jeton que personne ne peut fournir ici.

885 tests backend *(775 → +110)*, 196 frontend *(177 → +19)*.

### Ajouté — le planning

- **`planning/plan.csv`** et le calendrier mensuel (`PLAN-01`) : par jour, ce qui est
  **prévu** et ce qui a été **effectué**, semaine au lundi, mois navigable. Le réalisé est
  lu chez le domaine Activité, jamais recopié — deux vérités sur ce qui s'est passé un
  mardi seraient une de trop.
- **Planifier, corriger, retirer une séance** (`PLAN-02`) : date, heure **facultative**,
  nature, titre, durée, note. Garde anti-conflit par jeton comme partout ailleurs.
- **Écart plan / réalisé et taux de respect** (`PLAN-06`), semaine par semaine.
- **`FileStore.prefetch` sur les trois fichiers** de l'écran : à ~180 ms l'aller-retour
  mesuré sur l'instance réelle, les lire l'un après l'autre coûterait une demi-seconde de
  plus par affichage de mois.

### Ajouté — le flux iCal

- **`GET /api/calendar/{clé}.ics`** (`PLAN-05`), abonnable depuis Apple Calendar ou Google
  Agenda, et **`GET /api/planning/export.ics`** pour un téléchargement ponctuel sous jeton.
- Le module `ical.py` ne connaît ni dépôt ni HTTP : on lui passe des séances, il rend du
  texte. Quatre règles du format y sont écrites une fois — CRLF, pliage à 75 **octets**,
  échappement des quatre caractères spéciaux, heures en UTC.

### Ajouté — la génération assistée

- **`PLAN-03`** via `AiService.ask_json` : fréquence réelle des quatre dernières semaines,
  groupes musculaires délaissés (`ACT-16`), objectif et contraintes libres → une ou deux
  semaines proposées. La couche IA du L12 a servi telle quelle — ni modèle à choisir, ni
  cascade à écrire.
- **Aperçu, retrait individuel, adoption en une fois** (`PLAN-04`), marquée `source=ai`.
  L'écran réutilise `AiBlock` : une seconde façon de dire « pas encore validé » aurait
  affaibli la première.
- **`CsvRepository.extend`** — plusieurs lignes ajoutées en **une** écriture. Adopter huit
  séances en huit `PUT` coûterait plus d'une seconde et laisserait le fichier à moitié
  rempli si la coupure survient à la cinquième.

### Décidé

- **Le flux `.ics` est public, protégé par une clé et non par le JWT.** Un abonnement va
  chercher son fichier tout seul, sans interface où saisir quoi que ce soit et **sans
  pouvoir porter d'en-tête `Authorization`** : exiger le jeton livrerait une fonctionnalité
  incapable de fonctionner. La route est montée au niveau de l'application, avec la santé
  et la documentation, et **ne figure pas dans le schéma publié** — l'y déclarer
  demanderait une exception permanente dans la garde de `AUTH-05`, c'est-à-dire une porte
  ouverte dans le mécanisme même qui les interdit.
  En contrepartie : clé d'au moins **32 caractères** — en deçà le flux n'est pas publié du
  tout, et l'écran dit pourquoi —, comparaison à temps constant, et le même `404` pour une
  clé fausse que pour un flux inexistant. Distinguer les deux confirmerait qu'il y a
  quelque chose à trouver.
- **`plan.csv` est un fichier de planning, pas de mesure.** Toutes ses colonnes portent un
  défaut, `date` comprise, et `time` est facultative **par conception**. C'est le défaut
  qui avait fait tomber le tableau de bord entier en `502` au premier usage réel, sur un
  fichier de la même famille — sauf qu'ici la cellule vide est le cas *normal*, pas
  l'accident.
- **Le planning n'utilise pas `PastDate`** : c'est le seul domaine à porter des dates
  futures. Il a sa borne à lui, `PlannedDate`, à ±400 jours — accepter l'avenir n'est pas
  accepter n'importe quoi, et une faute de frappe sur l'année poserait une séance
  qu'aucun écran ne montre jamais et qui traînerait dans le flux pour toujours.
- **Un troisième taux, et il ne fusionne avec aucun des deux autres.** `AGG-03` mesure
  l'assiduité de *suivi*, `HEAT-27` le respect d'un *engagement* de cadence, `PLAN-06` le
  respect d'un *rendez-vous*. Le rapprochement se fait par **jour** et compte
  `min(prévu, réalisé)` : trois sorties un mardi n'honorent pas trois séances prévues le
  jeudi. Une semaine sans planning n'a pas un taux de 0 % — elle n'a **pas de taux**.
- **Une durée proposée sous 5 minutes est écartée.** La grammaire du projet lit `1:00`
  comme une minute — c'est du `mm:ss`, celui qui fait de `28:45` vingt-huit minutes trois
  quarts. Un modèle qui l'écrit en pensant « une heure » produirait une séance fausse d'un
  facteur soixante, indiscernable à l'œil d'une minute voulue. On n'écrit pas une seconde
  grammaire et on ne devine pas l'intention : on écarte, et le motif s'affiche.
- **Hors fenêtre, on écarte ; on ne recale pas.** Une date que le modèle a inventée ne se
  corrige pas en une autre. C'est la règle du L12 sur les bornes, appliquée au temps.
- **Ce qui est écarté se dit.** Une proposition amputée en silence laisserait croire que le
  modèle n'a suggéré que cela.

### Corrigé

- **`SettingsDep` rendait les réglages du *processus*, pas ceux de l'application.**
  `create_app(settings)` existe pour permettre des applications isolées ; une route qui
  appelle `get_settings()` rend ce paramètre à moitié faux. Sans clé d'abonnement, le
  défaut restait invisible — il ne le serait plus.
- **Deux défauts d'affichage trouvés en regardant la page, aucun par les tests** : un lien
  de téléchargement à **17 px** de haut, et trois tuiles d'indicateurs qui repoussaient le
  calendrier — le sujet de l'écran — à 492 px du haut d'une fenêtre de 844. Le second
  n'était pas une erreur de code : aucun test ne sait ce qu'un écran est censé montrer en
  premier.

### Non vérifié

- **Aucun client de calendrier réel ne s'est abonné au flux.** Il est conforme à la
  RFC 5545 et la garde de sa clé est testée, mais un `.ics` peut satisfaire la spec et
  être refusé par Apple Calendar sans un mot. C'est la moitié de DoD qui manque, et le
  geste est au §0 de [`docs/verifications-manuelles.md`](docs/verifications-manuelles.md).
- **Aucune proposition réelle n'a été demandée à un modèle.** Développement et tests sur
  réponses simulées, via `tests/fake_openrouter.py` ; aucun test de `make check` n'appelle
  OpenRouter.
- **L'écran n'a pas été touché sur un vrai téléphone.** La passe en émulation est faite —
  case de calendrier 47,1 × 44 px, aucune cible sous le plancher, aucun débordement à
  390 px — mais 47 × 44 est la cible la plus serrée du projet.

### Conséquence assumée

- **La barre de navigation déborde désormais aussi sur ordinateur.** « Planning » est la
  neuvième entrée : la barre demande 790 px et n'en obtient jamais plus de 695, la largeur
  de lecture étant plafonnée à `--wrap`. Elle défilait déjà par conception, mais seulement
  sur téléphone. Un dégradé de bord la fait lire comme « ça continue » plutôt que comme un
  affichage coupé ; raccourcir un libellé ou passer à un tiroir sont des décisions de
  produit, et elles appartiennent à `L17-07`.

## [0.13.0] — 2026-07-30

**Couche IA OpenRouter, estimation d'une assiette, import d'une capture Apple.** Ouvre le
jalon IV. C'est le premier lot dont une partie du résultat vient d'ailleurs que du calcul :
un modèle qui regarde une photo et rend des chiffres. Tout le lot est construit autour de
la conséquence — **une valeur proposée n'est pas une mesure**, et rien de ce qui vient d'un
modèle n'entre dans un fichier sans qu'on l'ait validé.

775 tests backend *(655 → +120)*, 177 frontend *(149 → +28)*.

### Ajouté — la couche IA

- **Client OpenRouter unique** (`IA-01`), API compatible OpenAI, transport injectable. Il
  sert déjà deux fonctions et en servira trois de plus (planning, objectifs, bilan) :
  un client par fonction aurait multiplié les délais, les en-têtes et les façons de lire
  une réponse.
- **Découverte des modèles gratuits** (`IA-02`) — coût nul, capables de rendre du texte,
  débarrassés des familles qui ne suivent pas de consigne (modération, plongements,
  synthèse vocale), classés par taille puis fenêtre de contexte, **mémorisés une heure**.
- **Cascade multi-modèles** (`IA-03`), bornée à trois tentatives.
- **Cascade restreinte aux modèles vision** pour tout appel portant une image (`IA-04`).
- **Extraction JSON robuste** (`IA-05`) : monologues `<think>` retirés, premier objet
  **équilibré** retenu.
- **Préparation d'images** (`IA-06`) : 1024 px de côté long, orientation EXIF appliquée,
  JPEG, data URL.
- **`GET /api/ai/status`** — l'écran demande au serveur s'il a une clé, plutôt que de le
  deviner. `GET /api/ai/models` publie le catalogue découvert.

### Ajouté — ce que ça donne à l'écran

- **Estimation d'une assiette** (`NUT-04`) : protéines, sucres ajoutés, calories et une
  description, depuis une photo. Sur le formulaire d'ajout **et** sur un repas déjà
  enregistré — l'écran promet que « les macros peuvent attendre », il fallait une porte
  pour « après ».
- **Import d'une capture Apple** (`IMP-01` → `IMP-06`) sur l'écran Activité : lecture,
  conversions, avertissement de doublon, puis écriture marquée `source=apple`.
- **`Stepper` a un état « proposé »** : trait discontinu, teinte du bloc IA, et un
  `aria-description` — la marque est dite, pas seulement dessinée. Elle disparaît dès
  qu'on retouche la valeur.
- **Les macros de la nutrition passent en pas-à-pas.** Une valeur proposée qu'on ne peut
  pas corriger au pouce sera adoptée telle quelle, ce qui viderait `NUT-04` de son sens.
- **Section « Assistance » dans Réglages** : l'état de l'IA s'y lit, avec le message du
  serveur.

### Décidé

- **La distinction quota / panne est portée par deux exceptions**, pas par un booléen
  (`IA-03`). Les deux mènent à un échec, mais l'un se résout en attendant et l'autre non —
  et l'utilisateur n'a pas la même conduite à tenir. Un seul `429` parmi des pannes suffit
  à basculer le message vers « indisponible » : promettre que l'attente réparera une panne
  serait pire que ne rien promettre.
- **Le modèle lit, il ne convertit pas.** On lui demande de recopier ce qui est affiché,
  unité comprise — `5,20 MI`, `28:45`, `Hier`. La conversion vit dans
  `app/core/parsing.py`, celui-là même qui lit les saisies au clavier : deux grammaires
  finiraient par diverger, et un modèle à qui l'on demande de convertir se trompe d'un
  facteur mille sans que ça se voie.
- **Hors bornes, une valeur est écartée, jamais ramenée à la borne.** Ramener 4000 g de
  protéines à 500 g donnerait une valeur fausse d'apparence honnête ; un champ vide dit ce
  qu'il en est. Même règle pour une fréquence cardiaque à 1852 : le modèle a lu autre
  chose.
- **Une réponse tronquée ne rend rien.** Compléter les accolades manquantes reviendrait à
  inventer les valeurs qu'elles contenaient. Le modèle suivant est essayé.
- **Une course sans distance est proposée en séance.** `runs.csv` porte l'allure, qui
  n'existe pas sans distance : plutôt qu'un pré-remplissage impossible à valider, l'écran
  bascule — et laisse rebasculer en un appui.
- **Le doublon est un avertissement, jamais un refus** (`IMP-04`). Deux sorties de trente
  minutes le même jour, cela existe.
- **Une estimation corrigée reste `source=ai`**, mais une estimation refusée retombe à
  `manual`. Ce que la colonne raconte, c'est d'où vient la ligne.
- **Pillow côté serveur**, et non un redimensionnement dans le navigateur : une photo
  **déjà rangée** sur Nextcloud doit pouvoir être analysée, et un canvas ne la voit jamais.

### Vérifié

Sur **réponses simulées**, par un faux OpenRouter monté en ASGI
(`tests/fake_openrouter.py`) — même parti pris que le faux WebDAV, et pour une raison plus
forte : un vrai appel n'est pas déterministe. Le même modèle, la même photo et la même
consigne rendent deux réponses différentes ; le catalogue gratuit change de semaine en
semaine ; les quotas dépendent de l'heure.

Ce que le double permet de scénariser, et qui est couvert : JSON bavard entouré de
politesses, JSON enfermé dans un bloc de code, monologue `<think>` contenant lui-même des
accolades, monologue **jamais refermé**, objet tronqué en plein nombre, `429` en cascade,
`429` annoncé dans un `200`, modèle muet, catalogue injoignable, catalogue sans aucun
modèle vision, et aucune clé configurée.

**Aucun test de `make check` n'appelle OpenRouter.**

### Vérifié sur le vrai catalogue — et deux défauts en sont sortis

`IA-02` interrogé pour de bon : **365 modèles publiés, 15 retenus, 6 vision.** Le filtrage
et le classement tiennent. Mais la passe a trouvé deux entrées que le filtre acceptait à
tort, et **aucune simulation n'aurait eu l'idée de les écrire** :

- **`openrouter/auto` annonce `"prompt": "-1"`.** C'est une sentinelle « variable » — le
  routeur facture le tarif du modèle vers lequel il route. Un test « pas strictement
  positif » le prenait pour gratuit. Un prix doit désormais valoir **exactement zéro**.
- **`google/lyria-3-clip-preview` annonce `["text", "audio"]` en sortie**, et compose de la
  musique. Un test « `text` est parmi les sorties » le laissait entrer, et il figurait
  dans les modèles **vision** retenus — donc joignable par la cascade d'une analyse de
  photo. La règle est maintenant « du texte, et rien d'autre ».

Le filtre passe ainsi de 22 modèles retenus à 15, et de 10 vision à 6. Les deux cas ont
leur test de non-régression.

C'est la démonstration de ce que le §6 du document d'état répète depuis trois lots :
**ce qui a été trouvé ici l'a été en utilisant la chose, pas en la testant.** La batterie
simulée était verte sur les deux entrées.

### Décidé après la passe réelle

- **Le modèle configuré reste `anthropic/claude-sonnet-5`, payant, et en tête de cascade.**
  Il lit une capture Apple bien mieux qu'un 31B gratuit, et une analyse d'image coûte de
  l'ordre d'un centime. Les gratuits restent le repli quand son quota tombe. C'est un choix
  explicite : `IA-01` rend le modèle configurable précisément pour cela.

### Non vérifié

- **Aucune vraie capture n'est encore passée dans un vrai modèle.** Toute la chaîne est
  couverte de bout en bout contre le double ; ce que la simulation ne peut pas dire, c'est
  si un modèle lit réellement un écran Apple Fitness. C'est la seconde moitié de la DoD,
  et elle reste ouverte.
- **Le HEIC n'est pas analysable** — écart assumé. Pillow ne l'ouvre qu'avec
  `pillow-heif` et sa chaîne de compilation native ; une photo au format iPhone par défaut
  reçoit un refus explicite et le repas s'enregistre normalement.

## [0.12.2] — 2026-07-29

**Passe tactile de l'écran Activité**, et les contrôles qu'elle demandait versés dans la
charte. `L17-07` nommait le mobile « cible d'usage principale » tout en repoussant la
passe au dernier lot ; l'application n'avait donc **qu'une seule media query** et des
cibles à 19 px. Ce qui suit avance ce travail, sans clore `L17-07` — sept écrans sur huit
restent à traiter.

149 tests frontend. Build : 118 → **120 ko gzip**.

### Ajouté — dans la charte, pas dans l'écran

- **`Stepper`** — champ numérique entre deux grosses touches. Le geste du projet sur
  mobile : ajuster une charge d'un pouce entre deux séries, sans ouvrir un clavier qui
  masque la moitié de l'écran. Le champ reste saisissable ; le pas-à-pas est un raccourci.
- **`Chip` et `ChipStrip`** — choix en un appui, sur une bande qui se parcourt au doigt
  avec accroche.
- **`SwipeRow`** — ligne dont un glissement vers la gauche découvre une action
  destructrice.
- **`useHorizontalSwipe`** (`lib/swipe.ts`) — une seule implémentation du geste pour toute
  l'application.
- **Tokens `--tap` (44 px), `--tap-lg` (56 px), `--swipe-threshold`.**
- **Section « 03b — Au doigt » du kitchen sink**, où les quatre se manipulent.

### Modifié — écran Activité

- **Choix de l'exercice en un appui** : une carte par exercice avec sa dernière charge, au
  lieu d'une liste déroulante native qui coûtait un appui, un panneau système, un
  défilement et un second appui — pour le geste le plus répété de l'écran.
- **Charge, séries et réps en pas-à-pas**, la charge par pas de **2,5 kg** — le plus petit
  disque d'une salle, pas un pas décidé à la calculette.
- **Pastilles de charge rapide**, tirées de `max_series` : ce qui a **réellement** été
  soulevé, jamais un arrondi ni une progression supposée.
- **Bande de séances glissante** à la place du sélecteur, et **balayage du journal** pour
  passer d'une séance à l'autre.
- **L'historique n'est plus un tableau** mais une liste de fiches glissables. Six colonnes
  ne se lisent pas à 390 px, et une ligne de tableau ne se tire pas au doigt.
- **Feuille de style retournée en mobile d'abord** : les règles de base décrivent le
  téléphone, les `min-width` ajoutent ce que la place permet.
- **Plancher tactile appliqué à la charte** : boutons, champs, segments — et la navigation
  du shell, qui était à 33 px alors que c'est le contrôle le plus touché de l'application.

### Décidé

- **Pas de curseurs à glisser pour les valeurs.** Viser 82,5 kg sur un curseur est
  difficile, et une mesure fausse entrée sans s'en apercevoir coûte plus qu'un appui de
  plus. Le glissement sert à **naviguer** — entre séances, vers une action — pas à mesurer.
- **Un geste n'est jamais la seule porte.** L'action de suppression existe toujours dans le
  document : révélée par le glissement au doigt, affichée d'emblée là où il y a un pointeur
  fin. On ne découvre pas ce qu'on ne voit pas.
- **Deux appuis pour détruire.** Un glissement part tout seul dans une poche ou en faisant
  défiler ; le projet n'a pas d'annulation.
- **Le pas-à-pas n'est pas un second analyseur de saisie.** Il ne relit que le format
  qu'il écrit lui-même ; `5mi`, `44:12`, `1h30` restent l'affaire du serveur (`ACT-01`).
  Sur ce qu'il ne reconnaît pas, il se désactive au lieu d'écraser la saisie.
- **Un geste plus vertical qu'horizontal appartient à la page.** Sans cette garde, faire
  défiler l'historique au pouce déclencherait une suppression.

### Vérifié

Mesuré dans un Chrome émulant un iPhone 14 (390 × 844, tactile activé), et **conduit en
vrais évènements tactiles** : aucune cible sous 44 px sur tout l'écran, aucun débordement
horizontal, le balayage du journal passe bien de la séance du 28/07 à celle du 25/07, et
tirer une ligne d'historique découvre son bouton (96 px de recouvrement → 0).

Trois défauts en sont sortis, qu'aucun test n'a signalés : « 0 kg » affiché pour un
exercice au poids du corps, des tirets de colonne orphelins sous la date d'une fiche, et
des colonnes qui ne s'alignaient pas d'une ligne à l'autre — chaque fiche étant sa propre
grille, une piste `auto` s'y résolvait selon son seul contenu.

### Outillage

**`make dev-lan`** expose le frontend sur le réseau local, pour ouvrir l'application depuis
un téléphone — ce que la passe tactile réclamait sans qu'aucune commande ne le permette.

Seul Vite est exposé : son proxy relaie `/api` vers `127.0.0.1:8000`, donc l'API et ses
secrets restent hors du réseau. Port dédié **5180 en `--strictPort`** et non le 5173
habituel : Vite ne cherche un port libre que sur l'adresse qu'il va écouter, si bien qu'un
autre projet tenant `[::1]:5173` laisse `*:5173` libre — les deux serveurs démarrent et
l'application obtenue dépend de l'adresse tapée. Le cas s'est produit pendant la mise au
point, et sur un téléphone il aurait été indémêlable.

Le drapeau se passe par une **chaîne, pas un tableau** : sous `set -u`, bash 3.2 — celui
que macOS livre — traite l'expansion d'un tableau vide comme une variable non définie.
Écrit en tableau, `make dev` serait tombé. C'est la deuxième fois que bash 3.2 mord.

### Non vérifié

**Sur un vrai téléphone, avec un vrai doigt.** L'émulation reproduit la taille, la densité
et les évènements tactiles ; elle ne reproduit ni l'imprécision du pouce, ni le clavier
système qui remonte, ni la latence. C'est le prochain test réel de cette passe.

Les sept autres écrans n'ont pas été traités : `L17-07` reste ouvert.

---

## [0.12.1] — 2026-07-29

**Refonte de l'écran Activité.** Pas un lot : la dette d'ergonomie nommée au lot L11, et
la seule des trois qu'un usage réel avait fait remonter. Soldée avant d'ouvrir le jalon IV
parce que l'import Apple du lot L12 (`IMP-02`) pré-remplit une course et une séance — donc
se greffe exactement sur le parcours à refondre. L'argument qui l'avait écartée du L11
(« aucune ligne partagée ») s'inverse pour le L12.

141 tests frontend, dont **treize sur ce seul parcours**. Build inchangé : 118 ko gzip.

### Modifié

- **Le journal de séance est toujours affiché**, en pleine largeur, avec un sélecteur de
  séance. Il n'existait que pendant qu'une séance était ouverte depuis l'historique : au
  chargement, le seul formulaire visible d'emblée était donc le catalogue d'exercices — le
  seul qui ne prend aucun chiffre.
- **La séance la plus récente est ouverte d'office** ; les autres restent à un choix dans
  la liste. Une séance tout juste créée y figure avant même que l'historique ne soit relu.
- **L'ordre affiché suit l'ordre du geste** : journal, puis création de séance et de
  course, puis catalogue — qui se déclare une fois, pas à chaque séance.
- **« Ouvrir » ne charge plus rien**, il désigne. La séance est relue par le journal
  lui-même, qui affiche le refus du serveur **à sa place** plutôt qu'en toast fugace.
- **Supprimer la séance ouverte** ramène le journal sur la précédente au lieu d'y laisser
  un message d'erreur.

### Décidé

- **Le journal reste dans la zone de saisie, il ne remonte pas en tête d'écran.** Les cinq
  écrans du projet posent d'abord les indicateurs, la saisie ensuite ; déplacer celui-ci
  aurait réglé un écran en désalignant les quatre autres. Il est en revanche le **premier
  et le plus large** de sa zone, ce qui suffit à ce que le regard y tombe.
- **Le catalogue n'est pas replié derrière un dépliant.** `GuidelinesUI.html` n'en a pas,
  et inventer un composant hors charte pour reculer une carte d'un cran ne se justifiait
  pas. Le repositionner et dire à quoi il sert suffit.
- **La date ne s'écrit qu'une fois.** Le sélecteur la porte ; la ligne de détail juste en
  dessous la répétait. Trouvé en regardant l'écran, pas en le testant.

### Vérifié

Le parcours a été **conduit dans un navigateur**, pas seulement testé : session ouverte,
`/activite` chargé, exercice choisi — rappel de la dernière charge affiché (`ACT-08`) —,
charge saisie, `POST` émis avec le bon corps, champ vidé, aucune erreur console. Les états
« aucune séance » et « catalogue vide » ont été rendus et relus à l'écran.

Deux défauts en sont sortis, qu'aucun test n'aurait signalés : la date en double, et
« la séance la plus récente est ouverte d'office » qui s'affichait alors qu'il n'y en avait
aucune. C'est la leçon du premier usage réel, appliquée dans l'autre sens.

### Non vérifié

L'écran n'a pas été rejoué contre Nextcloud : la session de développement s'est appuyée sur
une doublure d'API locale, pour ne pas écrire dans les données réelles. Les chemins
serveur, eux, sont inchangés — aucune ligne de backend n'a bougé.

---

## [0.12.0] — 2026-07-28

Lot **L11 — Heatmaps & réglage des pistes**. Il clôt le jalon III : le moteur du lot L10
calculait sans que rien ne l'affiche. 655 tests backend, 133 frontend, **100 % de
couverture toujours tenue sur la machine à états**.

### Ajouté

- **Les trois lectures de la spec §8** (`HEAT-24`, `HEAT-25`, `HEAT-29`) —
  `GET /api/heatmap/{id}`, `GET /api/heatmap?tracks=…`, `GET /api/heatmap/{id}/day/{date}`.
  La forme de réponse suit le §8 au mot près, `from`/`to` compris — un mot réservé de
  Python n'est pas une raison de renommer une clé publique.
- **Cache serveur des grilles** (`HEAT-33`) — clé « piste + plage + jour courant »,
  validité prouvée par l'**empreinte des fichiers réellement lus**.
- **Préchargement parallèle des sources.** Neuf pistes ouvrent sept fichiers ; les lire
  l'un après l'autre coûtait plus d'une seconde sur l'instance réelle.
- **Chiffrage du recalcul rétroactif** (`HEAT-20`, décision **D4**) —
  `POST /api/heatmap/tracks/{id}/preview` rend « 34 journées passeraient de validée à
  manquée » **avant** que rien ne soit écrit. C'est la dette que le lot L09 avait laissée,
  faute de moteur pour la calculer.
- **Écran Assiduité** (`/assiduite`) — toutes les grilles en **un appel**, taux de respect,
  série en cours, record et cumul par piste, tiroir de détail au clic sur une cellule.
- **Réglage des pistes**, dans l'écran Réglages — créer, réordonner, mettre en avant,
  changer la cadence, éditer les seuils avec confirmation chiffrée, neutraliser une plage
  et la rétablir.
- **Nuance d'affichage sur les jours `off`** — le moteur dit désormais *pourquoi* un jour
  n'attendait rien : `neutralised`, `before_track`, `future`, `pending`.

### Décidé

- **La nuance d'un `off` est un champ à part, pas un cinquième état.** Les quatre états de
  `HEAT-05` restent les seuls sur lesquels se décide une couleur, une série ou un taux. Un
  cinquième état aurait contaminé les statistiques ; un champ d'affichage se contente de
  répondre à « pourquoi cette cellule est-elle grise ? ».
- **Les jours à venir se peignent comme les autres `off`, ceux d'avant la piste sont des
  trous.** La plage va jusqu'au dimanche de la semaine en cours : en faire des trous
  donnerait à chaque grille une entaille hebdomadaire qui ne veut rien dire. Avant la
  création de la piste, en revanche, il n'y avait rien à tenir (`HEAT-07`).
- **Le cache s'invalide sur les fichiers observés, pas sur une liste déclarée.** Une liste
  écrite à la main aurait l'air juste et cesserait de l'être au premier fichier lu en plus
  — sans rien signaler, et avec pour symptôme une grille qui refuse de changer après une
  saisie. Les chemins déclarés par chaque source ne servent qu'au préchargement, et un
  test les confronte aux lectures réelles.
- **Une grille servie sans ETag n'est pas mémorisée.** On ne saurait pas l'invalider, et
  un cache qu'on ne peut pas invalider vaut moins que pas de cache.
- **Changer la source ou le filtre d'une piste est rétroactif.** Les deux manquaient à la
  liste du lot L09 : rebrancher « pectoraux » sur « jambes » réécrivait toute la grille en
  passant pour une modification anodine.
- **La refonte de l'écran Activité n'entre pas dans ce lot.** Elle est réelle et reste à
  faire, mais elle ne partage aucun code avec les heatmaps ; l'inclure aurait allongé un
  lot déjà large sans rien mutualiser.

### Mesuré

La question « où passe le temps d'un affichage ? » a été tranchée par un profilage avant
d'écrire la moindre ligne de cache, et la réponse a changé la conception. Sur un an de
saisie simulée — 98 ko, neuf pistes, 371 jours :

| | Avant | Après |
|---|---|---|
| Requêtes WebDAV, cache fichier chaud | 0 | 0 |
| Temps CPU par affichage | ~50 ms | ~5 ms |

**Le réseau était déjà réglé** par le cache de `FileStore` (`STO-06`). Ce qui restait était
du calcul refait à l'identique : 70 % d'analyse CSV et de validation Pydantic — six mille
lignes revalidées par affichage, neuf pistes rouvrant les mêmes cinq fichiers — et 22 % de
moteur. Un cache qui aurait visé le réseau aurait doublé un mécanisme existant sans rien
gagner.

Sur l'**instance Nextcloud réelle**, et c'est la première fois qu'un lot est mesuré
ailleurs que contre un double :

| | Durée |
|---|---|
| Aller-retour WebDAV unitaire | ~180 ms |
| Premier affichage, cache froid | 751 ms |
| Affichage suivant | 6 ms |
| Affichage après expiration du TTL (7 revalidations `304`) | 448 ms |

Sans le préchargement parallèle, la dernière ligne aurait coûté sept allers-retours mis
bout à bout, soit plus d'une seconde pour un écran qui n'a rien à recalculer.

### Vérifié sur l'instance réelle

`make check-storage` a été lancé pour la première fois : connexion, écriture, relecture,
nettoyage, et surtout **`If-None-Match` honoré avec un `304`**. C'était la prémisse de
toute la conception du cache (décision **D8**) ; elle est vérifiée et non plus supposée.

L'écran a ensuite été exécuté contre les vraies données : huit pistes amorcées depuis
l'historique réel, cadences déduites des quatre dernières semaines, et le détail d'une
cellule remonte bien la ligne de saisie qui la compose.

### Non vérifié

- **Aucune grille n'a encore un an d'historique réel derrière elle.** Les pistes ayant été
  amorcées aujourd'hui, `HEAT-07` les rend `off` sur tout le passé, et le taux de respect
  vaut `null` — ce qui est le comportement correct, mais laisse le rendu d'une grille
  dense et le calcul des longues séries éprouvés sur données simulées uniquement.
- **La navigation par plage** n'est pas exposée à l'écran : l'API accepte `from`/`to`, mais
  l'écran s'en tient à la plage par défaut de 53 semaines.
- **Le réordonnancement se fait par « Monter »/« Descendre »**, pas par glisser-déposer.

## [0.11.0] — 2026-07-28

Lot **L10 — Moteur `HEAT` : calcul, cadences, statistiques**. Le cœur du projet, et le
lot où la justesse comptait le plus. 594 tests backend, 106 frontend, **100 % de
couverture sur la machine à états** (l'exigence était 95 %).

### Ajouté

- **Machine à états du jour** (`HEAT-05`) — `off`, `missed`, `done`, `bonus`. Quatre
  états et non cinq niveaux, parce qu'une grille majoritairement `off` n'est pas un
  échec : c'est ce qui rend lisible une piste non quotidienne.
- **Les cinq cadences** (`HEAT-09` → `HEAT-13`). La fenêtre `window` est **glissante** :
  lundi/mercredi/vendredi et mardi/jeudi/samedi sont deux rythmes également corrects, et
  une règle « jours pairs » en punirait un arbitrairement.
- **Intensité découplée de la validation** (`HEAT-15` → `HEAT-17`) — le seuil décide vert
  ou rouge, les bornes décident l'intensité du vert. Un jour à 1,6 L d'eau est validé mais
  reste pâle, l'objectif étant à 2 L.
- **Grille complète** (`HEAT-24`) — aucun jour omis, jamais. Le client n'a aucun trou à
  combler.
- **Statistiques** (`HEAT-26` → `HEAT-28`) — jours validés, attendus, taux de respect,
  plus longue série, série en cours, meilleur jour, cumul, et statuts hebdomadaires.
- **Détail d'un jour** (`HEAT-29`) — chaque cellule est explorable : exercices et séries,
  distance et allure, prises horodatées, volumes bus, domaines renseignés.
- **Plage par défaut** (`HEAT-31`, décision **D6**) — 53 colonnes pleines, du lundi d'il y
  a 52 semaines au dimanche de la semaine courante.

### Décidé

Quatre lectures que la spec laissait ouvertes, chacune avec son test :

- **Un jour neutralisé compte comme satisfait dans une fenêtre glissante.** Sans cela une
  grippe ne casserait pas la série *pendant*, mais produirait un `missed` le lendemain —
  la fenêtre qui s'y referme ne contenant aucune validation. Punir le premier jour de
  convalescence est le contraire de l'intention de `HEAT-06`.
- **Une série se compte en jours de calendrier, pas en validations.** `HEAT-27` l'illustre
  par « une whey un jour sur deux pendant trois mois donne une série de trois mois, pas de
  deux jours » : compter les validations donnerait quarante-cinq, qui n'est ni l'un ni
  l'autre.
- **Un `bonus` prolonge la série.** Une piste « un jour sur deux » tenue *tous* les jours
  produit un `done` puis des `bonus` ; ne compter que les `done` donnerait une série de un
  pour une adhérence parfaite.
- **La semaine en cours n'entre pas dans le taux de respect.** Compter ses créneaux comme
  déjà dus ferait chuter le taux tous les lundis matin — même raison qu'un jour en cours
  n'est jamais `missed`.

Et **un état ajouté à la spec** : `WeekStatus.OFF`. `HEAT-28` en nomme trois, mais sur une
piste `per_week` un jour non validé est `off` (`HEAT-11`) — si bien qu'une semaine sans
rien et une semaine antérieure à la piste se ressemblent trait pour trait. Sans quatrième
valeur, `HEAT-07` serait violé au grain de la semaine.

### Architecture

Trois couches, et c'est ce qui rend la justesse vérifiable :

- `heatmap/engine.py` **juge**, et ne sait rien d'autre. Ni fichier, ni HTTP, ni horloge :
  on lui passe un dictionnaire de dates et il rend une grille. C'est ce qui permet
  d'écrire un test par exemple de la spec, sans monter une application.
- `heatmap/grids.py` **rassemble** les ingrédients et appelle le moteur. Aucune règle
  d'assiduité n'y vit : une règle écrite là échapperait à la batterie.
- `heatmap/sources.py` **réduit** un domaine de saisie à un nombre par jour, et sait
  expliquer ce nombre.

### Non livré, et c'est le découpage prévu

Les endpoints (`GET /api/heatmap/{id}`, lecture multi-pistes, détail d'un jour), le cache
serveur des grilles et l'écran d'assiduité sont le lot **L11**. Le moteur rend aussi
calculable le chiffrage de `HEAT-20` (décision **D4**) laissé en suspens au lot L09 :
« 34 jours passeraient de validé à manqué » s'obtient désormais en évaluant deux fois.

Comme les lots précédents, rien n'a été exercé contre l'instance Nextcloud réelle.

## [0.10.0] — 2026-07-28

Lot **L09 — Moteur `HEAT` : modèle, configuration, pistes**. Premier lot du jalon III,
le cœur du projet. Aucun état n'est encore calculé — c'est le lot suivant — mais tout ce
qui les paramètre existe. 492 tests backend, 106 frontend.

### Ajouté

- **Modèle de piste** (`HEAT-01`) — identifiant, libellé, source, filtre, seuil de
  validation, seuils d'intensité, mode binaire, accent, position, état actif, date de
  création. Toutes les heatmaps de l'application sont des instances de cet objet : il
  n'existe aucun code « heatmap whey » ou « heatmap jambes ».
- **Registre de sources** (`HEAT-02`, `HEAT-03`) — six implémentations derrière une seule
  interface : séries d'un groupe musculaire, distance courue, minutes d'activité, prises
  d'un supplément, volume bu, domaines renseignés. Le contrat tient en une phrase : une
  source rend **un nombre par jour**. Ajouter une piste ne demande aucune ligne de code ;
  ajouter une source est le seul cas qui en demande.
- **Cadences versionnées** (`HEAT-14`) — journal en ajout seul avec date de prise d'effet,
  et résolution de la cadence applicable à n'importe quelle date passée.
- **Jours neutralisés** (`HEAT-06`) — maladie, voyage, deload. `track_id` vide neutralise
  toutes les pistes : une semaine d'arrêt ne se déclare pas neuf fois.
- **Cycle de vie complet** (`HEAT-18` → `HEAT-22`) — créer, modifier, réordonner, mettre
  en avant, désactiver, supprimer. La mise en avant est le réglage `heatmap_metric`,
  celui-là même que le tableau de bord expose sous `highlight` depuis le lot L08.
- **Amorçage** (`heat_backlog` §5) — les pistes par défaut existent au premier affichage,
  peuplées de l'historique réel. Ouvrir l'écran ne doit pas montrer un formulaire vide.

### Décidé

- **L'amorçage crée une piste par supplément du planning**, et non les deux pistes
  « créatine » et « whey » que la spec cite en exemple. Les coder en dur donnerait deux
  grilles vides à qui prend autre chose (`HEAT-18`, `HEAT-23`).
- **Les cadences hebdomadaires sont amorcées sur la fréquence réelle des quatre dernières
  semaines** (décision **D9**), et à une fois par semaine faute d'historique. Amorcer les
  cinq groupes musculaires à deux fois par semaine supposerait dix créneaux hebdomadaires,
  ce qui est beaucoup quand on court aussi — et une grille rouge dès le premier jour est
  une grille qu'on cesse de regarder.
- **La piste eau valide à 1500 ml** (décision **D10**), le gradient d'intensité restant
  inchangé. À un litre, le vert validait des journées à la moitié de l'objectif.
- **La réconciliation planning → journal vit à la lecture.** La décision **D3** veut que
  `schedule.frequency` porte la valeur courante et le journal l'historique. Brancher
  l'alimentation du journal sur la seule écriture de l'application le laisserait muet
  quand le planning est modifié dans un tableur, et le moteur jugerait le passé avec une
  cadence périmée. Une lecture qui répare un journal se justifie quand la justesse du
  journal *est* la fonctionnalité.
- **Une source inconnue rend une grille vide plutôt qu'une erreur.** Le fichier des pistes
  est éditable à la main : une source mal orthographiée doit coûter sa propre grille, pas
  faire tomber l'écran avec les huit autres.

### Corrigé

Le journal des cadences était trié par `(valid_from, id)`. Les identifiants étant
aléatoires, deux prises d'effet posées **le même jour** se départageaient au hasard : une
piste créée puis corrigée dans la foulée gardait l'ancienne règle une fois sur deux. Un
journal daté au jour ne peut s'ordonner que par son propre ordre d'écriture — le tri est
désormais stable sur `valid_from` seul. Trouvé par le test de versionnement, avant tout
usage réel.

### Non vérifié

- **`HEAT-20` est tenu pour l'avertissement, pas pour le chiffrage.** La décision **D4**
  demande d'annoncer l'ampleur d'un changement de seuil (« 34 jours passeraient de validé
  à manqué ») avant de le valider. Compter ces jours suppose la machine à états, qui est
  le lot L10. La réponse porte `recalculated_history` et un avertissement en clair ; le
  compte s'y ajoutera sans changer le contrat.
- Comme les lots précédents, rien n'a été exercé contre l'instance Nextcloud réelle :
  `NEXTCLOUD_URL` pointe toujours sur la racine du site.

## [0.9.0] — 2026-07-28

Lot **L08 — Réglages & agrégats du tableau de bord**. Il ferme le jalon II : les six
domaines de saisie sont derrière nous, et l'écran d'accueil les rassemble enfin.
437 tests backend, 106 frontend.

### Ajouté

- **Endpoint d'agrégats** (`AGG-01`) — `GET /api/aggregates/dashboard` rend poids,
  entraînement, nutrition, hydratation, suppléments, assiduité **et** la série du
  graphique en une requête.
- **Totaux d'entraînement** (`AGG-02`) — total toutes catégories, semaine en cours,
  huit dernières semaines, répartition courses / musculation / autre.
- **Série d'assiduité** (`AGG-03`) — jours consécutifs avec au moins une donnée sur les
  sept sources, plus longue série, état complet des sept derniers jours avec le détail
  des domaines qui ont tenu chaque journée.
- **Séries temporelles génériques** (`AGG-04`) — un contrat unique, onze métriques :
  poids, six mensurations, hydratation, volume et tonnage hebdomadaires, charge par
  exercice. Plages 1 mois / 3 mois / tout, et les cinq statistiques qui vont avec.
  Le catalogue est **publié** (`GET /api/aggregates/metrics`) pour que le sélecteur de
  l'écran ne code aucune liste en dur.
- **Réglages éditables** (`L08-02`) — `PATCH /api/settings`, modification partielle sous
  garde anti-conflit, et un écran Réglages qui dit pour chaque valeur si elle a été
  choisie ou si c'est un repli.
- **Vrai tableau de bord** — rangée de chiffres clés, graphique croisé avec sélecteur de
  métrique et de période, sept derniers jours, répartition d'entraînement, écart à
  l'objectif de poids. La page d'attente du lot L03 disparaît.

### Décidé

- **Le graphique voyage avec le tableau de bord.** `AGG-01` promet une requête pour
  l'écran d'accueil ; un graphique qui demanderait sa série à part rendrait la promesse
  fausse au premier rendu. La réponse porte donc une série par défaut, et le sélecteur
  interroge ensuite `/aggregates/series` sans rien recharger d'autre.
- **Les valeurs de repli sont servies, pas recopiées.** L'annexe du backlog exige que
  backend et frontend s'accordent sur ce que vaut un objectif non renseigné. Le faire
  tenir par la même constante écrite dans deux langages durerait jusqu'au premier oubli :
  le serveur envoie valeurs effectives **et** défauts, et le client n'en code aucun.
- **La garde anti-conflit d'un fichier de configuration porte sur le fichier entier.**
  Un jeu de réglages s'édite en bloc là où un journal s'édite ligne par ligne.
  `Sheet.token` étend `STO-05` à cette granularité, avec la même règle : un `If-Match`
  absent est un conflit, jamais une permission.
- **Trois parts dans la répartition, pas deux.** Le champ `type` d'une séance est libre
  (`ACT-03`) ; ranger une heure de yoga sous « musculation » pour n'afficher que les deux
  parts demandées produirait un chiffre faux. Ce qui n'est ni course ni musculation est
  nommé pour ce qu'il est.
- **La plage d'une série se compte depuis aujourd'hui**, pas depuis le dernier relevé.
  Ancrée sur les points, une fenêtre d'un mois couvrirait un an après une pause, et
  « rien ce mois-ci » s'afficherait comme un mois plein. Une plage vide est une
  information.

### Corrigé

Deux défauts du socle, trouvés en construisant le lot :

- **L'absence d'un fichier n'était pas cachée.** Un 404 invalidait l'entrée au lieu de la
  mémoriser. Sur une installation neuve — donc au premier lancement — le tableau de bord
  redemandait chaque fichier inexistant à chaque domaine qui le voulait. L'économie de
  `AGG-01` se serait payée en allers-retours invisibles côté serveur. La fenêtre
  d'incohérence reste le TTL, comme pour un contenu déjà lu (décision **D8**).
- **Une cellule vide dans `settings.csv` rendait le fichier illisible.** `value` était une
  colonne requise : vider un réglage à la main dans un tableur faisait tomber le poids
  cible, l'objectif d'hydratation et le plafond de sucres d'un coup, et plus un écran ne
  s'affichait. Un réglage abîmé doit coûter son propre repli, pas l'application.

### Non vérifié

Le lot n'a **pas** été exercé contre l'instance Nextcloud réelle : `NEXTCLOUD_URL`
pointe toujours sur la racine du site au lieu du point d'accès WebDAV (voir le §6 de
`docs/etat-du-projet.md`). Tout est vérifié contre le double WebDAV, y compris le
comptage des lectures par fichier — mais la latence réelle d'un tableau de bord qui
ouvre neuf fichiers reste à mesurer.

## [0.8.0] — 2026-07-27

Lot **L07 — Nutrition & fichiers binaires**. Le premier lot où un bug de chemin devient
une faille. 381 tests backend dont **35 de sécurité**, 86 frontend.

### Ajouté

- **Repas** (`NUT-01` → `NUT-03`, `NUT-05` → `NUT-07`, `NUT-09`) — photo et/ou
  description, rangement daté, type présélectionné par le serveur, macros manuelles,
  totaux du jour, liste bornée ou complète, correction préservant photo et provenance.
- **Repas favoris** (`NUT-10`) — ce qui revient chaque jour se rejoue en une action.
- **Service sécurisé des photos** (`NUT-08`) — endpoint authentifié, forme de chemin
  imposée, réponses cachables un an et non reniflables.
- **Écran Nutrition** — anneau de protéines, journal avec vignettes chargées **avec le
  jeton de session** (un `<img src>` naïf recevrait un 401), saisie photo avec aperçu.
- Le client API sait désormais envoyer un formulaire multipart, en laissant au navigateur
  le soin d'y poser la frontière de séparation.

### Sécurité

Trois décisions, toutes vérifiées par des tests écrits du point de vue de quelqu'un qui
essaie de sortir du dossier :

- **La forme prime sur le nettoyage.** Un chemin qui ne correspond pas exactement à
  `AAAA/MM/JJ/horodatage-aléa.ext` est refusé, sans tentative de le réparer. Huit
  tentatives d'évasion testées — `../`, encodage URL, chemin absolu, octet nul,
  antislash, double encodage.
- **Le contenu décide du type**, jamais le nom de fichier ni le `Content-Type` annoncé
  par le client. Servir des octets arbitraires sous un type d'image offrirait une surface
  au navigateur.
- **Un chemin mal formé et un chemin absent rendent le même 404.** Les distinguer
  renseignerait sur l'arborescence.

### Décidé

- Supprimer un repas **ne supprime pas sa photo**. Elle est rangée par date et
  consultable hors de l'app ; l'effacer d'un clic dans une liste ferait perdre un souvenir
  qu'aucune annulation ne rendrait. La suppression du fichier reste manuelle, et assumée.
- Le total de calories est accompagné du **nombre de repas réellement renseignés** : un
  total sur deux repas sur cinq ne veut pas dire grand-chose, et l'écran doit pouvoir le
  nuancer plutôt que d'afficher un chiffre trompeur.

## [0.7.0] — 2026-07-27

Lot **L06 — Hydratation & suppléments**. Les deux domaines « en un geste », et les
dernières sources dont le moteur d'assiduité aura besoin. 311 tests backend, 72 frontend.

### Ajouté

- **Hydratation** (`HYD-01` → `HYD-05`) — prise horodatée avec son décalage, raccourcis
  de volume paramétrables, total du jour face à l'objectif, série complète sur 30 jours,
  moyennes 7 et 30 j, jours ayant atteint l'objectif.
- **Suppléments** (`SUP-01` → `SUP-06`) — planning trié par horaire, checklist du jour qui
  repart vierge chaque matin, série par item, ratio et booléen « journée complète ».
  Cocher écrit une prise horodatée, décocher la supprime — et elle seule.
- **`app/core/dates.py`** — le jour local et la semaine ISO n'ont plus qu'une
  implémentation. Deux endroits qui découpent le temps finissent par donner deux totaux
  pour la même journée.
- **`app/core/cadence.py`** — grammaire des cadences, validée à la saisie et normalisée.
  La décision **D3** lie `schedule.frequency` au futur journal d'historisation : sans
  normalisation, deux écritures équivalentes enregistreraient un changement de cadence
  qui n'en est pas un. Ce module ne décide pas encore si un jour est validé.
- **Écran Routine** — anneau d'hydratation, raccourcis en un geste, checklist groupée par
  moment de la journée, planning avec sa cadence en clair.
- **Bascule optimiste** (`SUP-04`) — la case se coche avant la réponse du serveur et se
  **restaure** si elle est refusée. Attendre un aller-retour vers Nextcloud pour voir une
  case bouger condamnerait la saisie en un geste.

### Vérifié

- **La frontière de jour.** Une prise à 23 h 30 appartient au jour qu'affiche l'horloge ;
  une prise à 0 h 30 au jour qui commence ; un horodatage sans fuseau — le cas d'une
  ligne saisie dans un tableur — est lu comme local et non comme UTC (`HEAT-32`).
- **Une valeur de réglage contenant des virgules** dans un fichier qui les utilise comme
  séparateur : elle doit être protégée par des guillemets. Notre écrivain le fait, un
  test le prouve — mais une ligne ajoutée à la main sans guillemets serait tronquée
  silencieusement.

## [0.6.0] — 2026-07-26

Lot **L05 — Activité sportive**. Le plus gros domaine du backlog, 18 fonctionnalités, et
la source de six des neuf pistes d'assiduité à venir. 241 tests backend, 61 frontend.

### Ajouté

- **Courses** (`ACT-01`, `ACT-02`, `ACT-05`) — saisie en formats souples : `44:12`,
  `1:18:44`, `44`, `44,5`, `1h30`, et `5mi` converti en kilomètres. Allure dérivée **et
  stockée**, vitesse dans le détail.
- **Séances** (`ACT-03`, `ACT-04`, `ACT-18`) — identifiant stable qui survit aux
  corrections, effort perçu 1–10, sept types suggérés sans contrainte. Supprimer une
  séance purge ses exercices.
- **Catalogue et journal** (`ACT-06` → `ACT-09`) — neuf groupes musculaires, charge ×
  séries × réps, charge 0 = poids du corps, et le rappel de la dernière performance à la
  sélection d'un exercice.
- **Agrégats** (`ACT-10` → `ACT-16`) — volume par jour avec repos distingué de zéro,
  totaux de semaine ISO, huit semaines d'historique, historique fusionné, tonnage par
  groupe, records et 1RM par Epley, groupes négligés.
- **Duplication d'une séance** (`ACT-17`) — exercices compris, sans hériter du RPE :
  l'effort perçu appartient à la séance vécue, pas au modèle.
- **`app/core/parsing.py`** — analyse des durées, distances et décimales françaises,
  placé dans le socle parce que l'import Apple (`IMP-03`) devra normaliser exactement les
  mêmes formats.
- **`remove_where`** sur le dépôt CSV — suppression en cascade en une écriture, plutôt
  qu'une par ligne qui laisserait le fichier dans un état intermédiaire.
- **Écran Activité** — semaine, volume par jour, tonnage, groupes négligés, progression
  des charges, historique fusionné, saisie de course et de séance, journal d'exercices et
  catalogue.

### Corrigé

- Deux champs portaient le libellé « Durée » sur la même page : ambigu pour un lecteur
  d'écran comme pour un test. Celui de la séance est désormais « Durée de séance ».

### Choix de modélisation

- `exercise_log.csv` **duplique** le nom de l'exercice et son groupe musculaire alors
  qu'il porte déjà `exercise_id`. `ACT-06` exige que retirer un exercice conserve
  l'historique : sans duplication, une ligne deviendrait illisible dès que son exercice
  disparaît, et le fichier doit rester compréhensible seul dans un tableur.
- Un groupe musculaire jamais travaillé rend `null` et non un grand nombre : « jamais »
  et « il y a très longtemps » ne se traitent pas pareil, et une valeur inventée
  fausserait la génération IA de planning (`PLAN-03`).

## [0.5.0] — 2026-07-26

Lot **L04 — Corps : poids et mensurations**. Première tranche verticale complète, et
patron des cinq domaines suivants. 169 tests backend, 49 frontend.

### Ajouté

- **Pesées** (`BODY-01` → `BODY-06`) — saisie bornée, correction et suppression sous
  garde, indicateurs, série chronologique, tendance lissée et historique paginé, le tout
  en **une seule requête** par écran.
- **Mensurations** (`BODY-07` → `BODY-10`) — six mesures facultatives dont la masse
  grasse, au moins une requise. Chaque mesure garde son propre historique : « le relevé
  précédent » d'un tour de bras n'est pas forcément la ligne d'avant.
- **Écran Corps** — quatre chiffres clés, courbe de poids avec tendance superposée sur le
  même axe, saisie, historique éditable, panneau mensurations. Aucune valeur inventée :
  sur historique vide, l'écran dit ce que coûte le prochain geste.
- **Jeton de ligne** — chaque entrée porte l'empreinte de son contenu ; modifier ou
  supprimer exige de la renvoyer en `If-Match` (`STO-05`). Un en-tête absent est un
  conflit, jamais une permission — sinon la garde se contournerait en l'omettant.
- **Lecteur de réglages** — `settings/settings.csv` avec les défauts de l'annexe, pour
  que l'écart au poids cible ne soit pas une constante codée en dur.
- **Superposition dans `Chart`** — une série partageant l'unité de la principale se trace
  sur le **même axe**, contrairement à la série de contexte.
- [`docs/patron-domaine.md`](docs/patron-domaine.md) — les quatre fichiers, les deux
  pièges de calcul rencontrés, les huit familles de tests, et une liste de reprise.

### Corrigé

- **`test_every_data_route_requires_a_token` ne vérifiait rien.** Il parcourait
  `app.routes`, où FastAPI n'aplatit pas les routeurs inclus : la seule route visible
  était la santé, justement exemptée. Il lit désormais le schéma OpenAPI publié, et un
  second test interroge réellement chaque lecture sans jeton.
- **`check-storage` ne diagnostiquait pas l'erreur de configuration la plus probable.**
  Une `NEXTCLOUD_URL` pointant sur la racine du site donne un « ressource introuvable »
  incompréhensible ; le script nomme la cause et donne la ligne à coller.

### Vérifié

- Stockage éprouvé contre le **vrai Nextcloud** : écriture, relecture identique, `304`
  honoré sur lecture conditionnelle, nettoyage. Le point resté ouvert depuis le lot L01
  est fermé.

## [0.4.0] — 2026-07-26

Lot **L03 — Design system et coquille applicative**. Le jalon I est bouclé : l'application
se connecte, navigue, et dispose de toute la bibliothèque visuelle. 37 tests frontend.

### Ajouté

- **18 composants** repris de la charte : `Button` (5 variantes), `Card`, `Badge`,
  `Field`, `Rule`, `Eyebrow`, `Segmented`, `Empty`, `AiBlock`, `Stat`, `Sparkline`,
  `Bars`, `Progress`, `Ring`, `Table`, `Check`, `Heatmap`, `Chart`, `Toaster`.
- **`Heatmap`** — six états distincts, dont la distinction qui compte : `off` (rien
  n'était attendu) et `missed` (attendu, non validé) ne se ressemblent pas. Une piste
  « deux fois par semaine » est majoritairement grise, et une grille grise ne doit pas se
  lire comme un échec (`HEAT-05`). Le composant ne décide rien : états et niveaux
  viennent du serveur (`HEAT-30`).
- **`Chart`** — axe gradué, aire dégradée, série de contexte en pointillé, bande
  inférieure à seuil d'alerte, curseur et infobulle suiveuse.
- **Client API typé** — injection du jeton, décodage de l'enveloppe `{code, message,
  fields}`, distinction entre panne réseau et refus métier, et purge du jeton sur session
  expirée en un seul endroit (`AUTH-06`).
- **Écran de connexion et routes protégées** — le jeton présent au démarrage est
  **confronté au serveur** plutôt que cru sur parole ; sans cela un jeton expiré pendant
  que l'app était fermée afficherait l'application puis ferait échouer chaque écran.
- **TanStack Query configuré** — clés nommées par domaine, réessai réservé aux pannes
  passagères. Une mutation n'est jamais rejouée : réessayer une écriture en conflit est
  le meilleur moyen d'écraser la mauvaise ligne (`STO-05`).
- **Formateurs** — dates FR, `mm:ss` / `h:mm:ss`, allure, volumes, virgule décimale, et
  une sérialisation de date en **heure locale** : `toISOString()` rattacherait au mauvais
  jour une saisie faite après minuit (`HEAT-32`).
- Galerie de charte complète sur `/_kitchen-sink`, **publique** : aucune donnée
  utilisateur, consultable sans session, et vérifiable par capture automatisée.

### Corrigé

- `tokenStore` avalait silencieusement l'indisponibilité de `localStorage`, ce qui aurait
  fait perdre la session au premier rechargement sans rien annoncer — navigation privée
  Safari, cookies bloqués. Repli en mémoire détecté à l'exécution, et `persistent`
  permet de le signaler.

### Retiré

- L'écran d'attente `Home` du lot L00, remplacé par le tableau de bord et l'écran de
  connexion.

## [0.3.0] — 2026-07-26

Lot **L02 — Socle API + authentification**. L'API est désormais close : plus aucune route
de données n'est joignable sans jeton. 134 tests backend, 96 % de couverture.

### Ajouté

- **Connexion mono-utilisateur** (`AUTH-01` → `AUTH-03`) — Argon2id, JWT signé de 7 jours,
  `Authorization: Bearer`. La session survit à la fermeture de l'app et au redémarrage.
- **Anti-brute-force** (`AUTH-04`) — 5 échecs / 60 s / adresse, fenêtre glissante en
  mémoire, `429` annonçant le délai en corps et en en-tête `Retry-After`. Trois détails
  qui font la différence : Argon2 est exécuté **même sur identifiant inconnu** (sinon le
  temps de réponse dirait lequel des deux champs est faux), le quota est consulté **avant**
  de hacher (sinon l'attaque coûterait plus au serveur qu'à l'attaquant), et une réussite
  remet le compteur à zéro.
- **Protection des routes** (`AUTH-05`) — portée sur le groupe de routeurs de données, pas
  route par route : un endpoint ajouté par un lot ultérieur est protégé par construction.
  Un test structurel le vérifie à chaque exécution.
- **`make hash-password`** (`AUTH-08`) — saisie sans écho, jamais de mot de passe en clair
  sur disque ni en argument de commande, propose aussi un `JWT_SECRET`.
- **Catalogue d'erreurs** (`API-07`) — un module unique, codes machine stables, messages
  français. Quatre gestionnaires couvrent le métier, la validation, les erreurs de FastAPI
  et l'imprévu — aucun traceback ne sort jamais dans une réponse.
- **Socle de validation** (`API-06`) — 18 types bornés réutilisables, et une règle
  « jamais dans le futur » évaluée en **heure locale** : à 1 h du matin à Paris, `date.today()`
  en UTC serait encore la veille et refuserait une pesée légitime.
- **Découpage par domaine** (`API-01`) — 12 routeurs préfixés, prêts à recevoir leurs
  routes lot par lot.
- **Refus de démarrer en production** avec un secret de développement, un hash de mot de
  passe absent ou un stockage non configuré (`API-02`).
- `/api/health` annonce désormais aussi `auth_configured`.

### Modifié

- `StorageError` descend de `MetricError` : un seul gestionnaire traduit tout le catalogue.
- Les messages d'erreur de FastAPI sont traduits — un 404 de routage répondait
  « Not Found » en anglais alors que l'API est francophone.
- `DEV_JWT_SECRET` allongé à 50 caractères : PyJWT signale toute clé HMAC de moins de
  32 octets comme trop courte pour SHA-256 (RFC 7518 §3.2).

### Non vérifié

- `make check-storage` contre un vrai Nextcloud : `NEXTCLOUD_USERNAME` et
  `NEXTCLOUD_PASSWORD` sont encore vides dans `.env`.

## [0.2.0] — 2026-07-26

Lot **L01 — Couche stockage WebDAV + CSV**. La pièce la plus risquée du projet : tout le
reste s'appuie dessus. Aucune fonctionnalité visible, mais 79 tests backend et 95 % de
couverture sur la couche stockage.

### Ajouté

- **Client WebDAV** (`STO-01`, `STO-08`) — GET / PUT / DELETE / MKCOL / PROPFIND, pool de
  connexions borné et maintenu en keep-alive, réessais sur erreur de transport, `429`,
  `423` (verrou Nextcloud) et 5xx, `Retry-After` honoré qu'il soit exprimé en secondes ou
  en date HTTP, backoff exponentiel plafonné avec gigue. L'attente est injectable : les
  délais sont testés sans être subis.
- **Erreurs typées** (`STO-09`, `API-07`) — chaque panne porte un code machine stable
  (`storage_unavailable`, `conflict`, `storage_not_configured`…) et un message français.
  Jamais de 500 brute ; le détail technique va dans les journaux, pas dans la réponse.
- **Cache des lectures** (`STO-06`, décision **D8**) — TTL de 30 s, puis revalidation
  conditionnelle par ETag. Un tableau de bord qui tire dix fichiers ne fait pas dix
  requêtes, et une modification faite depuis un autre appareil ou un tableur est
  rattrapée : l'invalidation ne suit pas seulement nos propres écritures.
- **Dépôt CSV typé** (`STO-02` → `STO-05`) — modèles Pydantic, migration d'en-tête
  automatique, garde anti-conflit par valeurs attendues doublée d'un `If-Match` sur
  l'ETag du fichier, lecture fraîche forcée avant toute écriture sous garde.
- **Fichiers binaires** (`STO-07`) — arborescence datée `AAAA/MM/JJ`, création des
  parents une seule fois, hors du cache CSV.
- **`make check-storage`** (`STO-11`) — écrit, relit, vérifie la revalidation
  conditionnelle et nettoie derrière lui. Diagnostique une configuration absente, de
  mauvais identifiants ou un serveur sans ETag sans jamais lever de traceback.
- **Faux serveur WebDAV ASGI** en mémoire, avec injection de pannes : conflit, coupure
  réseau, `429` avec `Retry-After`, verrou de fichier, serveur qui n'annonce aucun ETag.
- Cycle de vie de la couche stockage piloté par le `lifespan` de FastAPI, et dépendance
  `StoreDep` pour les domaines à venir.

### Corrigé

- `FileStore` remplaçait silencieusement le cache qu'on lui passait : `FileCache` définit
  `__len__`, donc un cache vide est *falsy* et `cache or FileCache()` le jetait.
- `ensure_collection("")` ne créait rien, si bien que le dossier racine des données
  n'existait jamais au premier démarrage — le premier `PUT` aurait échoué en `409`
  incompréhensible.
- `CsvModel.from_csv` forçait `None` sur une colonne absente au lieu de laisser le défaut
  du modèle s'appliquer, ce qui invalidait toute ligne ancienne dès l'ajout d'une colonne
  et vidait `STO-04` de son sens.

### Modifié

- Exceptions de stockage suffixées `Error` (`StorageConflictError`, `StorageNotFoundError`…)
  conformément à la convention Python plutôt qu'en silençant la règle de lint.
- `CsvRepository` utilise la syntaxe générique PEP 695 (`class CsvRepository[TModel]`).
- `pytest-asyncio` en mode `auto` : la couche stockage est asynchrone de bout en bout.

### Non vérifié

- `make check-storage` contre un vrai Nextcloud : impossible sans identifiants. Le
  développement s'est fait contre le double ASGI.

## [0.1.0] — 2026-07-26

Lot **L00 — Fondations, outillage, tokens UI**. Le dépôt démarre, se teste et parle
déjà la langue visuelle de Metric. Aucune fonctionnalité métier.

### Ajouté

- Dépôt initialisé : `.gitignore`, `.editorconfig`, `README`, réglages VS Code pointant
  sur le venv du backend.
- **Backend** — squelette FastAPI (Python 3.14) : configuration centralisée par
  environnement (`API-02`), route de santé publique `/api/health` (`API-04`), OpenAPI
  sur `/api/docs` (`API-05`), CORS paramétrable (`API-03`). `ruff`, `mypy --strict` et
  `pytest` configurés. 5 tests.
- **Frontend** — Vite 8 + React 19 + TypeScript 6 strict, TanStack Query et React
  Router installés, ESLint + Prettier, Vitest + Testing Library. 5 tests.
- **Tokens UI** extraits de `GuidelinesUI.html` vers `styles/tokens.css`, complétés par
  les composantes RVB des signaux — ce qui permet de dériver les 4 niveaux d'intensité
  d'une heatmap depuis une seule couleur d'accent par piste.
- **Polices servies localement** : Space Grotesk et JetBrains Mono téléchargées par
  `npm run fonts` et versionnées (14 fichiers woff2, 308 ko). Plus aucune dépendance au
  CDN Google — prérequis du fonctionnement hors-ligne (`L15`).
- `base.css` : reset, typographie, primitives de mise en page, règle graduée,
  `prefers-reduced-motion`, chiffres à chasse fixe.
- Page `/_kitchen-sink` : référence visuelle des tokens, test de dérive de la charte.
- Écran d'accueil provisoire sondant `/api/health` : prouve le proxy et illustre la
  dégradation propre quand Nextcloud ou l'IA ne sont pas configurés (`IA-07`).
- `Makefile` (`setup`, `dev`, `check`, `test`, `fmt`, `build`, `fonts`) et
  `scripts/dev.sh` qui lance les deux serveurs et les arrête ensemble.
- `.env.example` documenté et complet.
- CI GitHub Actions : formatage, lint, types, tests des deux côtés, plus build.
- `docker-compose.yml` de développement — écrit, non exécuté (Docker absent de la
  machine ; validation au `L17-01`).

### Décidé

- Les **11 points de spécification** relevés entre `backlogV2.md` et `heat_backlog.md`
  sont arrêtés et consignés au [§3 de la feuille de route](docs/ROADMAP.md#3-points-de-spécification-à-trancher).
- `httpx2` remplace `httpx` dans tout le projet : starlette 1.x déprécie `httpx` pour
  son `TestClient`, et le client WebDAV du lot L01 doit parler la même bibliothèque que
  les tests.
- TypeScript **6.0** et non 7 : `typescript-eslint` exige `<6.1.0`. Le lint prime sur
  la dernière majeure.
- Aucune bibliothèque de graphiques ni kit UI : la charte fournit déjà courbes, barres,
  anneau, heatmap et graphique croisé en SVG.
