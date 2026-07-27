"""Endpoints de l'hydratation (`HYD-01` → `HYD-05`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, status

from app.core.dates import today_local
from app.core.deps import StoreDep
from app.domains.hydration.schemas import HydrationView, Intake, IntakePayload
from app.domains.hydration.service import HISTORY_DAYS, HydrationService
from app.storage.errors import StorageConflictError

router = APIRouter(prefix="/hydration", tags=["hydratation"])

RowId = Annotated[int, Path(ge=0)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]


@router.get("", response_model=HydrationView, summary="Total du jour, série et moyennes")
async def read(
    store: StoreDep,
    days: Annotated[int, Query(ge=1, le=400)] = HISTORY_DAYS,
) -> HydrationView:
    return await HydrationService(store).view(today_local(), days=days)


@router.post(
    "",
    response_model=Intake,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer une prise",
)
async def create(payload: IntakePayload, store: StoreDep) -> Intake:
    return await HydrationService(store).create(payload)


@router.delete("/{row_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une prise")
async def delete(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    """Rattraper une erreur de saisie (`HYD-04`)."""
    if not if_match:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.", detail="en-tête If-Match absent"
        )
    await HydrationService(store).delete(row_id, if_match.strip('"'))
