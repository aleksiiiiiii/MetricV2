"""Écriture et lecture du domaine Activité (`ACT-01` → `ACT-09`, `ACT-17`).

Les agrégats hebdomadaires et les progressions vivent dans `stats.py` : ce module ne
s'occupe que du cycle de vie des lignes.
"""

from __future__ import annotations

import secrets
from datetime import date

from app.core.parsing import estimate_one_rep_max, pace_min_per_km
from app.domains.activity.models import ExerciseLogRow, ExerciseRow, RunRow, WorkoutRow
from app.domains.activity.schemas import (
    Exercise,
    ExerciseEntry,
    ExerciseEntryPayload,
    ExercisePayload,
    Run,
    RunPayload,
    Workout,
    WorkoutPayload,
)
from app.storage.csv_repo import CsvRepository, Row
from app.storage.errors import StorageConflictError, StorageNotFoundError
from app.storage.files import FileStore
from app.storage.paths import EXERCISE_LOG, EXERCISES, RUNS, WORKOUTS

#: Longueur des identifiants stables. Assez court pour rester lisible dans un tableur,
#: assez long pour qu'une collision soit hors de portée à l'échelle d'une vie de relevés.
ID_BYTES = 6


def new_id() -> str:
    return secrets.token_hex(ID_BYTES)


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


# ── Courses ───────────────────────────────────────────


class RunService:
    """Courses : saisie, allure dérivée, correction (`ACT-01`, `ACT-02`, `ACT-05`)."""

    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[RunRow] = CsvRepository(store, RUNS, RunRow)

    @staticmethod
    def to_schema(row: Row[RunRow]) -> Run:
        model = row.model
        pace = model.pace_min_km or pace_min_per_km(model.distance_km, model.duration_min)
        return Run(
            id=row.index,
            token=row.token,
            date=model.date,
            distance_km=model.distance_km,
            duration_min=model.duration_min,
            pace_min_km=_round(pace, 3),
            speed_kmh=_round(60 / pace, 2) if pace else None,
            avg_hr=model.avg_hr,
            elevation_m=model.elevation_m,
            note=model.note,
            source=model.source,
        )

    @staticmethod
    def _to_row(payload: RunPayload, source: str = "manual") -> RunRow:
        return RunRow(
            date=payload.date,
            distance_km=payload.distance_km,
            duration_min=payload.duration_min,
            # L'allure est stockée avec la course : recalculable, mais la conserver rend
            # le fichier lisible sans outil (`ACT-02`, `STO-02`).
            pace_min_km=_round(pace_min_per_km(payload.distance_km, payload.duration_min), 3),
            avg_hr=payload.avg_hr,
            elevation_m=payload.elevation_m,
            note=payload.note,
            source=source,
        )

    async def all(self) -> list[Row[RunRow]]:
        return await self._repo.read_all()

    async def get(self, index: int) -> Run:
        rows = await self._repo.read_all()
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Cette course n'existe pas.")
        return self.to_schema(rows[index])

    async def create(self, payload: RunPayload, *, source: str = "manual") -> Run:
        """Enregistre une course. `source` reste `manual` sauf import (`IMP-05`)."""
        return self.to_schema(await self._repo.append(self._to_row(payload, source)))

    async def update(self, index: int, token: str, payload: RunPayload) -> Run:
        rows = await self._repo.read_all(fresh=True)
        source = rows[index].model.source if 0 <= index < len(rows) else "manual"
        row = await self._repo.replace_by_token(index, token, self._to_row(payload, source))
        return self.to_schema(row)

    async def delete(self, index: int, token: str) -> None:
        await self._repo.delete_by_token(index, token)


# ── Exercices ─────────────────────────────────────────


class ExerciseService:
    """Catalogue d'exercices et journal des performances (`ACT-06` → `ACT-09`)."""

    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[ExerciseRow] = CsvRepository(store, EXERCISES, ExerciseRow)
        self._log: CsvRepository[ExerciseLogRow] = CsvRepository(
            store, EXERCISE_LOG, ExerciseLogRow
        )

    @staticmethod
    def entry_to_schema(row: Row[ExerciseLogRow]) -> ExerciseEntry:
        model = row.model
        return ExerciseEntry(
            id=row.index,
            token=row.token,
            workout_id=model.workout_id,
            date=model.date,
            exercise_id=model.exercise_id,
            exercise_name=model.exercise_name,
            muscle_group=model.muscle_group,
            weight_kg=model.weight_kg,
            sets=model.sets,
            reps=model.reps,
            note=model.note,
            volume_kg=_round(model.weight_kg * model.sets * model.reps) or 0,
            one_rep_max_kg=_round(estimate_one_rep_max(model.weight_kg, model.reps)),
        )

    async def catalogue(self) -> list[Exercise]:
        """Catalogue enrichi du rappel de dernière performance (`ACT-08`)."""
        rows = await self._repo.read_all()
        entries = await self._log.read_all()

        latest: dict[str, ExerciseLogRow] = {}
        for entry in sorted(entries, key=lambda item: (item.model.date, item.index)):
            latest[entry.model.exercise_id] = entry.model

        catalogue: list[Exercise] = []
        for row in rows:
            if not row.model.id:
                continue  # ligne sans identifiant : le journal ne peut pas s'y rattacher
            last = latest.get(row.model.id)
            catalogue.append(
                Exercise(
                    id=row.index,
                    token=row.token,
                    exercise_id=row.model.id,
                    name=row.model.name,
                    muscle_group=row.model.muscle_group,
                    last_weight_kg=last.weight_kg if last else None,
                    last_reps=last.reps if last else None,
                    last_sets=last.sets if last else None,
                    last_date=last.date if last else None,
                )
            )
        return catalogue

    async def create(self, payload: ExercisePayload) -> Exercise:
        row = await self._repo.append(
            ExerciseRow(id=new_id(), name=payload.name, muscle_group=payload.muscle_group)
        )
        return Exercise(
            id=row.index,
            token=row.token,
            exercise_id=row.model.id,
            name=row.model.name,
            muscle_group=row.model.muscle_group,
        )

    async def delete(self, index: int, token: str) -> None:
        """Retire un exercice du catalogue.

        Le journal n'est **pas** touché : `ACT-06` exige que l'historique survive. C'est
        précisément pourquoi `exercise_log.csv` duplique le nom et le groupe musculaire —
        les lignes passées restent lisibles sans le catalogue.
        """
        await self._repo.delete_by_token(index, token)

    async def resolve(self, exercise_id: str) -> ExerciseRow:
        rows = await self._repo.read_all()
        for row in rows:
            if row.model.id == exercise_id:
                return row.model
        raise StorageNotFoundError("Cet exercice n'est pas au catalogue.")

    async def log_entries(self) -> list[Row[ExerciseLogRow]]:
        return await self._log.read_all()

    async def log(self, workout_id: str, day: date, payload: ExerciseEntryPayload) -> ExerciseEntry:
        exercise = await self.resolve(payload.exercise_id)
        row = await self._log.append(
            ExerciseLogRow(
                workout_id=workout_id,
                date=day,
                exercise_id=exercise.id,
                # Dupliqués volontairement : le fichier doit rester compréhensible seul.
                exercise_name=exercise.name,
                muscle_group=exercise.muscle_group,
                weight_kg=payload.weight_kg,
                sets=payload.sets,
                reps=payload.reps,
                note=payload.note,
            )
        )
        return self.entry_to_schema(row)

    async def update_entry(
        self, index: int, token: str, payload: ExerciseEntryPayload
    ) -> ExerciseEntry:
        rows = await self._log.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageConflictError(detail=f"ligne {index} absente du journal")

        existing = rows[index].model
        exercise = await self.resolve(payload.exercise_id)
        row = await self._log.replace_by_token(
            index,
            token,
            ExerciseLogRow(
                workout_id=existing.workout_id,
                date=existing.date,
                exercise_id=exercise.id,
                exercise_name=exercise.name,
                muscle_group=exercise.muscle_group,
                weight_kg=payload.weight_kg,
                sets=payload.sets,
                reps=payload.reps,
                note=payload.note,
            ),
        )
        return self.entry_to_schema(row)

    async def delete_entry(self, index: int, token: str) -> None:
        await self._log.delete_by_token(index, token)

    async def purge_workout(self, workout_id: str) -> int:
        """Supprime les performances rattachées à une séance (`ACT-04`)."""
        return await self._log.remove_where(lambda row: row.workout_id == workout_id)


# ── Séances ───────────────────────────────────────────


class WorkoutService:
    """Séances : saisie, exercices rattachés, duplication (`ACT-03`, `ACT-04`, `ACT-17`)."""

    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[WorkoutRow] = CsvRepository(store, WORKOUTS, WorkoutRow)
        self._exercises = ExerciseService(store)

    async def all(self) -> list[Row[WorkoutRow]]:
        return await self._repo.read_all()

    def _to_schema(self, row: Row[WorkoutRow], entries: list[ExerciseEntry]) -> Workout:
        model = row.model
        return Workout(
            id=row.index,
            token=row.token,
            workout_id=model.id,
            date=model.date,
            type=model.type,
            duration_min=model.duration_min,
            calories=model.calories,
            rpe=model.rpe,
            note=model.note,
            source=model.source,
            exercises=entries,
            volume_kg=_round(sum(entry.volume_kg for entry in entries)) or 0,
        )

    async def get(self, index: int) -> Workout:
        rows = await self._repo.read_all()
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Cette séance n'existe pas.")

        row = rows[index]
        entries = [
            self._exercises.entry_to_schema(entry)
            for entry in await self._exercises.log_entries()
            if entry.model.workout_id == row.model.id
        ]
        return self._to_schema(row, entries)

    async def create(self, payload: WorkoutPayload, *, source: str = "manual") -> Workout:
        """Enregistre une séance. `source` reste `manual` sauf import (`IMP-05`)."""
        row = await self._repo.append(
            WorkoutRow(
                date=payload.date,
                type=payload.type,
                duration_min=payload.duration_min,
                calories=payload.calories,
                rpe=payload.rpe,
                note=payload.note,
                source=source,
                id=new_id(),
            )
        )
        return self._to_schema(row, [])

    async def update(self, index: int, token: str, payload: WorkoutPayload) -> Workout:
        rows = await self._repo.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageConflictError(detail=f"séance {index} absente")

        existing = rows[index].model
        row = await self._repo.replace_by_token(
            index,
            token,
            WorkoutRow(
                date=payload.date,
                type=payload.type,
                duration_min=payload.duration_min,
                calories=payload.calories,
                rpe=payload.rpe,
                note=payload.note,
                # Identifiant et source survivent à une correction : les exercices y sont
                # rattachés, et l'origine de la donnée ne change pas (`IMP-05`).
                source=existing.source,
                id=existing.id,
            ),
        )
        entries = [
            self._exercises.entry_to_schema(entry)
            for entry in await self._exercises.log_entries()
            if entry.model.workout_id == existing.id
        ]
        return self._to_schema(row, entries)

    async def delete(self, index: int, token: str) -> None:
        """Supprime une séance **et purge ses exercices** (`ACT-04`).

        L'ordre compte : la séance part en premier, sous garde. Purger d'abord laisserait
        des exercices orphelins si la garde refusait la suppression.
        """
        rows = await self._repo.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageConflictError(detail=f"séance {index} absente")
        workout_id = rows[index].model.id

        await self._repo.delete_by_token(index, token)
        await self._exercises.purge_workout(workout_id)

    async def duplicate(self, index: int, day: date) -> Workout:
        """Recrée une séance passée, exercices compris (`ACT-17`).

        Saisir une répétition de routine devient une action au lieu d'une dizaine.
        """
        source = await self.get(index)

        created = await self.create(
            WorkoutPayload(
                date=day,
                type=source.type,
                duration_min=source.duration_min,
                calories=source.calories,
                rpe=None,  # l'effort perçu appartient à la séance vécue, pas au modèle
                note=source.note,
            )
        )

        entries: list[ExerciseEntry] = []
        for entry in source.exercises:
            entries.append(
                await self._exercises.log(
                    created.workout_id,
                    day,
                    ExerciseEntryPayload(
                        exercise_id=entry.exercise_id,
                        weight_kg=entry.weight_kg,
                        sets=entry.sets,
                        reps=entry.reps,
                    ),
                )
            )

        created.exercises = entries
        created.volume_kg = _round(sum(entry.volume_kg for entry in entries)) or 0
        return created
