"""Formes échangées avec le client pour le domaine Activité.

Les durées et distances entrent en **texte** : `44:12`, `8,40`, `1h30`. La normalisation
se fait ici, à la frontière, pour que le domaine ne voie jamais que des minutes décimales
(`ACT-01`).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.core.parsing import ParseError, parse_decimal, parse_distance_km, parse_duration_minutes
from app.core.validation import (
    Calories,
    DistanceKm,
    DurationMin,
    ElevationM,
    HeartRate,
    Label,
    LoadKg,
    Note,
    PastDate,
    Reps,
    Rpe,
    Sets,
)

# ── Saisies souples ───────────────────────────────────


def _duration(value: str | float) -> float:
    try:
        return parse_duration_minutes(value)
    except ParseError as exc:
        raise ValueError(str(exc)) from exc


def _distance(value: str | float) -> float:
    try:
        return parse_distance_km(value)
    except ParseError as exc:
        raise ValueError(str(exc)) from exc


# ── Courses ───────────────────────────────────────────


class RunPayload(BaseModel):
    """Saisie d'une course (`ACT-01`)."""

    date: PastDate
    #: Accepte `8,40`, `8.4`, `5mi`.
    distance_km: DistanceKm
    #: Accepte `44:12`, `1:18:44`, `44`, `1h30`.
    duration_min: DurationMin
    avg_hr: HeartRate | None = None
    elevation_m: ElevationM | None = None
    note: Note | None = None

    @field_validator("distance_km", mode="before")
    @classmethod
    def read_distance(cls, value: object) -> object:
        return _distance(value) if isinstance(value, str) else value

    @field_validator("duration_min", mode="before")
    @classmethod
    def read_duration(cls, value: object) -> object:
        return _duration(value) if isinstance(value, str) else value

    @field_validator("avg_hr", "elevation_m", mode="before")
    @classmethod
    def read_optional_number(cls, value: object) -> object:
        if isinstance(value, str):
            return None if not value.strip() else round(parse_decimal(value))
        return value


class Run(BaseModel):
    """Course rendue au client, allure comprise (`ACT-05`)."""

    id: int
    token: str
    date: date
    distance_km: float
    duration_min: float
    pace_min_km: float | None = None
    #: Vitesse moyenne en km/h — l'autre lecture de la même mesure.
    speed_kmh: float | None = None
    avg_hr: int | None = None
    elevation_m: int | None = None
    note: str | None = None
    source: str


# ── Séances ───────────────────────────────────────────


class WorkoutPayload(BaseModel):
    """Saisie d'une séance (`ACT-03`, `ACT-18`)."""

    date: PastDate
    type: Label
    duration_min: DurationMin
    calories: Calories | None = None
    rpe: Rpe | None = None
    note: Note | None = None

    @field_validator("duration_min", mode="before")
    @classmethod
    def read_duration(cls, value: object) -> object:
        return _duration(value) if isinstance(value, str) else value

    @field_validator("calories", "rpe", mode="before")
    @classmethod
    def read_optional_number(cls, value: object) -> object:
        if isinstance(value, str):
            return None if not value.strip() else round(parse_decimal(value))
        return value


class ExerciseEntryPayload(BaseModel):
    """Une performance à consigner (`ACT-07`)."""

    exercise_id: str = Field(min_length=1, max_length=40)
    #: `0` = poids du corps, valeur légitime et non une absence.
    weight_kg: LoadKg = 0
    sets: Sets = 1
    reps: Reps = 1
    note: Note | None = None

    @field_validator("weight_kg", mode="before")
    @classmethod
    def read_load(cls, value: object) -> object:
        return parse_decimal(value) if isinstance(value, str) and value.strip() else value


class ExerciseEntry(BaseModel):
    id: int
    token: str
    workout_id: str
    date: date
    exercise_id: str
    exercise_name: str
    muscle_group: str
    weight_kg: float
    sets: int
    reps: int
    note: str | None = None
    #: Charge × séries × réps (`ACT-14`).
    volume_kg: float
    #: 1RM estimé par Epley (`ACT-15`). `None` au poids du corps.
    one_rep_max_kg: float | None = None


class Workout(BaseModel):
    """Séance rendue au client, avec ses exercices."""

    id: int
    token: str
    workout_id: str
    date: date
    type: str
    duration_min: float
    calories: int | None = None
    rpe: int | None = None
    note: str | None = None
    source: str
    exercises: list[ExerciseEntry] = Field(default_factory=list)
    #: Tonnage total de la séance.
    volume_kg: float = 0


# ── Catalogue d'exercices (`ACT-06`) ──────────────────


class ExercisePayload(BaseModel):
    name: Label
    muscle_group: str

    @field_validator("muscle_group")
    @classmethod
    def known_group(cls, value: str) -> str:
        from app.domains.activity.models import MuscleGroup

        if value not in {group.value for group in MuscleGroup}:
            raise ValueError(f"groupe musculaire inconnu : {value}")
        return value


class Exercise(BaseModel):
    id: int
    token: str
    exercise_id: str
    name: str
    muscle_group: str
    #: Dernière performance, pour choisir sa charge sans consulter l'historique (`ACT-08`).
    last_weight_kg: float | None = None
    last_reps: int | None = None
    last_sets: int | None = None
    last_date: date | None = None


# ── Historique et agrégats ────────────────────────────


class ActivityItem(BaseModel):
    """Ligne de l'historique fusionné courses + séances (`ACT-13`)."""

    kind: str = Field(description="« run » ou « workout »")
    id: int
    token: str
    date: date
    label: str
    duration_min: float
    distance_km: float | None = None
    pace_min_km: float | None = None
    rpe: int | None = None
    source: str


class DayVolume(BaseModel):
    """Un jour de la semaine (`ACT-10`)."""

    date: date
    weekday: int = Field(description="1 = lundi, 7 = dimanche")
    minutes: float
    #: Distingué d'un jour à zéro minute : un jour de repos est un choix, pas un trou.
    rest: bool


class WeekTotals(BaseModel):
    """Totaux de la semaine en cours (`ACT-11`), remis à zéro le lundi."""

    week_start: date
    minutes: float
    sessions: int
    distance_km: float
    pace_min_km: float | None = None


class WeekVolume(BaseModel):
    """Une des huit dernières semaines (`ACT-12`)."""

    week_start: date
    minutes: float
    sessions: int


class TrainingSplit(BaseModel):
    """Une part de la répartition courses / musculation (`AGG-02`)."""

    kind: str = Field(description="« run », « strength » ou « other »")
    label: str
    sessions: int
    minutes: float
    #: Part des séances, entre 0 et 1.
    ratio: float = Field(ge=0, le=1)


class TrainingTotals(BaseModel):
    """Totaux d'entraînement du tableau de bord (`AGG-02`).

    Vit dans le domaine Activité et non dans les agrégats : c'est de l'arithmétique
    d'activité, et la semaine en cours comme les huit dernières y sont déjà calculées
    (`ACT-11`, `ACT-12`). Les agrégats assemblent, ils ne recalculent pas.
    """

    sessions_total: int
    minutes_total: float
    week: WeekTotals
    #: Les huit dernières semaines, la plus ancienne en premier.
    weeks: list[WeekVolume]
    split: list[TrainingSplit]


class MuscleVolume(BaseModel):
    """Tonnage par groupe musculaire (`ACT-14`)."""

    muscle_group: str
    volume_kg: float
    sets: int


class NeglectedGroup(BaseModel):
    """Jours depuis la dernière sollicitation (`ACT-16`)."""

    muscle_group: str
    days_since: int | None = None
    last_date: date | None = None


class ExerciseProgress(BaseModel):
    """Progression d'un exercice (`ACT-09`, `ACT-15`)."""

    exercise_id: str
    name: str
    muscle_group: str
    last_weight_kg: float | None = None
    last_date: date | None = None
    #: Écart de charge avec la fois précédente.
    delta_kg: float | None = None
    #: Série de la charge maximale par séance.
    max_series: list[float] = Field(default_factory=list)
    dates: list[date] = Field(default_factory=list)
    best_weight_kg: float | None = None
    best_one_rep_max_kg: float | None = None


class ActivityOverview(BaseModel):
    """Tout ce qu'affiche l'écran Activité, en une requête."""

    week: WeekTotals
    days: list[DayVolume]
    weeks: list[WeekVolume]
    muscles: list[MuscleVolume]
    neglected: list[NeglectedGroup]
    history: list[ActivityItem]
    total: int
