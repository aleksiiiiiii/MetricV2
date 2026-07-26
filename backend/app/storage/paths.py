"""Chemins du stockage.

Les noms de fichiers viennent de l'annexe CSV du backlog. Les centraliser ici évite
qu'un domaine invente `activity/run.csv` quand le reste du monde écrit
`activity/runs.csv`.
"""

from __future__ import annotations

from datetime import datetime

# ── Fichiers de données (annexe du backlog) ─────────
WEIGHT = "body/weight.csv"
MEASUREMENTS = "body/measurements.csv"

RUNS = "activity/runs.csv"
WORKOUTS = "activity/workouts.csv"
EXERCISES = "activity/exercises.csv"
EXERCISE_LOG = "activity/exercise_log.csv"

MEALS = "nutrition/meals.csv"
MEAL_FAVORITES = "nutrition/favorites.csv"
MEAL_PHOTOS = "nutrition/photos"

HYDRATION_LOG = "hydration/intake_log.csv"

SUPPLEMENT_SCHEDULE = "supplements/schedule.csv"
SUPPLEMENT_LOG = "supplements/intake_log.csv"

PLAN = "planning/plan.csv"
GOALS = "goals/goals.csv"
WEEKLY_INSIGHTS = "insights/weekly.csv"

# Décision **D2** : tout ce qui est réglage vit sous `settings/`, y compris le
# clé/valeur que l'annexe plaçait à la racine. Un fichier et un dossier homonymes au
# même niveau est légal mais piégeux.
SETTINGS = "settings/settings.csv"
HEATMAP_TRACKS = "settings/heatmap_tracks.csv"
HEATMAP_CADENCES = "settings/heatmap_cadences.csv"
HEATMAP_OFF_DAYS = "settings/heatmap_off_days.csv"

# Fichier de diagnostic écrit puis relu par `check_storage.py` (`STO-11`).
HEALTHCHECK = "_metric_healthcheck.csv"


def dated_directory(prefix: str, when: datetime) -> str:
    """Dossier `prefix/AAAA/MM/JJ` (`STO-07`, `NUT-02`).

    L'arborescence datée sert autant à la navigation hors de l'app qu'à éviter un
    dossier unique de plusieurs milliers de fichiers.
    """
    return f"{prefix.rstrip('/')}/{when:%Y/%m/%d}"


def dated_file(prefix: str, when: datetime, filename: str) -> str:
    """Chemin complet d'un fichier rangé par date."""
    return f"{dated_directory(prefix, when)}/{filename}"
