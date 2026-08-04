"""Endpoints de la couche IA (`IA-02`, `IA-07`).

Deux routes seulement, et aucune n'analyse quoi que ce soit : l'analyse appartient aux
domaines qui ont quelque chose à faire analyser — la nutrition pour une assiette
(`NUT-04`), l'import pour une capture (`IMP-01`). Ce routeur ne publie que l'état de
l'assistance et le catalogue qu'elle utilise.

`GET /api/ai/models` est **la seule route du projet qui interroge réellement OpenRouter
sans qu'on lui donne d'image**. Elle sert à vérifier la découverte (`IA-02`) : le catalogue
gratuit change en permanence, et c'est la chose qu'aucun test simulé ne peut confirmer.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import AiQuotaError, AiUnavailableError
from app.domains.ai.client import ModelQuotaError, ModelUnusableError
from app.domains.ai.deps import AiProviderDep
from app.domains.ai.schemas import AiModel, AiModels, AiStatus

router = APIRouter(prefix="/ai", tags=["ia"])


@router.get("/status", response_model=AiStatus, summary="État de l'assistance IA")
def status(provider: AiProviderDep) -> AiStatus:
    """Dit si l'assistance est disponible, et sinon pourquoi (`IA-07`).

    Répond `200` dans les deux cas : l'absence de clé est un **état**, pas une panne. Un
    écran qui reçoit une erreur ici cacherait son bloc IA pour la mauvaise raison.
    """
    return AiStatus(enabled=provider.enabled, message=provider.message)


@router.get("/models", response_model=AiModels, summary="Modèles gratuits découverts")
async def models(provider: AiProviderDep) -> AiModels:
    """Catalogue gratuit, filtré et classé (`IA-02`). Mémorisé une heure."""
    catalogue = provider.catalogue
    cached = catalogue.fresh
    try:
        listed = await catalogue.all()
    except ModelQuotaError as exc:
        raise AiQuotaError from exc
    except ModelUnusableError as exc:
        raise AiUnavailableError(
            "Le catalogue des modèles est injoignable pour l'instant."
        ) from exc

    return AiModels(
        models=[
            AiModel(
                id=model.id,
                name=model.name,
                context_length=model.context_length,
                vision=model.vision,
                params_b=model.params_b,
            )
            for model in listed
        ],
        cached=cached,
    )
