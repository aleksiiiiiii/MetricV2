"""Endpoints du domaine Activité (`ACT-01` → `ACT-18`).

Même garde qu'ailleurs : les lectures rendent un `token` par ligne, les écritures
destructrices l'exigent en `If-Match` (`STO-05`, voir `docs/patron-domaine.md`).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Header, Path, Query, status

from app.core.deps import StoreDep
from app.core.validation import today_local
from app.domains.activity.models import WORKOUT_TYPES, MuscleGroup
from app.domains.activity.schemas import (
    ActivityOverview,
    Exercise,
    ExerciseEntry,
    ExerciseEntryPayload,
    ExercisePayload,
    ExerciseProgress,
    Run,
    RunPayload,
    Workout,
    WorkoutPayload,
)
from app.domains.activity.service import ExerciseService, RunService, WorkoutService
from app.domains.activity.stats import ActivityStats
from app.storage.errors import StorageConflictError

router = APIRouter(prefix="/activity", tags=["activité"])

RowId = Annotated[int, Path(ge=0, description="Position de la ligne dans le fichier")]
IfMatch = Annotated[
    str | None, Header(alias="If-Match", description="Jeton de la ligne, tel que rendu")
]


def _token(value: str | None) -> str:
    if not value:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.", detail="en-tête If-Match absent"
        )
    return value.strip('"')


# ── Vue d'ensemble ────────────────────────────────────


@router.get("", response_model=ActivityOverview, summary="Semaine, volumes et historique")
async def overview(
    store: StoreDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
) -> ActivityOverview:
    """Totaux de la semaine, volume par jour, huit semaines, tonnage, groupes négligés
    et historique fusionné — en une requête."""
    return await ActivityStats(store).overview(today_local(), limit=limit)


@router.get("/progress", response_model=list[ExerciseProgress], summary="Progression des charges")
async def progress(store: StoreDep) -> list[ExerciseProgress]:
    return await ActivityStats(store).progress()


@router.get("/types", response_model=list[str], summary="Types de séance suggérés")
def workout_types() -> list[str]:
    """Suggestions et non contrainte : le champ reste libre (`ACT-03`)."""
    return list(WORKOUT_TYPES)


@router.get("/muscle-groups", response_model=list[str], summary="Groupes musculaires")
def muscle_groups() -> list[str]:
    """La taxonomie de saisie (`ACT-06`), pour que le client ne la duplique pas."""
    return [group.value for group in MuscleGroup]


# ── Courses ───────────────────────────────────────────


@router.post(
    "/runs",
    response_model=Run,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer une course",
)
async def create_run(payload: RunPayload, store: StoreDep) -> Run:
    return await RunService(store).create(payload)


@router.get("/runs/{row_id}", response_model=Run, summary="Détail d'une course")
async def read_run(row_id: RowId, store: StoreDep) -> Run:
    return await RunService(store).get(row_id)


@router.patch("/runs/{row_id}", response_model=Run, summary="Corriger une course")
async def update_run(
    row_id: RowId, payload: RunPayload, store: StoreDep, if_match: IfMatch = None
) -> Run:
    return await RunService(store).update(row_id, _token(if_match), payload)


@router.delete(
    "/runs/{row_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une course"
)
async def delete_run(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    await RunService(store).delete(row_id, _token(if_match))


# ── Séances ───────────────────────────────────────────


@router.post(
    "/workouts",
    response_model=Workout,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer une séance",
)
async def create_workout(payload: WorkoutPayload, store: StoreDep) -> Workout:
    return await WorkoutService(store).create(payload)


@router.get("/workouts/{row_id}", response_model=Workout, summary="Détail d'une séance")
async def read_workout(row_id: RowId, store: StoreDep) -> Workout:
    return await WorkoutService(store).get(row_id)


@router.patch("/workouts/{row_id}", response_model=Workout, summary="Corriger une séance")
async def update_workout(
    row_id: RowId, payload: WorkoutPayload, store: StoreDep, if_match: IfMatch = None
) -> Workout:
    return await WorkoutService(store).update(row_id, _token(if_match), payload)


@router.delete(
    "/workouts/{row_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une séance"
)
async def delete_workout(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    """Supprime la séance **et purge ses exercices** (`ACT-04`)."""
    await WorkoutService(store).delete(row_id, _token(if_match))


@router.post(
    "/workouts/{row_id}/duplicate",
    response_model=Workout,
    status_code=status.HTTP_201_CREATED,
    summary="Dupliquer une séance",
)
async def duplicate_workout(
    row_id: RowId,
    store: StoreDep,
    day: Annotated[date | None, Body(embed=True, alias="date")] = None,
) -> Workout:
    """Recrée une séance passée, exercices compris (`ACT-17`)."""
    return await WorkoutService(store).duplicate(row_id, day or today_local())


# ── Exercices ─────────────────────────────────────────


@router.get("/exercises", response_model=list[Exercise], summary="Catalogue d'exercices")
async def list_exercises(store: StoreDep) -> list[Exercise]:
    """Catalogue enrichi de la dernière performance de chaque exercice (`ACT-08`)."""
    return await ExerciseService(store).catalogue()


@router.post(
    "/exercises",
    response_model=Exercise,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un exercice",
)
async def create_exercise(payload: ExercisePayload, store: StoreDep) -> Exercise:
    return await ExerciseService(store).create(payload)


@router.delete(
    "/exercises/{row_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Retirer un exercice"
)
async def delete_exercise(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    """Retire du catalogue sans toucher au journal : l'historique survit (`ACT-06`)."""
    await ExerciseService(store).delete(row_id, _token(if_match))


# ── Journal d'exercices ───────────────────────────────


@router.post(
    "/workouts/{row_id}/exercises",
    response_model=ExerciseEntry,
    status_code=status.HTTP_201_CREATED,
    summary="Consigner une performance",
)
async def log_exercise(
    row_id: RowId, payload: ExerciseEntryPayload, store: StoreDep
) -> ExerciseEntry:
    workout = await WorkoutService(store).get(row_id)
    return await ExerciseService(store).log(workout.workout_id, workout.date, payload)


@router.patch(
    "/exercise-log/{row_id}", response_model=ExerciseEntry, summary="Corriger une performance"
)
async def update_exercise_entry(
    row_id: RowId, payload: ExerciseEntryPayload, store: StoreDep, if_match: IfMatch = None
) -> ExerciseEntry:
    return await ExerciseService(store).update_entry(row_id, _token(if_match), payload)


@router.delete(
    "/exercise-log/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une performance",
)
async def delete_exercise_entry(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    await ExerciseService(store).delete_entry(row_id, _token(if_match))
