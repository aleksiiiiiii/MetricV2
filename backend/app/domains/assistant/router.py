"""Endpoints de l'assistant (`IA-09` → `IA-12`).

Minces, comme partout : ils valident, appellent le service, rendent. Une seule ligne y fait
exception, et c'est la même qu'au lot L14 — la conversation reçoit l'écart plan / réalisé
**construit ici** plutôt que dans son service.

La raison est un sens de dépendance. `planning/service.py` lit l'objectif actif du domaine
Objectifs ; si le service de l'assistant importait le service du planning, il ferait
exécuter le paquet `planning` — donc son routeur — au milieu d'une chaîne d'imports que
l'ordre de `app/domains/api.py` suffirait à casser. Le routeur est l'endroit où les
domaines se composent : il va chercher `PLAN-06` là où il est écrit, et personne ne le
recalcule.

Ce routeur n'a **pas** à déclarer d'authentification : il est monté dans le groupe protégé
de `app/domains/api.py`, et un test structurel vérifie à chaque exécution que toute
opération publiée exige un jeton (`AUTH-05`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, status

from app.core.deps import StoreDep
from app.domains.ai.deps import AiServiceDep
from app.domains.assistant.schemas import (
    AssistantView,
    ChatReply,
    ChatRequest,
    MemoryEntry,
    MemoryPayload,
)
from app.domains.assistant.service import AssistantService
from app.domains.planning.service import DEFAULT_ADHERENCE_WEEKS, PlanningService
from app.storage.errors import StorageConflictError

router = APIRouter(prefix="/assistant", tags=["assistant"])

RowId = Annotated[int, Path(ge=0)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]


def _token(value: str | None) -> str:
    """Un `If-Match` absent est un **conflit**, jamais une permission (`STO-05`)."""
    if not value:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.", detail="en-tête If-Match absent"
        )
    return value.strip('"')


# ── Le carnet (`IA-11`) ───────────────────────────────


@router.get("/memory", response_model=AssistantView, summary="Ce qui a été retenu")
async def read_memory(store: StoreDep) -> AssistantView:
    """Le carnet et les sujets suggérés, en une requête.

    **Aucune dépendance à l'IA** : le carnet se lit, s'écrit et se corrige sans clé
    OpenRouter. C'est `IA-07` pris au mot — l'IA est un confort, et ce qu'elle apporte ici
    est de *proposer* ce qu'on aurait noté soi-même (`IA-11`).
    """
    return await AssistantService(store).view()


@router.post(
    "/memory",
    response_model=MemoryEntry,
    status_code=status.HTTP_201_CREATED,
    summary="Retenir une note",
)
async def remember(payload: MemoryPayload, store: StoreDep) -> MemoryEntry:
    """Écrit une note, marquée `manual` (`IA-11`).

    C'est aussi l'endpoint qu'emprunte une note **proposée** par l'assistant une fois
    validée : côté serveur, adopter une suggestion et l'écrire soi-même sont le même geste.
    Seule la colonne `source` les distingue, et c'est le client qui la demande.
    """
    return await AssistantService(store).remember(payload)


@router.post(
    "/memory/adopt",
    response_model=MemoryEntry,
    status_code=status.HTTP_201_CREATED,
    summary="Retenir une note proposée",
)
async def adopt(payload: MemoryPayload, store: StoreDep) -> MemoryEntry:
    """Écrit une note proposée par l'assistant, marquée `ai` (`IA-10`).

    Aucune dépendance à l'IA non plus : une fois la suggestion relue et éventuellement
    retouchée, il ne reste qu'une saisie. C'est ce qui permet de retenir une note affichée
    il y a dix minutes, ou dont on a réécrit la moitié.
    """
    return await AssistantService(store).remember(payload, source="ai")


@router.patch("/memory/{row_id}", response_model=MemoryEntry, summary="Corriger une note")
async def update(
    row_id: RowId, payload: MemoryPayload, store: StoreDep, if_match: IfMatch = None
) -> MemoryEntry:
    return await AssistantService(store).update(row_id, _token(if_match), payload)


@router.delete(
    "/memory/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Oublier une note",
)
async def forget(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    await AssistantService(store).forget(row_id, _token(if_match))


# ── La conversation (`IA-09`, `IA-10`) ────────────────


@router.post("/chat", response_model=ChatReply, summary="Poser une question")
async def chat(payload: ChatRequest, store: StoreDep, ai: AiServiceDep) -> ChatReply:
    """Répond à partir des données de l'utilisateur. **Rien n'est écrit** (`IA-10`).

    Sans clé OpenRouter, `AiServiceDep` fait échouer l'endpoint avec un code du catalogue
    avant même d'entrer ici (`IA-07`) : le carnet, lui, reste entier.

    L'écart plan / réalisé est lu chez `PLAN-06` et passé au service — voir l'en-tête de ce
    module. Huit semaines, la fenêtre par défaut du taux de respect.
    """
    adherence = await PlanningService(store).adherence(weeks=DEFAULT_ADHERENCE_WEEKS)
    return await AssistantService(store).ask(ai, payload, adherence=adherence)
