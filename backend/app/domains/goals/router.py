"""Endpoints des objectifs et du bilan hebdomadaire (`GOAL-01` → `GOAL-06`, `IA-08`).

Minces, comme partout : ils valident, appellent le service, rendent. Une seule ligne y
fait exception, et elle est motivée — le bilan hebdomadaire reçoit l'écart plan / réalisé
**construit ici** plutôt que dans son service.

La raison est un sens de dépendance. `planning/service.py` lit l'objectif actif pour
remplir la consigne d'une proposition (`PLAN-03`) ; si le service des bilans importait à
son tour le service du planning, les deux domaines s'importeraient mutuellement et l'ordre
de chargement des modules deviendrait une question. Le routeur est l'endroit où les
domaines se composent : c'est lui qui va chercher `PLAN-06` là où il est écrit, et le
service des bilans ne le recalcule pas — ce qui était de toute façon la contrainte.

Ce routeur n'a **pas** à déclarer d'authentification : il est monté dans le groupe protégé
de `app/domains/api.py`, et un test structurel vérifie à chaque exécution que toute
opération publiée exige un jeton (`AUTH-05`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, status

from app.core.deps import StoreDep
from app.domains.ai.deps import AiServiceDep
from app.domains.goals.schemas import (
    GoalEntry,
    GoalPayload,
    GoalProposal,
    GoalsView,
    ProposalRequest,
    WeeklyEntry,
    WeeklyPayload,
    WeeklyReview,
    WeeklyView,
)
from app.domains.goals.service import GoalService, WeeklyInsightService
from app.domains.planning.service import DEFAULT_ADHERENCE_WEEKS, PlanningService
from app.storage.errors import StorageConflictError

router = APIRouter(prefix="/goals", tags=["objectifs"])

RowId = Annotated[int, Path(ge=0)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]


def _token(value: str | None) -> str:
    """Un `If-Match` absent est un **conflit**, jamais une permission (`STO-05`)."""
    if not value:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.", detail="en-tête If-Match absent"
        )
    return value.strip('"')


# ── L'objectif (`GOAL-04`, `GOAL-05`, `GOAL-06`) ──────


@router.get("", response_model=GoalsView, summary="Objectif en cours et historique")
async def read_goals(store: StoreDep) -> GoalsView:
    """L'état, l'objectif actif avec sa progression, et les objectifs clos (`GOAL-05`).

    Une requête et non trois : l'écran ne sait rien afficher tant qu'il n'a pas les trois,
    et chacune rouvrirait les mêmes fichiers.
    """
    return await GoalService(store).view()


@router.post(
    "",
    response_model=GoalEntry,
    status_code=status.HTTP_201_CREATED,
    summary="Adopter un objectif",
)
async def adopt(payload: GoalPayload, store: StoreDep) -> GoalEntry:
    """Écrit l'objectif retenu, marqué `source=ai` (`GOAL-03`).

    Aucune dépendance à l'IA : une fois la proposition relue et éventuellement retouchée,
    il ne reste qu'une saisie. C'est ce qui permet d'adopter un objectif affiché il y a dix
    minutes, ou dont on a réécrit le titre.
    """
    return await GoalService(store).adopt(payload)


@router.post("/{row_id}/close", response_model=GoalEntry, summary="Clore un objectif")
async def close(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> GoalEntry:
    """Clôt l'objectif et **calcule** son résultat : atteint ou partiel (`GOAL-06`)."""
    return await GoalService(store).close(row_id, _token(if_match))


@router.post("/{row_id}/abandon", response_model=GoalEntry, summary="Abandonner un objectif")
async def abandon(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> GoalEntry:
    """Ferme l'objectif sur « abandonné » (`GOAL-03`)."""
    return await GoalService(store).abandon(row_id, _token(if_match))


# ── Proposition assistée (`GOAL-01`, `GOAL-02`) ───────


@router.post("/proposal", response_model=GoalProposal, summary="Proposer un objectif")
async def propose(payload: ProposalRequest, store: StoreDep, ai: AiServiceDep) -> GoalProposal:
    """Demande un objectif à un modèle. **Rien n'est écrit** (`GOAL-03`).

    Sans clé OpenRouter, `AiServiceDep` fait échouer l'endpoint avec un code du catalogue
    avant même d'entrer ici (`IA-07`) : se fixer une cible à la main, l'adopter, la clore
    et lire sa progression restent entiers.
    """
    return await GoalService(store).propose(ai, payload)


# ── Bilan hebdomadaire (`IA-08`) ──────────────────────


@router.get("/weekly", response_model=WeeklyView, summary="Historique des bilans")
async def read_weekly(store: StoreDep) -> WeeklyView:
    return await WeeklyInsightService(store).view()


@router.post("/weekly", response_model=WeeklyReview, summary="Produire un bilan")
async def review(store: StoreDep, ai: AiServiceDep) -> WeeklyReview:
    """Bilan de la semaine révolue. **Rien n'est écrit** tant qu'il n'est pas conservé.

    L'écart plan / réalisé est lu chez `PLAN-06` et passé au service : voir l'en-tête de
    ce module pour la raison. Huit semaines, la fenêtre par défaut du taux de respect —
    la semaine commentée en fait partie, et les précédentes servent à la situer.
    """
    adherence = await PlanningService(store).adherence(weeks=DEFAULT_ADHERENCE_WEEKS)
    return await WeeklyInsightService(store).generate(ai, adherence=adherence)


@router.post(
    "/weekly/keep",
    response_model=WeeklyEntry,
    status_code=status.HTTP_201_CREATED,
    summary="Conserver un bilan",
)
async def keep(payload: WeeklyPayload, store: StoreDep) -> WeeklyEntry:
    """Historise le bilan (`IA-08`). Une semaine, une ligne : reconserver remplace."""
    return await WeeklyInsightService(store).keep(payload)


@router.delete(
    "/weekly/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer un bilan de l'historique",
)
async def remove_weekly(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    await WeeklyInsightService(store).remove(row_id, _token(if_match))
