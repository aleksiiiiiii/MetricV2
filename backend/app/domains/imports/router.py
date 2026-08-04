"""Endpoints de l'import Apple (`IMP-01` → `IMP-06`).

Deux routes, et leur séparation **est** la garantie de `IMP-01` : `analyze` ne sait pas
écrire, `confirm` ne sait pas lire une image. Aucun chemin ne mène de la capture au fichier
sans passer par un appui de l'utilisateur.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from app.core.deps import StoreDep
from app.domains.ai.deps import AiServiceDep
from app.domains.imports.schemas import AppleDraft, AppleImportPayload, ImportResult
from app.domains.imports.service import AppleImportService

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/apple/analyze", response_model=AppleDraft, summary="Lire une capture Apple")
async def analyze(
    store: StoreDep,
    ai: AiServiceDep,
    screenshot: Annotated[UploadFile, File()],
) -> AppleDraft:
    """Pré-remplit une activité depuis une capture. **Rien n'est écrit** (`IMP-01`).

    Le dépôt est tout de même nécessaire : la détection de doublon (`IMP-04`) relit
    l'historique. Elle le lit, elle n'y touche pas.

    Une capture inexploitable rend `ai_unreadable` avec un message qui propose de refaire
    la capture ou de saisir à la main (`IMP-06`) — jamais un formulaire vide présenté
    comme un import réussi.
    """
    data = await screenshot.read()
    await screenshot.close()
    return await AppleImportService(store).analyze(ai, data)


@router.post(
    "/apple",
    response_model=ImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Importer l'activité validée",
)
async def confirm(payload: AppleImportPayload, store: StoreDep) -> ImportResult:
    """Écrit l'activité telle que l'utilisateur l'a validée, `source=apple` (`IMP-05`).

    Aucune dépendance à l'IA : une fois le pré-remplissage corrigé, il n'y a plus qu'une
    saisie. C'est ce qui permet d'importer une capture analysée il y a dix minutes, ou de
    valider un brouillon dont on a tout réécrit.
    """
    return await AppleImportService(store).confirm(payload)
