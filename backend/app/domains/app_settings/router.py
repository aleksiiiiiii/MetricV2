"""Endpoints de réglages.

Lecture seule au lot L04 : l'édition arrive au L08 avec le reste du domaine.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import StoreDep
from app.domains.app_settings.service import SettingsService

router = APIRouter(prefix="/settings", tags=["réglages"])


@router.get("", summary="Réglages utilisateur")
async def read_settings(store: StoreDep) -> dict[str, str]:
    """Réglages en vigueur, défauts compris.

    Le client reçoit les valeurs effectives et n'a pas à connaître les repli : il ne
    peut donc pas diverger du serveur sur ce que vaut un objectif non renseigné.
    """
    return await SettingsService(store).all()
