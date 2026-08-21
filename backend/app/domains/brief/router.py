"""Endpoints de la lecture du jour.

Minces, comme partout. Une seule ligne y fait exception et elle est motivée : l'écart plan
/ réalisé est **construit ici** puis passé au service, pour la raison écrite dans l'en-tête
de `goals/router.py` — le routeur est l'endroit où les domaines se composent, et `PLAN-06`
n'a qu'une implémentation.

## `GET` lit, `POST` écrit

`GET` rend `state: 'absent'` tant que le jour n'a pas sa ligne, et n'interroge aucun
modèle. Un `GET` qui générerait rendrait le tableau de bord lent et non déterministe à
chaque ouverture, et fausserait autant le cache HTTP que la promesse « une lecture n'est
écrite qu'une fois par jour ».

Ce routeur n'a **pas** à déclarer d'authentification : il est monté dans le groupe protégé
de `app/domains/api.py`, et un test structurel vérifie à chaque exécution que toute
opération publiée exige un jeton (`AUTH-05`).
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core.deps import StoreDep
from app.domains.ai.deps import AiServiceDep
from app.domains.brief.schemas import BriefThread, BriefView
from app.domains.brief.service import BriefService
from app.domains.planning.service import DEFAULT_ADHERENCE_WEEKS, PlanningService

router = APIRouter(prefix="/brief", tags=["lecture du jour"])


@router.get("", response_model=BriefView, summary="La lecture du jour")
async def read_brief(store: StoreDep) -> BriefView:
    """Ce qui a été écrit pour aujourd'hui. **Aucun modèle n'est interrogé.**"""
    return await BriefService(store).view()


@router.post(
    "",
    response_model=BriefView,
    status_code=status.HTTP_201_CREATED,
    summary="Écrire la lecture du jour",
)
async def write_brief(store: StoreDep, ai: AiServiceDep) -> BriefView:
    """Demande la lecture du jour et la range. Rappelée, elle remplace celle du jour."""
    adherence = await PlanningService(store).adherence(weeks=DEFAULT_ADHERENCE_WEEKS)
    return await BriefService(store).generate(ai, adherence=adherence)


@router.post(
    "/thread",
    response_model=BriefThread,
    status_code=status.HTTP_201_CREATED,
    summary="Ouvrir le fil de la lecture du jour",
)
async def open_thread(store: StoreDep) -> BriefThread:
    """Le fil dans lequel répondre — créé au premier appui, rendu tel quel ensuite."""
    return await BriefService(store).thread()
