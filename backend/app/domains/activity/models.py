"""Modèles CSV du domaine Activité.

Colonnes reprises de l'annexe du backlog. Quatre fichiers, et une décision de forme qui
mérite d'être nommée : `exercise_log.csv` **duplique** le nom de l'exercice et son groupe
musculaire, alors qu'il porte déjà `exercise_id`.

Ce n'est pas un oubli de normalisation. `ACT-06` exige que retirer un exercice du
catalogue conserve tout l'historique : sans duplication, une ligne de journal deviendrait
illisible dès que son exercice disparaît. Le fichier doit rester compréhensible seul,
dans un tableur, des années après (`STO-02`).
"""

from __future__ import annotations

from datetime import date, time
from enum import StrEnum

from app.storage.model import CsvDate, CsvModel


class MuscleGroup(StrEnum):
    """Taxonomie de saisie (`ACT-06`) — neuf valeurs, et elles ne bougent pas.

    Le regroupement en pistes d'assiduité (`HEAT`) est un **réglage** posé par-dessus,
    pas une contrainte sur cette liste.
    """

    PECTORAUX = "pectoraux"
    DOS = "dos"
    EPAULES = "épaules"
    BICEPS = "biceps"
    TRICEPS = "triceps"
    JAMBES = "jambes"
    FESSIERS = "fessiers"
    ABDOS = "abdos"
    AUTRE = "autre"


#: Types de séance proposés à la saisie (`ACT-03`). Suggestions et non contrainte : le
#: champ reste libre, on ne va pas empêcher d'écrire « escalade ».
WORKOUT_TYPES: tuple[str, ...] = (
    "musculation",
    "vélo",
    "natation",
    "HIIT",
    "yoga",
    "marche",
    "football",
)


class RunRow(CsvModel):
    """Une course. `activity/runs.csv`."""

    date: date
    distance_km: float
    duration_min: float
    #: Allure stockée avec la course (`ACT-02`) : recalculable, mais la conserver rend le
    #: fichier lisible sans outil.
    pace_min_km: float | None = None
    avg_hr: int | None = None
    elevation_m: int | None = None
    #: Cadence en pas par minute. Colonne ajoutée au lot C06 : les lignes écrites avant
    #: portent une cellule vide, ce qui est une valeur légitime et non un fichier cassé
    #: (`STO-04`). Rien ne la déduit — une cadence ne se calcule pas depuis une allure.
    cadence_spm: int | None = None
    note: str | None = None
    source: str = "manual"
    #: Identifiant **stable** de la course, sur le modèle de `WorkoutRow.id` : les paliers
    #: s'y rattachent, et `id` — la position dans le fichier — se décale à la première
    #: suppression. Vide sur les lignes écrites avant le lot C08, ce qui est légitime
    #: (`STO-04`) : elles n'ont pas de paliers, et on ne leur en inventera pas.
    run_id: str = ""
    #: Calories **totales**, métabolisme de base compris. `calories` tout court n'existe
    #: pas ici, et c'est délibéré : une capture Apple en affiche deux — 439 actives, 492
    #: totales — et un champ sans qualificatif finirait par mélanger les deux d'une course
    #: à l'autre.
    total_calories: int | None = None
    #: Calories **actives**, la dépense de la séance seule. Le lot C08 les laissait hors du
    #: fichier « tant qu'aucun écran ne les demande » ; la page Course les demande, et les
    #: lisait déjà sur la capture pour les jeter ensuite. Colonne en fin d'en-tête, comme
    #: les précédentes : les lignes d'avant portent une cellule vide (`STO-04`).
    active_calories: int | None = None
    #: Bornes horaires de la séance, telles que la capture les affiche. Elles ne servent
    #: pas à dater la course — c'est `date` qui le fait — mais à la situer dans la journée.
    start_time: time | None = None
    end_time: time | None = None
    #: Longueur d'un palier plein, en kilomètres : 1,0 pour « 1 Kilometer », 1,609 pour
    #: « 1 Mile ». Sans elle, un fichier converti depuis des miles perdrait ce qui permet
    #: de relire ses paliers.
    split_length_km: float | None = None


class RunSplitRow(CsvModel):
    """Un palier d'une course. `activity/run_splits.csv` (`ACT-19`).

    Le fichier existe pour une raison qui tient en une ligne de la capture : la neuvième.
    Huit paliers autour de cinq minutes, puis `00:44` — qui n'est pas un kilomètre mais le
    reliquat de distance. Apple lui affiche quand même une allure, par extrapolation.

    `partial` est donc la colonne qui porte tout le poids du fichier : sans elle, une
    moyenne, un écart ou une dérive comptent 44 secondes comme un kilomètre et se
    trompent de bout en bout. C'est aussi le seul champ qu'aucune capture n'affiche
    littéralement — il se déduit de la durée, côté serveur, jamais par le modèle.
    """

    #: Rattachement à `RunRow.run_id`, pas à sa position. Une course supprimée en amont
    #: décalerait tous les index et ferait migrer les paliers vers la course voisine.
    run_id: str
    #: Le numéro **lu sur la ligne**, jamais recompté : une capture peut être défilée et
    #: commencer au septième palier.
    index: int
    duration_s: float
    #: La longueur **réelle** du palier — 1,0 pour un plein, le reliquat pour un partiel.
    #: C'est elle et non `index` qui permet de sommer une distance sans mentir.
    distance_km: float
    #: Recopiée telle qu'affichée, y compris sur un partiel où elle est extrapolée. C'est
    #: `partial` qui dit comment la lire, pas son absence.
    pace_min_km: float | None = None
    cadence_spm: int | None = None
    avg_hr: int | None = None
    elevation_m: int | None = None
    partial: bool = False


class WorkoutRow(CsvModel):
    """Une séance. `activity/workouts.csv`.

    `id` est un identifiant **stable** et non la position dans le fichier : les exercices
    s'y rattachent (`ACT-03`), et une suppression de ligne décalerait tous les index.
    """

    date: date
    type: str
    duration_min: float
    calories: int | None = None
    #: Effort perçu 1–10 (`ACT-18`), transmis à l'IA comme signal de charge et de fatigue.
    rpe: int | None = None
    note: str | None = None
    source: str = "manual"
    id: str = ""


class ExerciseRow(CsvModel):
    """Un exercice du catalogue. `activity/exercises.csv`.

    Colonnes toutes optionnelles, comme pour tout fichier que l'utilisateur peut ouvrir
    dans un tableur : une cellule vide coûte sa ligne, jamais le fichier (`STO-04`).
    Le journal des performances, lui, reste strict — c'est une mesure.
    """

    id: str = ""
    name: str = ""
    muscle_group: str = ""
    #: Les autres façons d'écrire cet exercice, séparées par des points-virgules —
    #: `dev couché;développé couché barre`. C'est ce qui permet de reconnaître une note
    #: manuscrite au deuxième passage (`C07`).
    #:
    #: **Une colonne et non un fichier à part**, et la raison est une conséquence : retirer
    #: un exercice doit emporter ses alias. Un `exercise_aliases.csv` laisserait des
    #: orphelins, et un nom retiré du catalogue continuerait d'être reconnu à la saisie.
    #:
    #: Le point-virgule et non la virgule : c'est un CSV, et le lecteur de `csv` de la
    #: bibliothèque standard couperait la cellule au mauvais endroit sans se plaindre.
    aliases: str = ""


class ExerciseLogRow(CsvModel):
    """Une performance. `activity/exercise_log.csv`.

    `weight_kg = 0` signifie **poids du corps** (`ACT-07`) : c'est une valeur légitime,
    pas une absence de donnée.
    """

    workout_id: str
    date: date
    exercise_id: str
    exercise_name: str
    muscle_group: str
    weight_kg: float
    sets: int
    reps: int
    note: str | None = None


class CircuitRow(CsvModel):
    """Une séance **modèle**, ouverte dans Cadence Tabata. `activity/circuits.csv`.

    Elle n'a pas de date : ce n'est pas une mesure mais un patron, et il se rejoue. C'est
    toute la raison pour laquelle elle ne vit pas dans `workouts.csv` — voir `paths.py`.

    **Aucun lien vers `exercises.csv`** (**D2**). Les noms d'exercices d'un circuit sont
    ceux du catalogue de Cadence, en anglais, et servent à afficher une illustration ;
    ceux du catalogue de Metric sont en français et servent à suivre une charge. Les
    rapprocher demanderait une table de correspondance à tenir à jour, et la faute qu'elle
    ferait — « Push-Ups » qui donne l'illustration de *Pike Push-ups* — est silencieuse.
    """

    #: Identifiant **stable**, sur le modèle de `WorkoutRow.id` : les exercices s'y
    #: rattachent, et `id` — la position dans le fichier — se décale à la première
    #: suppression.
    id: str = ""
    name: str = ""
    #: Bornes de la spécification de Cadence : 1 à 99. Une valeur hors bornes n'est pas
    #: rejetée à la lecture, elle est ramenée par `circuit_link.normalise` au moment de
    #: fabriquer le lien — c'est ce que fait l'application cible.
    rounds: int = 1
    #: Repos **entre deux rounds**, en secondes. 0 à 900.
    round_rest_s: int = 0
    #: Jour de création, tel que le serveur le voit. Il sert à trier une liste, jamais à
    #: dater une mesure : un circuit ne s'est pas produit ce jour-là.
    created: CsvDate = None
    note: str = ""


class CircuitExerciseRow(CsvModel):
    """Un exercice d'un circuit. `activity/circuit_exercises.csv`.

    ## `reps` fait autorité, `duration_s` est subordonnée

    `reps = -1` veut dire « cet exercice est au temps », et c'est alors `duration_s` qui
    compte. Un fichier corrigé à la main peut porter `reps: 12` **et** `duration_s: 30` ;
    la règle dit alors douze répétitions. Sans elle écrite ici, le générateur de lien et
    l'estimateur de durée trancheraient différemment le jour où ça arrive.

    Pourquoi une sentinelle plutôt qu'une cellule vide : une cellule vide laisse deviner,
    `-1` **dit** quelque chose à qui ouvre le fichier. Et pourquoi elle ne va pas dans
    `exercise_log.csv` : `Reps` y est borné `ge=1`, et desserrer cette borne la desserrerait
    aussi pour la saisie manuelle, où `-1` deviendrait une faute de frappe acceptée dans le
    journal de charge (**D3**).
    """

    #: Rattachement à `CircuitRow.id`, jamais à sa position.
    circuit_id: str = ""
    #: L'ordre **lu**, jamais recompté : le fichier peut être trié dans un tableur.
    position: int = 0
    #: Texte libre. Un nom du catalogue de Cadence y affiche une illustration ; tout autre
    #: nom fonctionne, simplement sans image.
    name: str = ""
    #: L'un des neuf groupes de `MuscleGroup`, choisi à la création du circuit.
    #:
    #: **C'est cette colonne qui relie les deux mondes.** Sans elle, un tabata déclaré fait
    #: n'aurait aucun groupe à écrire dans `exercise_log.csv`, et tous les circuits
    #: finiraient dans « autre » — l'équilibre par groupe cesserait de vouloir dire quelque
    #: chose exactement là où le tabata compte, sur les abdos et les jambes.
    #:
    #: Vide sur une ligne écrite à la main ou avant ce lot : légitime (`STO-04`), et lue
    #: comme « autre » plutôt que de faire tomber le fichier.
    muscle_group: str = ""
    duration_s: int = 20
    reps: int = -1
    rest_s: int = 0


class CircuitLoadRow(CsvModel):
    """La charge d'un exercice de tabata. `activity/circuit_loads.csv` (**C1**).

    ## Trois états, et l'absence de ligne en est un

    | Ce qu'on voit | Ce que le fichier porte |
    |---|---|
    | Jamais renseigné | **aucune ligne** |
    | Poids du corps | `bodyweight` vrai, `weight_kg` vide |
    | Une charge | `weight_kg` renseigné, `bodyweight` faux |

    Une ligne n'existe donc qu'une fois quelque chose déclaré, et `weight_kg` vide **n'est
    pas zéro** : zéro serait une mesure — c'est d'ailleurs ce que zéro veut dire dans
    `exercise_log.csv`, où il signifie « poids du corps » (`ACT-07`) — alors que vide est
    une absence. L'écran affiche un tiret pour l'une et « poids du corps » pour l'autre,
    et il ne pourrait pas les distinguer si les deux s'écrivaient `0`.

    ## Pourquoi la clé est un nom et pas un rattachement

    La charge vaut pour l'exercice, pas pour le circuit qui l'emploie (**C1**). Le même
    Rowing apparaît dans trois séances ; le noter à 12 kg doit valoir pour les trois. Un
    rattachement à `circuit_exercises.csv` autoriserait 12 kg ici et 16 kg là, et aucune
    règle ne dirait alors laquelle la page doit montrer.

    Le rapprochement passe par `fold` (`app/core/text.py`), celui du reste du domaine.
    """

    #: Le nom **tel qu'il est écrit dans le circuit**, gardé pour l'affichage. C'est son
    #: repli qui sert de clé, jamais la casse ou les accents.
    name: str = ""
    #: Vide = jamais chiffré. Exclusif de `bodyweight` : le service efface l'un en posant
    #: l'autre, sans quoi une ligne pourrait dire « poids du corps à 12 kg ».
    weight_kg: float | None = None
    bodyweight: bool = False
    #: Le jour de la dernière décision, tel que le serveur le voit. Il ne date **aucune
    #: séance** : noter une charge n'est pas la soulever.
    updated: CsvDate = None


class CircuitLoadLogRow(CsvModel):
    """Un changement de charge. `activity/circuit_load_log.csv` (**C2**).

    Une ligne par changement **confirmé**, jamais une par appui sur `+` : le pas-à-pas
    ajuste une valeur locale, c'est l'enregistrement qui écrit. Sans cette règle, monter de
    10 à 16 kg laisserait six lignes ici et six points sur la courbe.

    **Le passage en poids du corps y entre aussi**, avec `bodyweight` vrai et `weight_kg`
    vide. C'est un vrai événement de la courbe — la charge s'arrête — et l'omettre ferait
    mentir le graphique par le silence.

    Ce fichier est le seul historique des charges de tabata. `exercise_log.csv` n'en porte
    aucun : déclarer un circuit fait y écrit toujours `weight_kg = 0` (**C4**), et la
    raison est écrite dans `docs/charges.md` §1 — un exercice au temps porte `reps = -1`,
    et le multiplier par une charge non nulle produirait un tonnage négatif.
    """

    name: str = ""
    date: date
    weight_kg: float | None = None
    bodyweight: bool = False


class CircuitSessionRow(CsvModel):
    """Un circuit **déclaré fait**. `activity/circuit_sessions.csv`.

    ## Le pendant mesuré de `CircuitRow`

    `circuits.csv` porte un patron qui se rejoue et n'a pas de date ; ce fichier porte ce
    qui a eu lieu, une fois, un jour donné. C'est exactement la raison qui séparait déjà
    les circuits des séances — voir `paths.py` — et elle vaut dans les deux sens : une
    session ne se rejoue pas, elle ne se corrige pas non plus par un changement de patron.

    ## Le nom est dupliqué, comme dans `exercise_log.csv`

    `circuit_id` dit d'où vient la séance, `name` dit ce qu'elle était. Supprimer un
    circuit doit laisser son historique **lisible** (`ACT-06`) : sans la duplication, une
    ligne deviendrait muette dès que son patron disparaît, dans l'application comme dans
    un tableur trois ans plus tard (`STO-02`).

    ## Ce que ce fichier ne porte pas

    **Aucune charge.** `circuit_loads.csv` reste la seule autorité sur ce qu'on charge
    (**C1**), et le tonnage reste hors du monde tabata (**C4**) : un exercice au temps
    porte `reps = -1`, et le multiplier par une charge produirait un tonnage négatif.
    """

    #: Identifiant **stable** de la séance, sur le modèle de `WorkoutRow.id` : les séries
    #: s'y rattachent, et `id` — la position dans le fichier — se décale à la première
    #: suppression.
    session_id: str = ""
    #: Le patron joué, quand il existe encore. Vide sur une ligne dont le circuit a été
    #: supprimé depuis, ce qui est légitime : c'est `name` qui garde le sens de la ligne.
    circuit_id: str = ""
    #: Le jour de la séance, **tel que le serveur le voit**. Une session est une mesure :
    #: contrairement à `CircuitRow.created`, cette date date bien quelque chose.
    date: date
    name: str = ""
    #: Le nombre de rounds joués, borné comme le fait Cadence. C'est aussi le nombre de
    #: séries de chaque exercice — voir `CircuitSessionSetRow.sets`.
    rounds: int = 1
    #: La durée **confirmée** à l'écran, jamais l'estimation (**D4**). Sur une séance en
    #: répétitions personne ne connaît la durée réelle, et l'écrire en silence mettrait une
    #: valeur inventée dans le volume hebdomadaire.
    duration_min: float
    #: Effort perçu 1–10 (`ACT-18`), comme sur une séance. Absent est une réponse.
    rpe: int | None = None
    #: La provenance, sur le modèle de `WorkoutRow.source`. `cadence` pour un circuit
    #: déclaré fait depuis l'application ; la colonne existe pour que `IMP-05` continue de
    #: vouloir dire quelque chose le jour où une session vient d'ailleurs.
    source: str = "cadence"


class CircuitSessionSetRow(CsvModel):
    """Les séries d'un exercice, dans une séance tabata. `activity/circuit_session_sets.csv`.

    **C'est ce fichier qui rend l'assiduité possible.** Elle compte des séries par groupe
    musculaire et par jour ; une liste de groupes sérialisée dans une cellule de
    `circuit_sessions.csv` perdrait ce compte, et cesserait d'être lisible dans un tableur
    (`STO-02`). Le partage est celui de `run_splits.csv` et d'`exercise_log.csv`, pour la
    même raison.

    `date` est **recopiée** depuis la session plutôt que jointe : c'est ce qui permet de
    compter une semaine de séries en lisant ce seul fichier, et de le relire dans un
    tableur sans avoir à ouvrir l'autre à côté.
    """

    #: Rattachement à `CircuitSessionRow.session_id`, jamais à sa position.
    session_id: str = ""
    date: date
    #: Le nom **tel qu'il était dans le circuit ce jour-là**, et son groupe : dupliqués
    #: pour la raison d'`exercise_log.csv` (`ACT-06`) — une ligne d'historique doit rester
    #: lisible quand son patron a disparu.
    exercise_name: str = ""
    #: L'un des neuf groupes de `MuscleGroup`. Vide ou inconnu se lit comme `autre`, jamais
    #: en faisant tomber le fichier — la règle de lecture est celle de `_group_of`.
    muscle_group: str = ""
    #: Le nombre de rounds de la séance : chaque round est bien une série de plus. Le même
    #: chiffre que `CircuitSessionRow.rounds`, recopié pour que la ligne se lise seule.
    sets: int
    #: Les répétitions, ou `-1` si l'exercice est au temps — la sentinelle de
    #: `CircuitExerciseRow`, avec la même règle : c'est `reps` qui dit la nature de la
    #: ligne. Aucune charge ne l'accompagne, donc aucun tonnage n'en sort (**C4**).
    reps: int = -1
