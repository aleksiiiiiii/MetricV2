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

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, status
from fastapi.responses import StreamingResponse

from app.core.deps import StoreDep
from app.core.exceptions import MetricError
from app.domains.ai.deps import AiServiceDep
from app.domains.assistant.schemas import (
    ActionReport,
    AssistantView,
    ChatReply,
    ChatRequest,
    ConfirmRequest,
    MemoryEntry,
    MemoryPayload,
    RenamePayload,
    ThreadDetail,
    ThreadList,
    ThreadSummary,
)
from app.domains.assistant.service import AssistantService
from app.domains.planning.service import DEFAULT_ADHERENCE_WEEKS, PlanningService
from app.storage.errors import StorageConflictError

logger = logging.getLogger("metric.assistant")

router = APIRouter(prefix="/assistant", tags=["assistant"])

RowId = Annotated[int, Path(ge=0)]
ThreadId = Annotated[str, Path(min_length=1, max_length=32)]
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

    C'était aussi l'endpoint qu'empruntait une note **proposée** par l'assistant une fois
    validée. Plus rien ne propose : le carnet se remplit tout seul pendant la conversation,
    et `/memory/adopt` a été retiré plutôt que laissé à rouiller. Ce qui reste ici est la
    saisie à la main, qui n'a jamais eu besoin d'une clé API (`IA-11`).
    """
    return await AssistantService(store).remember(payload)


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


# ── Les fils (`IA-13`) ────────────────────────────────


@router.get("/threads", response_model=ThreadList, summary="Les discussions")
async def threads(store: StoreDep) -> ThreadList:
    """La liste des fils, du plus récemment actif au plus ancien.

    **Sans dépendance à l'IA**, comme le carnet : relire ce qui a été dit ne demande
    aucune clé, et une panne de modèle ne doit pas fermer l'accès à ses propres
    discussions (`IA-07`).
    """
    return await AssistantService(store).threads()


@router.get("/threads/{thread_id}", response_model=ThreadDetail, summary="Une discussion")
async def thread(thread_id: ThreadId, store: StoreDep) -> ThreadDetail:
    return await AssistantService(store).thread(thread_id)


@router.patch(
    "/threads/{thread_id}",
    response_model=ThreadSummary,
    summary="Renommer une discussion",
)
async def rename_thread(
    thread_id: ThreadId, payload: RenamePayload, store: StoreDep
) -> ThreadSummary:
    """Change le titre d'un fil, et rien d'autre.

    Les titres sont écrits par le modèle à l'ouverture, et il se trompe. On ne pouvait que
    supprimer le fil — ce qui emportait la conversation avec son mauvais titre.

    **Sans dépendance à l'IA**, comme la liste et le carnet : corriger un libellé n'a pas
    à attendre qu'un modèle réponde (`IA-07`). Et sans garde `If-Match`, pour la même
    raison que la suppression : un fil se désigne par son identifiant stable et non par sa
    position dans le fichier.
    """
    return await AssistantService(store).rename_thread(thread_id, payload.title)


@router.delete(
    "/threads/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une discussion",
)
async def forget_thread(thread_id: ThreadId, store: StoreDep) -> None:
    """Supprime un fil et ses messages.

    Sans garde `If-Match`, contrairement à une note : un fil se désigne par son
    identifiant stable et non par sa position, et le conflit que la garde protège — deux
    écrans qui renumérotent la même liste — n'existe pas ici. La confirmation est à
    l'écran, là où elle se lit.
    """
    await AssistantService(store).forget_thread(thread_id)


@router.delete(
    "/threads",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Effacer toutes les discussions",
)
async def forget_all_threads(store: StoreDep) -> None:
    """Vide l'historique des conversations. **Le carnet n'est pas touché** : ce qui a été
    retenu survit à l'effacement des discussions qui l'ont produit, et c'est bien le
    partage voulu entre les deux (`IA-11`)."""
    await AssistantService(store).forget_all_threads()


# ── Les actions (`IA-15`) ─────────────────────────────


@router.post("/actions/confirm", response_model=ActionReport, summary="Exécuter une action")
async def confirm(payload: ConfirmRequest, store: StoreDep) -> ActionReport:
    """Exécute une action que l'assistant avait laissée en attente.

    **Sans dépendance à l'IA** : confirmer n'interroge aucun modèle. C'est une écriture
    ordinaire, dont l'assistant n'a fait que rédiger les arguments — et l'utilisateur
    aurait pu appeler la route du domaine lui-même, ce qu'il fait tous les jours depuis
    les autres écrans.

    L'action est revalidée entièrement contre le catalogue : rien n'est retenu entre la
    proposition et la confirmation, donc rien ne peut être confirmé qui n'aurait pas pu
    être demandé.
    """
    return await AssistantService(store).confirm(payload)


# ── La conversation (`IA-09`, `IA-10`) ────────────────


@router.post("/chat", response_model=ChatReply, summary="Poser une question")
async def chat(payload: ChatRequest, store: StoreDep, ai: AiServiceDep) -> ChatReply:
    """Répond à partir des données de l'utilisateur, dans un fil.

    Sans clé OpenRouter, `AiServiceDep` fait échouer l'endpoint avec un code du catalogue
    avant même d'entrer ici (`IA-07`) : le carnet, lui, reste entier.

    L'écart plan / réalisé est lu chez `PLAN-06` et passé au service — voir l'en-tête de ce
    module. Huit semaines, la fenêtre par défaut du taux de respect.
    """
    adherence = await PlanningService(store).adherence(weeks=DEFAULT_ADHERENCE_WEEKS)
    return await AssistantService(store).ask(ai, payload, adherence=adherence)


@router.post("/chat/stream", summary="Poser une question, en suivant l'avancement")
async def chat_stream(payload: ChatRequest, store: StoreDep, ai: AiServiceDep) -> StreamingResponse:
    """La même réponse que `/chat`, précédée de ce que le serveur est en train de faire.

    ## Pourquoi un flux, et pourquoi pas les jetons du modèle

    Une réponse demande cinq à quinze secondes, et l'écran n'affichait que trois points.
    Streamer le texte du modèle, lui, n'est **pas** possible sans casser autre chose : la
    conversation rend un objet JSON — `reply`, `remember`, `actions`, `need` — dont l'ordre
    des champs n'est pas garanti, et une seconde passe remplace entièrement la première.
    Un texte affiché au fil de l'eau devrait donc parfois être effacé sous les yeux.

    Ce flux transporte donc des **étapes**, pas des jetons. Chacune est émise au moment où
    elle commence : ce que l'écran affiche est arrivé, ce qui est la seule différence qui
    compte entre un compte rendu et une animation.

    ## La forme

    `event: step` pendant, puis exactement un `event: reply` ou un `event: error` à la fin.
    L'erreur voyage **dans le flux** et non en statut HTTP : les en-têtes sont partis
    depuis longtemps quand un modèle renonce. Elle porte le même `{code, message}` que
    partout ailleurs, pour que le client décide sur le code comme d'habitude (`API-07`).
    """
    adherence = await PlanningService(store).adherence(weeks=DEFAULT_ADHERENCE_WEEKS)
    service = AssistantService(store)

    async def events() -> AsyncIterator[str]:
        steps: asyncio.Queue[str | None] = asyncio.Queue()

        async def report(message: str) -> None:
            await steps.put(message)

        async def run() -> ChatReply:
            try:
                return await service.ask(ai, payload, adherence=adherence, on_step=report)
            finally:
                # La sentinelle libère le lecteur, que la réponse arrive ou qu'elle échoue.
                await steps.put(None)

        task = asyncio.create_task(run())

        while True:
            step = await steps.get()
            if step is None:
                break
            yield _sse("step", {"step": step})

        try:
            reply = await task
        except MetricError as error:
            logger.warning("chat diffusé → %s : %s", error.code, error)
            yield _sse("error", {"code": error.code, "message": error.message})
            return

        yield _sse("reply", reply.model_dump(mode="json"))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # Sans lui, Nginx met le flux en tampon et livre les étapes **toutes ensemble
            # à la fin** — ce qui rend l'endpoint exactement aussi muet qu'avant, sans
            # que rien ne le signale en développement où il n'y a pas de proxy.
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    """Un événement `text/event-stream`, terminé par sa ligne vide."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
