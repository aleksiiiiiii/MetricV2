"""Point d'entrée de l'API Metric.

Ce module assemble l'application : cycle de vie des ressources partagées, gestionnaires
d'erreurs, découpage en routeurs par domaine (`API-01`) et route de santé (`API-04`).

Les routes publiques sont énumérées ici, et elles sont quatre : la santé, la documentation
(`API-05`), la connexion, et le flux iCal du planning (`PLAN-05`). Tout le reste exige un
jeton (`AUTH-05`).

Le flux iCal est le seul des quatre à servir des données personnelles, et le seul à porter
sa propre garde : une clé secrète dans son URL, parce qu'un abonnement Apple Calendar va
chercher son fichier tout seul et ne peut pas porter d'en-tête `Authorization`. Le
raisonnement complet, et ce qu'il impose, sont dans `app/domains/planning/router.py`.
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
from app.core.limits import RequestSizeLimit
from app.core.security import PasswordChecker, TokenIssuer
from app.core.throttle import LoginThrottle
from app.domains.ai.service import AiProvider
from app.domains.api import protected_router, public_router
from app.domains.brief.scheduler import BriefScheduler
from app.domains.heatmap.cache import GridCache
from app.domains.notifications.provider import PushProvider
from app.domains.planning import calendar_router
from app.storage.provider import StorageProvider


class HealthResponse(BaseModel):
    """État du service, pour vérification manuelle et supervision."""

    status: Literal["ok"] = "ok"
    version: str = Field(description="Version de l'application")
    environment: str = Field(description="Environnement d'exécution")
    time: datetime = Field(description="Heure locale du serveur, fuseau inclus")
    timezone: str = Field(description="Fuseau de découpage des journées")
    storage_configured: bool = Field(description="Stockage Nextcloud renseigné")
    auth_configured: bool = Field(description="Identifiant et hash de mot de passe présents")
    ai_enabled: bool = Field(description="Clé OpenRouter présente (IA-07)")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construit l'application. Paramétrable pour permettre des tests isolés."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Ouvre et referme les ressources partagées.

        Le client WebDAV détient un pool de connexions keep-alive (`STO-08`) : il doit
        naître dans la boucle d'événements et être relâché à l'arrêt. Les objets de
        sécurité sont construits une fois car ils portent un coût fixe — Argon2 est lent
        par conception.
        """
        provider = StorageProvider(settings)
        await provider.start()

        # Même cycle de vie, pour la même raison : un pool de connexions. Sans clé,
        # `start` ne construit rien et le fournisseur reste inerte (`IA-07`).
        ai = AiProvider(settings)
        await ai.start()

        # Le push, et l'ordonnanceur des rappels qui vit avec lui (`NOT-01`, `NOT-02`).
        # Même régime encore : sans paire de clés VAPID, rien ne démarre et rien n'est
        # bloqué. L'ordonnanceur est une **tâche de fond** — c'est le seul du projet, et
        # c'est pour cela qu'il tient au `lifespan` : une tâche créée ailleurs survivrait à
        # l'arrêt de l'application ou mourrait avec la requête qui l'a lancée.
        push = PushProvider(settings)
        await push.start(provider)

        # La lecture du jour, et sa passe horaire.
        #
        # **Deuxième tâche de fond du projet, et elle ne dépend pas de la première.**
        # `ReminderScheduler` ne démarre qu'avec une paire VAPID — correct pour lui, il
        # n'aurait personne à qui envoyer. Celle-ci s'affiche sur une carte : la lier au
        # réglage des notifications ferait dépendre un écran d'une clé qui n'a rien à y
        # faire. Sans clé OpenRouter ou sans stockage, rien ne démarre et rien n'est
        # bloqué — la carte porte alors son bouton, qui écrit la même ligne (`IA-07`).
        briefs: BriefScheduler | None = None
        if ai.enabled and settings.storage_configured:
            briefs = BriefScheduler(provider.store, ai.service)
            briefs.start()

        app.state.storage = provider
        app.state.ai = ai
        app.state.push = push
        app.state.password_checker = PasswordChecker(settings)
        app.state.token_issuer = TokenIssuer(settings)
        app.state.login_throttle = LoginThrottle()
        # Les grilles se mémorisent pour toute la durée de vie du processus, et sont
        # invalidées par la version de leurs fichiers sources et non par une horloge
        # (`HEAT-33`, décision **D8**).
        app.state.grid_cache = GridCache()
        try:
            yield
        finally:
            # Les ordonnanceurs en premier : ils lisent le stockage à chaque passe, et
            # les arrêter après lui les ferait échouer sur un client déjà refermé.
            if briefs is not None:
                await briefs.stop()
            await push.stop()
            await ai.stop()
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

    # Les réglages de **cette** application, pour les routes qui en dépendent. Posés ici
    # et non dans le `lifespan` : ce n'est pas une ressource à ouvrir et à refermer, et
    # une route ne doit pas dépendre du démarrage complet pour savoir comment elle est
    # configurée.
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Le plafond de transport, **au-dessus** du CORS pour être traversé en premier : un
    # corps trop gros est refusé avant d'être lu, et le refus prend la forme de toutes les
    # autres erreurs — `{code, message}` en français — plutôt qu'un `413` nu sur lequel le
    # client n'a rien à décider.
    app.add_middleware(RequestSizeLimit)

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
            auth_configured=bool(settings.auth_username and settings.auth_password_hash),
            ai_enabled=settings.ai_enabled,
        )

    # Le flux iCal se monte ici, à côté de la santé, et non dans le groupe protégé :
    # il porte sa propre garde et n'a pas de jeton à exiger (`PLAN-05`).
    app.include_router(calendar_router)
    app.include_router(public_router)
    app.include_router(protected_router)

    return app


app = create_app()
