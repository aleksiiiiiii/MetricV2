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

from app.storage.model import CsvModel


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
    #: à l'autre. Les actives restent hors de `runs.csv` tant qu'aucun écran ne les demande.
    total_calories: int | None = None
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
