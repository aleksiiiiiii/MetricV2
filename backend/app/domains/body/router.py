"""Endpoints du domaine Corps (`BODY-01` → `BODY-10`).

## Garde anti-conflit

Chaque ligne rendue porte un `token`, empreinte de son contenu. Modifier ou supprimer
exige de le renvoyer dans l'en-tête `If-Match` : c'est la façon HTTP de dire « j'agis sur
la ligne telle que je l'ai lue » (`STO-05`). Si un autre appareil a modifié la ligne
entre-temps, le jeton ne correspond plus et le serveur refuse en `409` plutôt que
d'écraser la mauvaise valeur.

Un `DELETE` n'a pas de corps de requête naturel : l'en-tête est ce qui permet à la garde
de s'appliquer aussi à lui.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, status

from app.core.deps import StoreDep
from app.domains.body.schemas import (
    MeasurementEntry,
    MeasurementPayload,
    MeasurementView,
    WeightEntry,
    WeightPayload,
    WeightView,
)
from app.domains.body.service import MeasurementService, WeightService
from app.storage.errors import StorageConflictError

router = APIRouter(prefix="/body", tags=["corps"])

RowId = Annotated[int, Path(ge=0, description="Position de la ligne dans le fichier")]
IfMatch = Annotated[
    str | None,
    Header(alias="If-Match", description="Jeton de la ligne, tel que rendu par la lecture"),
]
Limit = Annotated[int, Query(ge=1, le=500, description="Taille de page")]
Offset = Annotated[int, Query(ge=0, description="Décalage de pagination")]


def _token_or_conflict(token: str | None) -> str:
    """Un `If-Match` absent est traité comme un conflit, jamais comme une permission.

    Sinon la garde se contournerait en omettant l'en-tête — ce qui la rendrait inutile.
    """
    if not token:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.",
            detail="en-tête If-Match absent",
        )
    return token.strip('"')


# ── Pesées ────────────────────────────────────────────


@router.get("/weight", response_model=WeightView, summary="Poids : indicateurs et historique")
async def read_weight(store: StoreDep, limit: Limit = 50, offset: Offset = 0) -> WeightView:
    """Indicateurs, série avec tendance et historique paginé, en une requête."""
    return await WeightService(store).view(limit=limit, offset=offset)


@router.post(
    "/weight",
    response_model=WeightEntry,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer une pesée",
)
async def create_weight(payload: WeightPayload, store: StoreDep) -> WeightEntry:
    return await WeightService(store).create(payload)


@router.patch("/weight/{row_id}", response_model=WeightEntry, summary="Corriger une pesée")
async def update_weight(
    row_id: RowId, payload: WeightPayload, store: StoreDep, if_match: IfMatch = None
) -> WeightEntry:
    return await WeightService(store).update(row_id, _token_or_conflict(if_match), payload)


@router.delete(
    "/weight/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une pesée",
)
async def delete_weight(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    await WeightService(store).delete(row_id, _token_or_conflict(if_match))


# ── Mensurations ──────────────────────────────────────


@router.get(
    "/measurements",
    response_model=MeasurementView,
    summary="Mensurations : indicateurs et historique",
)
async def read_measurements(
    store: StoreDep, limit: Limit = 50, offset: Offset = 0
) -> MeasurementView:
    return await MeasurementService(store).view(limit=limit, offset=offset)


@router.post(
    "/measurements",
    response_model=MeasurementEntry,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer des mensurations",
)
async def create_measurements(payload: MeasurementPayload, store: StoreDep) -> MeasurementEntry:
    return await MeasurementService(store).create(payload)


@router.patch(
    "/measurements/{row_id}",
    response_model=MeasurementEntry,
    summary="Corriger des mensurations",
)
async def update_measurements(
    row_id: RowId, payload: MeasurementPayload, store: StoreDep, if_match: IfMatch = None
) -> MeasurementEntry:
    return await MeasurementService(store).update(row_id, _token_or_conflict(if_match), payload)


@router.delete(
    "/measurements/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer des mensurations",
)
async def delete_measurements(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    await MeasurementService(store).delete(row_id, _token_or_conflict(if_match))
