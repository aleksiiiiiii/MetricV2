"""Enveloppe d'erreur HTTP (`API-07`, `STO-09`).

Chaque échec métier sort sous la même forme : un **code machine stable** et un message
français. Le client mappe les codes vers ses propres formulations — il ne parse jamais
du texte, et un message reformulé ne casse rien.

Le catalogue complet des codes est établi au lot L02 ; on n'y branche ici que la couche
stockage, seule à pouvoir échouer à ce stade.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.storage.errors import StorageError

logger = logging.getLogger("metric.errors")


class ErrorBody(BaseModel):
    """Corps de réponse de toute erreur métier."""

    code: str = Field(description="Code machine stable, à mapper côté client")
    message: str = Field(description="Message français affichable en l'état")


async def handle_storage_error(request: Request, exc: Exception) -> JSONResponse:
    """Traduit une panne de stockage en réponse exploitable.

    Jamais de 500 brute (`STO-09`) : l'utilisateur doit pouvoir distinguer « Nextcloud
    est tombé, réessaie » de « ta modification est en conflit, recharge ».
    """
    assert isinstance(exc, StorageError)

    # Le détail technique va dans les journaux, pas dans la réponse : il contient des
    # chemins et des statuts qui n'aident pas l'utilisateur.
    logger.warning("%s %s → %s : %s", request.method, request.url.path, exc.code, exc)

    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorBody(code=exc.code, message=exc.message).model_dump(),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StorageError, handle_storage_error)
