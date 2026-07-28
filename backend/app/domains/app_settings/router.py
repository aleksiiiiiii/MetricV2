"""Endpoints de réglages (`L08-01`, `L08-02`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header

from app.core.deps import StoreDep
from app.domains.app_settings.schemas import SettingsPayload, SettingsView
from app.domains.app_settings.service import SettingsService
from app.storage.errors import StorageConflictError

router = APIRouter(prefix="/settings", tags=["réglages"])

IfMatch = Annotated[str | None, Header(alias="If-Match")]


@router.get("", response_model=SettingsView, summary="Réglages utilisateur")
async def read_settings(store: StoreDep) -> SettingsView:
    """Réglages en vigueur, valeurs de repli comprises.

    Le client reçoit les valeurs effectives **et** les défauts : il n'a donc aucune
    constante à recopier, et ne peut pas diverger du serveur sur ce que vaut un objectif
    non renseigné.
    """
    return await SettingsService(store).view()


@router.patch("", response_model=SettingsView, summary="Modifier les réglages")
async def update_settings(
    payload: SettingsPayload, store: StoreDep, if_match: IfMatch = None
) -> SettingsView:
    """Modification partielle : un champ omis reste à sa valeur.

    La garde porte sur le fichier entier et non sur une ligne : un jeu de réglages
    s'édite en bloc. Un `If-Match` **absent est un conflit**, jamais une permission —
    sinon la garde se contournerait en omettant l'en-tête (`STO-05`).
    """
    if not if_match:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.", detail="en-tête If-Match absent"
        )
    return await SettingsService(store).update(payload, if_match.strip('"'))
