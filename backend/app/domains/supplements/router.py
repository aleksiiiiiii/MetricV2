"""Endpoints des suppléments (`SUP-01` → `SUP-06`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, status

from app.core.dates import today_local
from app.core.deps import StoreDep
from app.domains.supplements.models import UNITS
from app.domains.supplements.schemas import (
    ChecklistView,
    IntakePayload,
    Supplement,
    SupplementPayload,
)
from app.domains.supplements.service import SupplementService
from app.storage.errors import StorageConflictError

router = APIRouter(prefix="/supplements", tags=["suppléments"])

RowId = Annotated[int, Path(ge=0)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]


def _token(value: str | None) -> str:
    if not value:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.", detail="en-tête If-Match absent"
        )
    return value.strip('"')


@router.get("/today", response_model=ChecklistView, summary="Checklist du jour")
async def checklist(store: StoreDep) -> ChecklistView:
    """État vierge chaque jour : rien n'est mémorisé, tout est déduit du journal."""
    return await SupplementService(store).checklist(today_local())


@router.post("/today", response_model=ChecklistView, summary="Cocher une prise")
async def take(payload: IntakePayload, store: StoreDep) -> ChecklistView:
    """Écrit une prise horodatée et rend la checklist à jour.

    Rendre l'état complet plutôt que la seule ligne écrite évite au client un second
    aller-retour pour rafraîchir le ratio et la série.
    """
    return await SupplementService(store).take(payload.schedule_id)


@router.delete("/today/{schedule_id}", response_model=ChecklistView, summary="Décocher")
async def untake(schedule_id: str, store: StoreDep) -> ChecklistView:
    """Supprime la prise du jour correspondante (`SUP-05`)."""
    return await SupplementService(store).untake(schedule_id)


@router.get("/schedule", response_model=list[Supplement], summary="Planning")
async def schedule(
    store: StoreDep, active_only: Annotated[bool, Query()] = False
) -> list[Supplement]:
    return await SupplementService(store).schedule(active_only=active_only)


@router.post(
    "/schedule",
    response_model=Supplement,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un supplément",
)
async def create(payload: SupplementPayload, store: StoreDep) -> Supplement:
    return await SupplementService(store).create(payload)


@router.patch("/schedule/{row_id}", response_model=Supplement, summary="Modifier un supplément")
async def update(
    row_id: RowId, payload: SupplementPayload, store: StoreDep, if_match: IfMatch = None
) -> Supplement:
    return await SupplementService(store).update(row_id, _token(if_match), payload)


@router.delete(
    "/schedule/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer un supplément",
)
async def remove(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    """Retire du planning sans perdre l'historique des prises (`SUP-02`)."""
    await SupplementService(store).remove(row_id, _token(if_match))


@router.get("/units", response_model=list[str], summary="Unités proposées")
def units() -> list[str]:
    return list(UNITS)
