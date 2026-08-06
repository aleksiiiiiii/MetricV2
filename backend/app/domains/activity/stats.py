"""Agrégats du domaine Activité (`ACT-09` → `ACT-16`).

Toutes les fenêtres hebdomadaires sont des **semaines ISO** : lundi → dimanche. Le
backlog le dit deux fois (`ACT-11` « remise à zéro chaque lundi », `PLAN-01` « semaine
commençant le lundi ») et la spec d'assiduité en dépend (`HEAT-11`). Un seul endroit
calcule cette borne.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from app.core.dates import week_start
from app.core.parsing import estimate_one_rep_max, pace_min_per_km
from app.domains.activity.models import MuscleGroup, RunRow, WorkoutRow
from app.domains.activity.schemas import (
    ActivityItem,
    ActivityOverview,
    DayVolume,
    ExerciseProgress,
    MuscleVolume,
    NeglectedGroup,
    TrainingSplit,
    TrainingTotals,
    WeekTotals,
    WeekVolume,
)
from app.domains.activity.service import ExerciseService, RunService, WorkoutService
from app.storage.csv_repo import Row
from app.storage.files import FileStore

#: Profondeur de l'historique hebdomadaire (`ACT-12`).
WEEKS_BACK = 8


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


class ActivityStats:
    """Lecture agrégée de l'activité."""

    def __init__(self, store: FileStore) -> None:
        self._runs = RunService(store)
        self._workouts = WorkoutService(store)
        self._exercises = ExerciseService(store)

    @staticmethod
    def _per_day(
        runs: list[Row[RunRow]], workouts: list[Row[WorkoutRow]]
    ) -> tuple[dict[date, float], dict[date, int]]:
        """Minutes et nombre de séances par jour, toutes activités confondues."""
        minutes: defaultdict[date, float] = defaultdict(float)
        sessions: defaultdict[date, int] = defaultdict(int)
        for run in runs:
            minutes[run.model.date] += run.model.duration_min
            sessions[run.model.date] += 1
        for workout in workouts:
            minutes[workout.model.date] += workout.model.duration_min
            sessions[workout.model.date] += 1
        return minutes, sessions

    async def overview(self, today: date, *, limit: int = 30) -> ActivityOverview:
        runs = await self._runs.all()
        workouts = await self._workouts.all()
        entries = await self._exercises.log_entries()

        current = week_start(today)
        minutes, sessions = self._per_day(runs, workouts)

        return ActivityOverview(
            week=self._week_totals(runs, workouts, current),
            days=self._days(minutes, current),
            weeks=self._weeks(minutes, sessions, current),
            muscles=self._muscles(entries, current),
            neglected=self._neglected(entries, today),
            history=self._history(runs, workouts)[:limit],
            total=len(runs) + len(workouts),
        )

    # ── Totaux d'entraînement (`AGG-02`) ──────────────

    async def training(self, today: date) -> TrainingTotals:
        """Totaux du tableau de bord : deux fichiers lus, rien de plus.

        Le journal des exercices n'est pas ouvert : `AGG-02` demande des séances et des
        minutes, pas du tonnage. Une lecture Nextcloud évitée par affichage d'accueil.
        """
        runs = await self._runs.all()
        workouts = await self._workouts.all()

        current = week_start(today)
        minutes, sessions = self._per_day(runs, workouts)

        return TrainingTotals(
            sessions_total=len(runs) + len(workouts),
            minutes_total=_round(sum(minutes.values())) or 0,
            week=self._week_totals(runs, workouts, current),
            weeks=self._weeks(minutes, sessions, current),
            split=self._split(runs, workouts),
        )

    @staticmethod
    def _split(runs: list[Row[RunRow]], workouts: list[Row[WorkoutRow]]) -> list[TrainingSplit]:
        """Répartition courses / musculation (`AGG-02`).

        Trois parts et non deux : le champ `type` d'une séance est libre (`ACT-03`), et
        ranger une heure de yoga sous « musculation » pour n'en afficher que deux serait
        un chiffre faux. Ce qui n'est ni course ni musculation est nommé pour ce qu'il
        est, et la part disparaît quand elle est vide.
        """

        def is_strength(row: Row[WorkoutRow]) -> bool:
            return row.model.type.strip().lower() == "musculation"

        strength = [row for row in workouts if is_strength(row)]
        other = [row for row in workouts if not is_strength(row)]

        total = len(runs) + len(workouts)
        parts = (
            ("run", "Course", runs),
            ("strength", "Musculation", strength),
            ("other", "Autre", other),
        )

        return [
            TrainingSplit(
                kind=kind,
                label=label,
                sessions=len(rows),
                minutes=_round(sum(row.model.duration_min for row in rows)) or 0,
                ratio=len(rows) / total if total else 0.0,
            )
            for kind, label, rows in parts
            if rows
        ]

    # ── Séries pour `AGG-04` ──────────────────────────

    async def weekly_minutes(self) -> list[tuple[date, float]]:
        """Minutes d'activité par semaine ISO, datées au lundi."""
        minutes, _ = self._per_day(await self._runs.all(), await self._workouts.all())
        return self._by_week(minutes)

    async def weekly_sessions(self) -> list[tuple[date, float]]:
        """Nombre de séances par semaine ISO, datées au lundi.

        Toutes catégories confondues, comme `AGG-02` compte les totaux : une sortie de
        course et une heure de muscu sont deux séances. Sert la métrique `weekly_sessions`
        du registre, donc aussi bien les séries génériques (`AGG-04`) qu'un objectif de
        régularité (`GOAL-04`).
        """
        _, sessions = self._per_day(await self._runs.all(), await self._workouts.all())
        return self._by_week({day: float(count) for day, count in sessions.items()})

    async def weekly_distance(self) -> list[tuple[date, float]]:
        """Kilomètres courus par semaine ISO.

        La course seule : additionner les kilomètres d'une séance de musculation n'aurait
        pas de sens, et c'est déjà la raison pour laquelle `_week_totals` calcule l'allure
        moyenne sur les courses uniquement.
        """
        per_day: defaultdict[date, float] = defaultdict(float)
        for row in await self._runs.all():
            per_day[row.model.date] += row.model.distance_km
        return self._by_week(per_day)

    async def weekly_volume(self) -> list[tuple[date, float]]:
        """Tonnage par semaine ISO : charge × séries × réps (`ACT-14`)."""
        entries = await self._exercises.log_entries()
        per_day: defaultdict[date, float] = defaultdict(float)
        for row in entries:
            model = row.model
            per_day[model.date] += model.weight_kg * model.sets * model.reps
        return self._by_week(per_day)

    async def exercise_load(self, exercise_id: str) -> list[tuple[date, float]]:
        """Charge maximale par jour pour un exercice (`ACT-09`).

        Une séance peut contenir plusieurs lignes du même exercice : la charge du jour
        est la plus lourde, pas la dernière consignée.
        """
        entries = await self._exercises.log_entries()
        per_day: dict[date, float] = {}
        for row in entries:
            model = row.model
            if model.exercise_id != exercise_id:
                continue
            per_day[model.date] = max(per_day.get(model.date, 0.0), model.weight_kg)
        return sorted(per_day.items())

    @staticmethod
    def _by_week(per_day: dict[date, float]) -> list[tuple[date, float]]:
        per_week: defaultdict[date, float] = defaultdict(float)
        for day, value in per_day.items():
            per_week[week_start(day)] += value
        return sorted((day, _round(value) or 0) for day, value in per_week.items())

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
