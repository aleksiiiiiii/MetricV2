"""Agrégats du domaine Activité (`ACT-09` → `ACT-16`).

Toutes les fenêtres hebdomadaires sont des **semaines ISO** : lundi → dimanche. Le
backlog le dit deux fois (`ACT-11` « remise à zéro chaque lundi », `PLAN-01` « semaine
commençant le lundi ») et la spec d'assiduité en dépend (`HEAT-11`). Un seul endroit
calcule cette borne.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from app.core.parsing import estimate_one_rep_max, pace_min_per_km
from app.domains.activity.models import MuscleGroup
from app.domains.activity.schemas import (
    ActivityItem,
    ActivityOverview,
    DayVolume,
    ExerciseProgress,
    MuscleVolume,
    NeglectedGroup,
    WeekTotals,
    WeekVolume,
)
from app.domains.activity.service import ExerciseService, RunService, WorkoutService
from app.storage.files import FileStore

#: Profondeur de l'historique hebdomadaire (`ACT-12`).
WEEKS_BACK = 8


def week_start(day: date) -> date:
    """Lundi de la semaine ISO contenant `day`."""
    return day - timedelta(days=day.weekday())


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


class ActivityStats:
    """Lecture agrégée de l'activité."""

    def __init__(self, store: FileStore) -> None:
        self._runs = RunService(store)
        self._workouts = WorkoutService(store)
        self._exercises = ExerciseService(store)

    async def overview(self, today: date, *, limit: int = 30) -> ActivityOverview:
        runs = await self._runs.all()
        workouts = await self._workouts.all()
        entries = await self._exercises.log_entries()

        current = week_start(today)

        # Minutes par jour, toutes activités confondues.
        minutes: defaultdict[date, float] = defaultdict(float)
        sessions: defaultdict[date, int] = defaultdict(int)
        for run in runs:
            minutes[run.model.date] += run.model.duration_min
            sessions[run.model.date] += 1
        for workout in workouts:
            minutes[workout.model.date] += workout.model.duration_min
            sessions[workout.model.date] += 1

        return ActivityOverview(
            week=self._week_totals(runs, workouts, current),
            days=self._days(minutes, current),
            weeks=self._weeks(minutes, sessions, current),
            muscles=self._muscles(entries, current),
            neglected=self._neglected(entries, today),
            history=self._history(runs, workouts)[:limit],
            total=len(runs) + len(workouts),
        )

    # ── Semaine en cours (`ACT-10`, `ACT-11`) ─────────

    @staticmethod
    def _week_totals(runs: list, workouts: list, current: date) -> WeekTotals:  # type: ignore[type-arg]
        end = current + timedelta(days=7)
        week_runs = [row.model for row in runs if current <= row.model.date < end]
        week_workouts = [row.model for row in workouts if current <= row.model.date < end]

        distance = sum(run.distance_km for run in week_runs)
        running_minutes = sum(run.duration_min for run in week_runs)

        return WeekTotals(
            week_start=current,
            minutes=_round(
                sum(run.duration_min for run in week_runs)
                + sum(workout.duration_min for workout in week_workouts)
            )
            or 0,
            sessions=len(week_runs) + len(week_workouts),
            distance_km=_round(distance) or 0,
            # L'allure moyenne ne porte que sur la course : mélanger une heure de yoga
            # aux kilomètres n'aurait aucun sens.
            pace_min_km=_round(pace_min_per_km(distance, running_minutes), 3),
        )

    @staticmethod
    def _days(minutes: dict[date, float], current: date) -> list[DayVolume]:
        """Les sept jours de la semaine en cours, repos distingué (`ACT-10`)."""
        days: list[DayVolume] = []
        for offset in range(7):
            day = current + timedelta(days=offset)
            volume = minutes.get(day, 0.0)
            days.append(
                DayVolume(
                    date=day,
                    weekday=offset + 1,
                    minutes=_round(volume) or 0,
                    # Un jour de repos est un choix, pas un trou de données.
                    rest=volume == 0,
                )
            )
        return days

    @staticmethod
    def _weeks(
        minutes: dict[date, float], sessions: dict[date, int], current: date
    ) -> list[WeekVolume]:
        """Les huit dernières semaines, la plus ancienne en premier (`ACT-12`)."""
        weeks: list[WeekVolume] = []
        for offset in range(WEEKS_BACK - 1, -1, -1):
            start = current - timedelta(weeks=offset)
            end = start + timedelta(days=7)
            total = sum(value for day, value in minutes.items() if start <= day < end)
            count = sum(value for day, value in sessions.items() if start <= day < end)
            weeks.append(WeekVolume(week_start=start, minutes=_round(total) or 0, sessions=count))
        return weeks

    # ── Muscles (`ACT-14`, `ACT-16`) ──────────────────

    @staticmethod
    def _muscles(entries: list, current: date) -> list[MuscleVolume]:  # type: ignore[type-arg]
        """Tonnage de la semaine par groupe musculaire (`ACT-14`).

        Charge × séries × réps : c'est la charge réelle, là où les minutes ne
        distinguent pas trois séries de huit d'une heure de repos entre les séries.
        """
        end = current + timedelta(days=7)
        volume: defaultdict[str, float] = defaultdict(float)
        sets: defaultdict[str, int] = defaultdict(int)

        for row in entries:
            model = row.model
            if not current <= model.date < end:
                continue
            volume[model.muscle_group] += model.weight_kg * model.sets * model.reps
            sets[model.muscle_group] += model.sets

        return [
            MuscleVolume(muscle_group=group, volume_kg=_round(volume[group]) or 0, sets=sets[group])
            for group in (item.value for item in MuscleGroup)
            if volume[group] or sets[group]
        ]

    @staticmethod
    def _neglected(entries: list, today: date) -> list[NeglectedGroup]:  # type: ignore[type-arg]
        """Jours depuis la dernière sollicitation de chaque groupe (`ACT-16`).

        Un groupe jamais travaillé rend `None` et non un nombre géant : « jamais » et
        « il y a très longtemps » ne se traitent pas pareil, et une valeur inventée
        fausserait la génération IA de planning (`PLAN-03`).
        """
        last: dict[str, date] = {}
        for row in entries:
            model = row.model
            current = last.get(model.muscle_group)
            if current is None or model.date > current:
                last[model.muscle_group] = model.date

        neglected: list[NeglectedGroup] = []
        for group in (item.value for item in MuscleGroup):
            if group == MuscleGroup.AUTRE.value:
                continue  # « autre » n'est pas un groupe à solliciter
            seen = last.get(group)
            neglected.append(
                NeglectedGroup(
                    muscle_group=group,
                    days_since=(today - seen).days if seen else None,
                    last_date=seen,
                )
            )
        return sorted(
            neglected,
            # Jamais travaillé d'abord, puis du plus ancien au plus récent.
            key=lambda item: (item.days_since is not None, -(item.days_since or 0)),
        )

    # ── Historique fusionné (`ACT-13`) ────────────────

    @staticmethod
    def _history(runs: list, workouts: list) -> list[ActivityItem]:  # type: ignore[type-arg]
        items: list[ActivityItem] = []

        for row in runs:
            model = row.model
            items.append(
                ActivityItem(
                    kind="run",
                    id=row.index,
                    token=row.token,
                    date=model.date,
                    label="Course",
                    duration_min=model.duration_min,
                    distance_km=model.distance_km,
                    pace_min_km=_round(
                        model.pace_min_km or pace_min_per_km(model.distance_km, model.duration_min),
                        3,
                    ),
                    source=model.source,
                )
            )

        for row in workouts:
            model = row.model
            items.append(
                ActivityItem(
                    kind="workout",
                    id=row.index,
                    token=row.token,
                    date=model.date,
                    label=model.type,
                    duration_min=model.duration_min,
                    rpe=model.rpe,
                    source=model.source,
                )
            )

        return sorted(items, key=lambda item: (item.date, item.kind), reverse=True)

    # ── Progression par exercice (`ACT-09`, `ACT-15`) ──

    async def progress(self) -> list[ExerciseProgress]:
        """Progression et records, exercice par exercice, groupés par muscle."""
        entries = await self._exercises.log_entries()

        by_exercise: defaultdict[str, list] = defaultdict(list)  # type: ignore[type-arg]
        for row in entries:
            by_exercise[row.model.exercise_id].append(row)

        progress: list[ExerciseProgress] = []
        for exercise_id, rows in by_exercise.items():
            ordered = sorted(rows, key=lambda row: (row.model.date, row.index))

            # Une séance peut contenir plusieurs lignes du même exercice : la charge du
            # jour est la plus lourde, pas la dernière consignée.
            per_day: dict[date, float] = {}
            for row in ordered:
                day = row.model.date
                per_day[day] = max(per_day.get(day, 0.0), row.model.weight_kg)

            days = sorted(per_day)
            maxima = [per_day[day] for day in days]
            latest = ordered[-1].model

            best = max(row.model.weight_kg for row in ordered)
            best_1rm = max(
                (
                    value
                    for row in ordered
                    if (value := estimate_one_rep_max(row.model.weight_kg, row.model.reps))
                ),
                default=None,
            )

            progress.append(
                ExerciseProgress(
                    exercise_id=exercise_id,
                    name=latest.exercise_name,
                    muscle_group=latest.muscle_group,
                    last_weight_kg=maxima[-1] if maxima else None,
                    last_date=days[-1] if days else None,
                    delta_kg=_round(maxima[-1] - maxima[-2]) if len(maxima) >= 2 else None,
                    max_series=maxima,
                    dates=days,
                    best_weight_kg=best,
                    best_one_rep_max_kg=_round(best_1rm),
                )
            )

        return sorted(progress, key=lambda item: (item.muscle_group, item.name))
