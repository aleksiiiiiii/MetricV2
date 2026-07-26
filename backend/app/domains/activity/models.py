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

from datetime import date
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
    note: str | None = None
    source: str = "manual"


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
    """Un exercice du catalogue. `activity/exercises.csv`."""

    id: str
    name: str
    muscle_group: str


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
