"""Dépendances de la couche IA, pour les domaines qui s'en servent.

Elles vivent ici et non dans `app/core/deps.py` : le socle ne connaît pas les domaines, et
l'inverse mettrait `core` au courant d'OpenRouter. C'est le même arrangement que la
heatmap avec son cache de grilles.

`AiServiceDep` lève `AiUnavailableError` — donc un `503` porteur d'un code du catalogue
(`API-07`) — quand aucune clé n'est configurée. L'endpoint qui la demande n'a rien à
vérifier lui-même : sans clé, il ne s'exécute simplement pas, et le client reçoit une
phrase qui dit quoi faire (`IA-07`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.domains.ai.service import AiProvider, AiService


def get_ai_provider(request: Request) -> AiProvider:
    """Fournisseur IA attaché à l'application par le `lifespan`."""
    provider = getattr(request.app.state, "ai", None)
    if not isinstance(provider, AiProvider):  # pragma: no cover - erreur de câblage
        raise RuntimeError("« ai » n'a pas été initialisé par le lifespan.")
    return provider


def get_ai_service(provider: Annotated[AiProvider, Depends(get_ai_provider)]) -> AiService:
    """Service de cascade prêt à l'emploi, ou `AiUnavailableError` (`IA-07`)."""
    return provider.service


AiProviderDep = Annotated[AiProvider, Depends(get_ai_provider)]
AiServiceDep = Annotated[AiService, Depends(get_ai_service)]
