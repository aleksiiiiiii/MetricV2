"""Point d'entrée de l'API Metric.

Le découpage en routeurs par domaine (`API-01`) est mis en place au lot L02 ; ce module
porte l'assemblage de l'application, le cycle de vie de la couche stockage, et la route
de santé (`API-04`), qui reste publique (`AUTH-05`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import __version__
from app.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.storage.provider import StorageProvider


class HealthResponse(BaseModel):
    """État du service, pour vérification manuelle et supervision."""

    status: Literal["ok"] = "ok"
    version: str = Field(description="Version de l'application")
    environment: str = Field(description="Environnement d'exécution")
    time: datetime = Field(description="Heure locale du serveur, fuseau inclus")
    timezone: str = Field(description="Fuseau de découpage des journées")
    storage_configured: bool = Field(description="Stockage Nextcloud renseigné")
    ai_enabled: bool = Field(description="Clé OpenRouter présente (IA-07)")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construit l'application. Paramétrable pour permettre des tests isolés."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Ouvre et referme le pool de connexions Nextcloud (`STO-08`).

        Le client WebDAV doit naître dans la boucle d'événements, et ses connexions
        keep-alive être relâchées à l'arrêt.
        """
        provider = StorageProvider(settings)
        await provider.start()
        app.state.storage = provider
        try:
            yield
        finally:
            await provider.stop()

    app = FastAPI(
        title="Metric",
        version=__version__,
        description=(
            "API de suivi sportif personnel. Stockage CSV sur Nextcloud, "
            "mono-utilisateur, unités métriques."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    @app.get(
        "/api/health",
        response_model=HealthResponse,
        summary="État du service",
        tags=["système"],
    )
    def health() -> HealthResponse:
        return HealthResponse(
            version=__version__,
            environment=settings.app_env,
            time=datetime.now(tz=settings.tz),
            timezone=settings.timezone,
            storage_configured=settings.storage_configured,
            ai_enabled=settings.ai_enabled,
        )

    return app


app = create_app()
