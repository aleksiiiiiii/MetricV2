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

#: Les paliers d'une course — un kilomètre par ligne (`ACT-19`).
#:
#: Un fichier à part et non des colonnes de `runs.csv` : le nombre de paliers varie d'une
#: course à l'autre, et l'aplatir en colonnes donnerait un en-tête qui s'allonge à chaque
#: sortie plus longue que la précédente. C'est le même partage que `workouts.csv` et
#: `exercise_log.csv`, pour la même raison.
RUN_SPLITS = "activity/run_splits.csv"

WORKOUTS = "activity/workouts.csv"
EXERCISES = "activity/exercises.csv"
EXERCISE_LOG = "activity/exercise_log.csv"

#: Les séances **modèles** ouvertes dans Cadence Tabata (**D2**), et leurs exercices.
#:
#: `circuits` et non `workouts` : `workouts.csv` décrit ce qui **a eu lieu** — il porte une
#: date, une durée réelle, un RPE. Un circuit n'a pas de date, il se rejoue. Les mettre
#: dans le même fichier ferait porter à `date` un sens différent selon la ligne, ce qui est
#: la façon la plus sûre de casser un CSV qu'on rouvre dans un tableur trois ans plus tard.
#:
#: Deux fichiers plutôt qu'une liste sérialisée dans une cellule, comme `run_splits.csv` et
#: `exercise_log.csv` : c'est la seule forme qui reste lisible dans un tableur (`STO-02`).
CIRCUITS = "activity/circuits.csv"
CIRCUIT_EXERCISES = "activity/circuit_exercises.csv"

MEALS = "nutrition/meals.csv"
MEAL_FAVORITES = "nutrition/favorites.csv"
MEAL_PHOTOS = "nutrition/photos"

HYDRATION_LOG = "hydration/intake_log.csv"

SUPPLEMENT_SCHEDULE = "supplements/schedule.csv"
SUPPLEMENT_LOG = "supplements/intake_log.csv"

PLAN = "planning/plan.csv"
GOALS = "goals/goals.csv"
WEEKLY_INSIGHTS = "insights/weekly.csv"
MEMORY = "insights/memory.csv"

#: La lecture du jour, une ligne par journée (`brief/`).
#:
#: Rangé avec les bilans et le carnet plutôt qu'avec les fils de discussion, parce que
#: c'est ce qu'il est : une lecture datée des chiffres, du même genre que le bilan
#: hebdomadaire. Le fil qu'il sème n'est qu'une conséquence, et il vit dans son fichier.
BRIEF = "insights/brief.csv"

# Notifications push (`NOT-01`, `NOT-02`).
#
# `sent.csv` est la **mémoire de l'ordonnanceur**, et c'est un fichier plutôt qu'une
# variable pour une raison précise : un redémarrage ne doit pas renvoyer ce qui a déjà été
# envoyé. Il se lit aussi très bien dans un tableur — « quand ai-je été rappelé, et de
# quoi » est une question qu'on se pose le jour où un rappel arrive au mauvais moment.
PUSH_SUBSCRIPTIONS = "notifications/subscriptions.csv"
NOTIFICATIONS_SENT = "notifications/sent.csv"

# Les fils de discussion de l'assistant.
#
# Le serveur ne stockait rien : l'écran rendait l'historique à chaque question et le
# perdait au rechargement. C'était documenté comme voulu, avec trois bénéfices — et deux
# d'entre eux se retrouvent autrement dès lors qu'un fil a une identité. Le troisième,
# « aucun fichier ne grossit sans fin », est le prix assumé de pouvoir revenir sur une
# discussion d'il y a trois mois.
#
# Deux fichiers plutôt qu'un par fil : le dépôt CSV est fait pour ça, et un dossier de
# plusieurs centaines de fichiers minuscules se navigue mal hors de l'application — ce
# qui est le critère du projet depuis `STO-07`.
THREADS = "assistant/threads.csv"
MESSAGES = "assistant/messages.csv"

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
