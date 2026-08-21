"""Endpoints de l'import Apple (`IMP-01` → `IMP-06`).

Deux routes, et leur séparation **est** la garantie de `IMP-01` : `analyze` ne sait pas
écrire, `confirm` ne sait pas lire une image. Aucun chemin ne mène de la capture au fichier
sans passer par un appui de l'utilisateur.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from app.core.deps import StoreDep
from app.core.exceptions import ValidationFailedError
from app.domains.ai.deps import AiServiceDep
from app.domains.imports.schemas import AppleDraft, AppleImportPayload, ImportResult
from app.domains.imports.service import AppleImportService

router = APIRouter(prefix="/import", tags=["import"])


#: Nombre de captures acceptées en un import. Le résumé, la liste des paliers, et de quoi
#: la faire défiler en deux ou trois fois sur une course longue. Au-delà, ce ne sont plus
#: les écrans d'une même séance — et chaque image coûte des jetons à un modèle gratuit.
MAX_SCREENSHOTS = 6


@router.post("/apple/analyze", response_model=AppleDraft, summary="Lire des captures Apple")
async def analyze(
    store: StoreDep,
    ai: AiServiceDep,
    screenshot: Annotated[list[UploadFile], File()],
) -> AppleDraft:
    """Pré-remplit une activité depuis une ou plusieurs captures. **Rien n'est écrit**
    (`IMP-01`).

    Le champ garde son nom au **singulier** alors qu'il accepte désormais une liste : c'est
    le nom que le client envoie déjà, et une requête multipart qui répète `screenshot`
    deux fois est exactement ce qu'un `<input multiple>` produit. Le renommer aurait cassé
    l'écran d'import pour un pluriel.

    Le dépôt est tout de même nécessaire : la détection de doublon (`IMP-04`) relit
    l'historique. Elle le lit, elle n'y touche pas.

    Une capture inexploitable rend `ai_unreadable` avec un message qui propose de refaire
    la capture ou de saisir à la main (`IMP-06`) — jamais un formulaire vide présenté
    comme un import réussi.
    """
    if not screenshot:
        raise ValidationFailedError("Ajoute au moins une capture à lire.")
    if len(screenshot) > MAX_SCREENSHOTS:
        raise ValidationFailedError(f"{MAX_SCREENSHOTS} captures au maximum pour une même séance.")

    shots: list[bytes] = []
    for upload in screenshot:
        shots.append(await upload.read())
        await upload.close()
    return await AppleImportService(store).analyze(ai, shots)


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
