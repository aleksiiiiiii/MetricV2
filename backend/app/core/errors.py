"""Traduction des erreurs en réponses HTTP (`API-07`, `STO-09`).

Quatre gestionnaires couvrent tout ce qui peut sortir de l'API :

* `MetricError` — le catalogue métier, y compris la couche stockage ;
* `RequestValidationError` — les bornes de vraisemblance de `API-06` ;
* `HTTPException` — ce que FastAPI lève lui-même (404 de routage, 405…) ;
* `Exception` — le filet de sécurité : jamais de traceback dans une réponse.

Toutes renvoient la même forme, `{code, message}`, éventuellement enrichie de `fields`
pour une erreur de validation.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import MetricError, ValidationFailedError

logger = logging.getLogger("metric.errors")

#: Statuts levés par FastAPI lui-même — 404 de routage, 405 de méthode — rattachés à un
#: code du catalogue et à un message français.
#:
#: Le `detail` d'origine est délibérément ignoré : Starlette le rédige en anglais
#: (« Not Found »), et l'API doit répondre en français (`STO-09`, `API-07`). Notre propre
#: code ne lève jamais `HTTPException`, il lève des `MetricError` — rien n'est perdu.
_HTTP_FALLBACKS = {
    401: ("session_expired", "Session expirée. Reconnecte-toi."),
    403: ("forbidden", "Accès refusé."),
    404: ("not_found", "Cette ressource n'existe pas."),
    405: ("method_not_allowed", "Cette méthode n'est pas autorisée sur cette adresse."),
    422: ("validation_error", "Les données envoyées sont invalides."),
}


class FieldError(BaseModel):
    """Champ refusé et raison, pour que le client sache quoi surligner."""

    field: str = Field(description="Chemin du champ, ex. « body.weight_kg »")
    message: str = Field(description="Raison du refus")


class ErrorBody(BaseModel):
    """Corps de réponse de toute erreur."""

    code: str = Field(description="Code machine stable, à mapper côté client")
    message: str = Field(description="Message français affichable en l'état")
    fields: list[FieldError] | None = Field(
        default=None, description="Détail par champ, sur une erreur de validation"
    )


def _respond(error: MetricError, extra: dict[str, Any] | None = None) -> JSONResponse:
    body = ErrorBody(code=error.code, message=error.message).model_dump(exclude_none=True)
    return JSONResponse(
        status_code=error.status_code,
        content={**body, **(extra or {})},
        headers=error.headers,
    )


async def handle_metric_error(request: Request, exc: Exception) -> JSONResponse:
    """Traduit une erreur du catalogue.

    Le détail technique part dans les journaux et pas dans la réponse : il contient des
    chemins de stockage et des statuts amont qui n'aident pas l'utilisateur.
    """
    assert isinstance(exc, MetricError)

    log = logger.warning if exc.status_code < 500 else logger.error
    log("%s %s → %s : %s", request.method, request.url.path, exc.code, exc)

    return _respond(exc)


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Traduit un refus de validation Pydantic (`API-06`).

    On renvoie le détail par champ — contrairement aux autres erreurs : ici l'information
    vient de la requête de l'utilisateur, elle ne révèle rien de l'infrastructure, et
    c'est ce qui permet de surligner le bon champ dans le formulaire.
    """
    assert isinstance(exc, RequestValidationError)

    fields = [
        FieldError(
            field=".".join(str(part) for part in error["loc"]) or "?",
            message=str(error.get("msg", "valeur invalide")),
        )
        for error in exc.errors()
    ]
    logger.info("%s %s → validation_error : %s", request.method, request.url.path, fields)

    return _respond(
        ValidationFailedError(),
        {"fields": [field.model_dump() for field in fields]},
    )


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """Rattache les erreurs levées par FastAPI au même format que les nôtres."""
    assert isinstance(exc, StarletteHTTPException)

    code, message = _HTTP_FALLBACKS.get(
        exc.status_code, ("http_error", "La requête n'a pas pu être traitée.")
    )

    error = MetricError(message, detail=f"{request.method} {request.url.path} — {exc.detail}")
    error.code = code
    error.status_code = exc.status_code
    error.headers = getattr(exc, "headers", None)

    return _respond(error)


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Filet de sécurité : une exception non prévue ne fuit jamais son traceback."""
    logger.exception("%s %s → erreur non gérée", request.method, request.url.path, exc_info=exc)

    return _respond(MetricError())


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(MetricError, handle_metric_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
