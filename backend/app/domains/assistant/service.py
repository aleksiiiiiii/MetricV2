"""Assistant conversationnel et mémoire de santé (`IA-09` → `IA-12`).

Deux moitiés, et leur séparation est la garantie du lot : **`ask` ne sait pas écrire**, et
le carnet ne sait pas interroger un modèle. Entre les deux, un écran et un appui — c'est là
que vit `IA-10`, comme `NUT-04`, `PLAN-04` et `GOAL-03` avant lui.

## Le serveur ne se souvient de rien

Aucune session, aucun fil stocké. L'historique de conversation est **rendu par le client**
à chaque question et reparti avec la réponse. Trois conséquences, toutes voulues : deux
onglets ouverts ne se mélangent jamais, un rechargement repart proprement, et il n'existe
aucun fichier de discussions qui grossirait sans fin pour une valeur que trois lignes de
carnet couvrent mieux.

Ce qui doit durer est **extrait, proposé, validé** — et cela seul est écrit.
"""

from __future__ import annotations

import secrets as secrets_module
from datetime import date
from typing import TYPE_CHECKING

from app.core.dates import today_local
from app.core.exceptions import AiUnreadableError
from app.domains.ai.service import AiService
from app.domains.assistant import context, conversation
from app.domains.assistant.models import TOPICS, MemoryRow, normalise_topic
from app.domains.assistant.schemas import (
    MAX_HISTORY,
    AssistantView,
    ChatReply,
    ChatRequest,
    MemoryEntry,
    MemoryPayload,
)
from app.storage.csv_repo import CsvRepository, Row
from app.storage.errors import StorageNotFoundError
from app.storage.files import FileStore
from app.storage.paths import MEMORY

if TYPE_CHECKING:  # pragma: no cover - import de typage seulement
    from app.domains.planning.schemas import AdherenceView

#: Jetons laissés au modèle. Une réponse tient en quatre phrases et deux notes ; au-delà,
#: ce n'est pas la place qui manquait, c'est la consigne qui a été comprise autrement.
MAX_TOKENS = 900


def new_id() -> str:
    """Identifiant stable d'une note.

    Stable et non positionnel : l'écran corrige et retire des lignes, et une note citée
    dans une réponse doit rester retrouvable après une suppression.
    """
    return secrets_module.token_hex(6)


class AssistantService:
    """Conversation contextuelle et carnet de santé."""

    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._repo: CsvRepository[MemoryRow] = CsvRepository(store, MEMORY, MemoryRow)

    # ── Le carnet (`IA-11`) ───────────────────────────

    @staticmethod
    def _to_schema(row: Row[MemoryRow]) -> MemoryEntry:
        model = row.model
        return MemoryEntry(
            id=row.index,
            token=row.token,
            memory_id=model.id,
            created=model.created,
            topic=normalise_topic(model.topic),
            note=model.note,
            source=model.source or "manual",
        )

    async def _rows(self, *, fresh: bool = False) -> list[Row[MemoryRow]]:
        """Notes lisibles, les plus récentes d'abord.

        Une ligne sans identifiant ou sans note est écartée des vues — on ne saurait ni
        quoi afficher ni quelle ligne corriger — mais elle **survit dans le fichier** : on
        n'efface pas ce qu'on ne comprend pas.
        """
        rows = await self._repo.read_all(fresh=fresh)
        usable = [row for row in rows if row.model.id and row.model.note.strip()]
        return sorted(
            usable, key=lambda row: (row.model.created or date.min, row.index), reverse=True
        )

    async def view(self, *, today: date | None = None) -> AssistantView:
        return AssistantView(
            memories=[self._to_schema(row) for row in await self._rows()],
            topics=list(TOPICS),
            today=today or today_local(),
        )

    async def remember(
        self, payload: MemoryPayload, *, source: str = "manual", today: date | None = None
    ) -> MemoryEntry:
        """Écrit une note. C'est le premier moment où quoi que ce soit est écrit."""
        row = await self._repo.append(
            MemoryRow(
                id=new_id(),
                created=today or today_local(),
                topic=normalise_topic(payload.topic),
                note=payload.note.strip(),
                source=source,
            )
        )
        return self._to_schema(row)

    async def update(self, index: int, token: str, payload: MemoryPayload) -> MemoryEntry:
        """Corrige une note, sous garde anti-conflit (`STO-05`).

        L'identifiant et la provenance survivent à la correction : préciser « genou droit »
        ne transforme pas une note proposée par l'assistant en note écrite de toutes
        pièces. C'est la même règle qu'au L13 pour une séance déplacée, et qu'au L12 pour
        une estimation retouchée.
        """
        rows = await self._repo.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Cette note n'existe pas.")
        existing = rows[index].model

        row = await self._repo.replace_by_token(
            index,
            token,
            existing.model_copy(
                update={
                    "topic": normalise_topic(payload.topic),
                    "note": payload.note.strip(),
                }
            ),
        )
        return self._to_schema(row)

    async def forget(self, index: int, token: str) -> None:
        """Retire une note, sous garde anti-conflit (`STO-05`)."""
        await self._repo.delete_by_token(index, token)

    async def _known(self) -> list[tuple[str, str]]:
        """Le carnet sous la forme que la consigne attend."""
        return [(normalise_topic(row.model.topic), row.model.note) for row in await self._rows()]

    # ── La conversation (`IA-09`, `IA-10`) ────────────

    async def ask(
        self,
        ai: AiService,
        request: ChatRequest,
        *,
        adherence: AdherenceView,
        today: date | None = None,
    ) -> ChatReply:
        """Répond à une question. **N'écrit rien** (`IA-10`).

        La symétrie avec `GoalService.propose` et `PlanningService.propose` est voulue :
        cette méthode ne connaît pas l'écriture, `remember` ne connaît pas l'IA.
        """
        current = today or today_local()

        known = await self._known()
        facts = await context.build(self._store, adherence=adherence, today=current)
        memory = context.memory_lines(known)

        payload = await ai.ask_json(
            instruction=conversation.INSTRUCTION,
            prompt=conversation.build_prompt(
                question=request.question,
                context=facts,
                memory=memory,
                # Le client rend l'historique ; on le reborne quand même. Un client peut
                # envoyer ce qu'il veut, et la facture d'un appel se compte en jetons.
                history=[(item.role, item.content) for item in request.history[-MAX_HISTORY:]],
            ),
            max_tokens=MAX_TOKENS,
        )

        reply, proposed, _ = conversation.read_reply(
            payload,
            # La relecture écarte ce que le condensé disait déjà : une note qui figerait un
            # chiffre recalculé serait fausse le mois suivant.
            context=facts,
            known=[note for _, note in known],
        )

        if not reply:
            # La chaîne a fonctionné, la réponse ne contient rien d'affichable. `422` et
            # non `503` : rien n'est en panne, reformuler est la conduite utile.
            raise AiUnreadableError(
                "Le modèle n'a rien rendu d'exploitable. Reformule ta question — les "
                "chiffres, eux, restent lisibles sur les autres écrans."
            )

        return ChatReply(reply=reply, remember=proposed, context=facts)


__all__ = ["AssistantService", "new_id"]
