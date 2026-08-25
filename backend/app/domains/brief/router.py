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

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import StoreDep
from app.domains.ai.deps import AiServiceDep
from app.domains.brief.schemas import BriefSlot, BriefThread, BriefView
from app.domains.brief.service import BriefService
from app.domains.planning.service import DEFAULT_ADHERENCE_WEEKS, PlanningService

router = APIRouter(prefix="/brief", tags=["lecture du jour"])


#: Le créneau demandé. Absent, c'est celui en cours qui est rendu — décidé par le serveur,
#: qui seul tient l'heure et le fuseau (`HEAT-32`).
SlotQuery = Annotated[BriefSlot | None, Query(description="matin, midi ou soir")]


@router.get("", response_model=BriefView, summary="La lecture du moment")
async def read_brief(store: StoreDep, slot: SlotQuery = None) -> BriefView:
    """Ce qui a été écrit pour ce moment de la journée. **Aucun modèle n'est interrogé.**"""
    return await BriefService(store).view(slot=slot)


@router.post(
    "",
    response_model=BriefView,
    status_code=status.HTTP_201_CREATED,
    summary="Écrire la lecture du moment",
)
async def write_brief(store: StoreDep, ai: AiServiceDep, slot: SlotQuery = None) -> BriefView:
    """Demande la lecture d'un créneau et la range. Rappelée, elle remplace la sienne."""
    adherence = await PlanningService(store).adherence(weeks=DEFAULT_ADHERENCE_WEEKS)
    return await BriefService(store).generate(ai, adherence=adherence, slot=slot)


@router.post(
    "/thread",
    response_model=BriefThread,
    status_code=status.HTTP_201_CREATED,
    summary="Ouvrir le fil de la lecture du jour",
)
async def open_thread(store: StoreDep, slot: SlotQuery = None) -> BriefThread:
    """Le fil dans lequel répondre — créé au premier appui, rendu tel quel ensuite."""
    return await BriefService(store).thread(slot=slot)
