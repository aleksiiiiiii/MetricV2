"""Assistant conversationnel et mémoire de santé (`IA-09` → `IA-12`).

Deux moitiés, et leur séparation est la garantie du lot : **`ask` ne sait pas écrire**, et
le carnet ne sait pas interroger un modèle. Entre les deux, un écran et un appui — c'est là
que vit `IA-10`, comme `NUT-04`, `PLAN-04` et `GOAL-03` avant lui.

## Le serveur tient les fils

Il ne s'en souvenait pas : l'écran rendait l'historique à chaque question et le perdait au
rechargement. C'était documenté comme voulu, avec trois bénéfices — et deux d'entre eux
tiennent toujours dès lors qu'un fil porte une identité : deux onglets sur deux fils ne se
mélangent pas, et un rechargement **rouvre** le fil courant au lieu de le perdre, ce qui
est mieux. Le troisième, « aucun fichier ne grossit sans fin », est le prix assumé de
pouvoir revenir sur une discussion d'il y a trois mois.

Conséquence de sécurité, et elle vaut d'être dite : **l'historique n'est plus rendu par le
client**. Il pouvait envoyer le passé qu'il voulait, ce qui était sans portée tant que rien
ne s'écrivait ; ça n'en est plus une dès lors qu'une réponse peut agir sur les données.
"""

from __future__ import annotations

import secrets as secrets_module
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from app.core.dates import local_moment, now_local, today_local
from app.core.exceptions import AiUnreadableError, MetricError
from app.domains.ai.service import AiService
from app.domains.assistant import actions as catalogue
from app.domains.assistant import context, conversation
from app.domains.assistant.models import (
    MAX_CONTENT,
    MAX_TITLE,
    TOPICS,
    MemoryRow,
    MessageRow,
    ThreadRow,
    normalise_topic,
)
from app.domains.assistant.schemas import (
    MAX_HISTORY,
    ActionReport,
    AssistantView,
    ChatReply,
    ChatRequest,
    ConfirmRequest,
    MemoryEntry,
    MemoryPayload,
    ProposedAction,
    ThreadDetail,
    ThreadList,
    ThreadMessage,
    ThreadSummary,
    UndoRef,
)
from app.storage.csv_repo import CsvRepository, Row
from app.storage.errors import StorageNotFoundError
from app.storage.files import FileStore
from app.storage.paths import MEMORY, MESSAGES, THREADS

if TYPE_CHECKING:  # pragma: no cover - import de typage seulement
    from app.domains.planning.schemas import AdherenceView

#: Jetons laissés au modèle. Une réponse tient en quatre phrases et deux notes ; au-delà,
#: ce n'est pas la place qui manquait, c'est la consigne qui a été comprise autrement.
MAX_TOKENS = 900


def _sortable(summary: ThreadSummary) -> tuple[bool, datetime]:
    """Clé de tri d'un fil, robuste à ce qu'un tableur peut écrire.

    Le booléen sépare d'abord les fils datés de ceux qui ne le sont pas, ce qui évite
    d'inventer une date à ces derniers pour les ranger.
    """
    if summary.updated is None:
        return (False, datetime.min.replace(tzinfo=UTC))
    return (True, local_moment(summary.updated))


def _title_from(question: str) -> str:
    """Titre d'un fil, tiré de la question qui l'ouvre.

    Coupé sur un mot entier : « Pourquoi je stagne au dévelop… » se lit mal dans une
    liste, et un titre est ce sur quoi on retrouve un fil trois mois plus tard.

    C'est un repli, pas l'ambition : dès que le contrat JSON portera un `title`, c'est le
    modèle qui nommera le fil — il a lu la question *et* sa réponse, donc il sait de quoi
    la discussion a parlé, ce que la première phrase ne dit pas toujours.
    """
    cleaned = " ".join(question.split())
    if len(cleaned) <= MAX_TITLE:
        return cleaned
    coupe = cleaned[:MAX_TITLE].rsplit(" ", 1)[0]
    return f"{coupe or cleaned[:MAX_TITLE]}…"


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
        self._threads: CsvRepository[ThreadRow] = CsvRepository(store, THREADS, ThreadRow)
        self._messages: CsvRepository[MessageRow] = CsvRepository(store, MESSAGES, MessageRow)

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

    # ── Les fils (`IA-13`) ────────────────────────────

    async def threads(self) -> ThreadList:
        """Les fils, du plus récemment actif au plus ancien.

        Sans leurs messages : la liste s'ouvre en une lecture de `threads.csv`, et le
        contenu ne se charge qu'à l'ouverture d'un fil.
        """
        rows = await self._threads.read_all()
        counts: dict[str, int] = {}
        for message in await self._messages.read_all():
            counts[message.model.thread_id] = counts.get(message.model.thread_id, 0) + 1

        summaries = [
            ThreadSummary(
                thread_id=row.model.id,
                title=row.model.title,
                created=row.model.created,
                updated=row.model.updated,
                messages=counts.get(row.model.id, 0),
            )
            for row in rows
            if row.model.id
        ]
        # Un fil sans horodatage descend en bas de la liste au lieu de faire échouer le
        # tri, et un horodatage retapé à la main sans son décalage est situé plutôt que
        # comparé de travers — comparer un instant naïf à un instant situé lève.
        summaries.sort(key=_sortable, reverse=True)
        return ThreadList(threads=summaries)

    async def thread(self, thread_id: str) -> ThreadDetail:
        """Un fil et tous ses messages, dans l'ordre où ils ont été écrits."""
        row = await self._find_thread(thread_id)
        messages = [
            ThreadMessage(
                seq=message.model.seq,
                role="assistant" if message.model.role == "assistant" else "user",
                content=message.model.content,
                created=message.model.created,
            )
            for message in await self._messages.read_all()
            if message.model.thread_id == thread_id
        ]
        messages.sort(key=lambda item: item.seq)
        return ThreadDetail(
            thread_id=row.id,
            title=row.title,
            created=row.created,
            updated=row.updated,
            messages=messages,
        )

    async def forget_thread(self, thread_id: str) -> None:
        """Supprime un fil et ses messages.

        Les messages partent **d'abord** : si l'écriture échoue entre les deux, il reste un
        fil vide — visible et resupprimable — plutôt que des messages orphelins que plus
        aucun écran ne montre et que plus personne ne peut retirer.
        """
        await self._find_thread(thread_id)
        await self._messages.remove_where(lambda row: row.thread_id == thread_id)
        await self._threads.remove_where(lambda row: row.id == thread_id)

    async def forget_all_threads(self) -> None:
        """Vide toutes les discussions. Le carnet, lui, n'est pas touché."""
        await self._messages.overwrite([])
        await self._threads.overwrite([])

    async def _find_thread(self, thread_id: str) -> ThreadRow:
        for row in await self._threads.read_all():
            if row.model.id == thread_id:
                return row.model
        raise StorageNotFoundError("Cette discussion n'existe pas.")

    async def _append_messages(
        self,
        thread_id: str,
        entries: list[tuple[str, str]],
        *,
        moment: datetime,
    ) -> None:
        """Ajoute des tours à un fil et repousse sa date d'activité."""
        existing = [
            row.model.seq
            for row in await self._messages.read_all()
            if row.model.thread_id == thread_id
        ]
        next_seq = max(existing, default=-1) + 1

        await self._messages.extend(
            [
                MessageRow(
                    thread_id=thread_id,
                    seq=next_seq + offset,
                    role=role,
                    content=content[:MAX_CONTENT],
                    created=moment,
                )
                for offset, (role, content) in enumerate(entries)
            ]
        )

        rows = await self._threads.read_all(fresh=True)
        for index, row in enumerate(rows):
            if row.model.id == thread_id:
                await self._repo_replace_thread(index, row.token, row.model, moment)
                return

    async def _repo_replace_thread(
        self, index: int, token: str, existing: ThreadRow, moment: datetime
    ) -> None:
        await self._threads.replace_by_token(
            index, token, existing.model_copy(update={"updated": moment})
        )

    async def _open_thread(self, title: str, *, moment: datetime) -> str:
        """Ouvre un fil et rend son identifiant."""
        thread_id = new_id()
        await self._threads.append(
            ThreadRow(
                id=thread_id,
                created=moment,
                updated=moment,
                title=title.strip()[:MAX_TITLE] or "Sans titre",
            )
        )
        return thread_id

    async def _history(self, thread_id: str) -> list[tuple[str, str]]:
        """Les derniers tours du fil, pour la consigne."""
        rows = [
            row.model for row in await self._messages.read_all() if row.model.thread_id == thread_id
        ]
        rows.sort(key=lambda row: row.seq)
        return [(row.role, row.content) for row in rows[-MAX_HISTORY:]]

    # ── Les actions (`IA-15`) ─────────────────────────

    async def _run_actions(self, proposed: list[ProposedAction]) -> list[ActionReport]:
        """Exécute ce qui s'exécute, met le reste en attente.

        **Aucune action ne fait échouer l'échange.** Un nom inventé, des arguments
        incomplets, un domaine qui refuse : chacun rend un rapport lisible, et la réponse
        reste affichée. L'inverse — un `500` parce que le modèle a mal nommé une action —
        perdrait la réponse *et* la question, pour un tour où l'assistant a peut-être
        surtout bien répondu.

        Le niveau vient de la table et **jamais du modèle** : il ne peut pas demander à ce
        qu'une suppression passe pour un ajout.
        """
        reports: list[ActionReport] = []

        for item in proposed:
            checked = catalogue.validate(item.name, item.args)
            if isinstance(checked, str):
                reports.append(
                    ActionReport(
                        name=item.name,
                        level="add",
                        status="refused",
                        summary=checked,
                        args=item.args,
                    )
                )
                continue

            spec, payload = checked
            if spec.level is catalogue.Level.CHANGE:
                # Rien n'est écrit. L'écran montrera ce que ça changerait, et un appui
                # rappellera `confirm` avec les mêmes arguments.
                reports.append(
                    ActionReport(
                        name=spec.name,
                        level="change",
                        status="pending",
                        summary=spec.label.capitalize(),
                        args=item.args,
                    )
                )
                continue

            reports.append(await self._perform(spec, payload, item.args))

        return reports

    async def _perform(
        self, spec: catalogue.ActionSpec, payload: Any, args: dict[str, Any]
    ) -> ActionReport:
        """Lance une action et rend son rapport, quoi qu'il advienne."""
        try:
            outcome = await spec.run(self._store, payload)
        except MetricError as error:
            # Le domaine a dit non — borne de vraisemblance, conflit de jeton, ligne
            # absente. Son message est déjà en français et destiné à être lu (`API-06`).
            return ActionReport(
                name=spec.name,
                level=spec.level.value,
                status="refused",
                summary=str(error),
                args=args,
            )

        return ActionReport(
            name=spec.name,
            level=spec.level.value,
            status="done",
            summary=outcome.summary,
            args=args,
            undo=(
                UndoRef(
                    domain=outcome.undo.domain,
                    row_id=outcome.undo.row_id,
                    token=outcome.undo.token,
                )
                if outcome.undo is not None
                else None
            ),
        )

    async def confirm(self, request: ConfirmRequest) -> ActionReport:
        """Exécute une action restée en attente.

        Elle est **revalidée entièrement** : le client renvoie un nom et des arguments, et
        ils repassent par la même porte que ceux du modèle. Rien n'est retenu entre la
        proposition et la confirmation, donc rien ne peut être confirmé qui n'aurait pas
        pu être demandé.
        """
        checked = catalogue.validate(request.name, request.args)
        if isinstance(checked, str):
            return ActionReport(
                name=request.name,
                level="change",
                status="refused",
                summary=checked,
                args=request.args,
            )

        spec, payload = checked
        return await self._perform(spec, payload, request.args)

    # ── La conversation (`IA-09`, `IA-10`) ────────────

    async def ask(
        self,
        ai: AiService,
        request: ChatRequest,
        *,
        adherence: AdherenceView,
        today: date | None = None,
    ) -> ChatReply:
        """Répond à une question, dans un fil.

        **L'historique vient du fil, pas du client.** C'était l'inverse : l'écran renvoyait
        le passé à chaque question. Sans conséquence tant que rien ne s'écrivait — mais un
        client peut envoyer le passé qu'il veut, et une réponse qui agit sur les données ne
        doit pas se décider sur un historique fourni par l'appelant.

        Le fil est écrit **après** la réponse, les deux tours ensemble. Une question sans
        réponse — modèle injoignable, quota atteint — ne laisse donc pas de fil orphelin
        qu'on rouvrirait sur un message sans suite.
        """
        current = today or today_local()
        moment = now_local()

        thread_id = request.thread_id
        opening = thread_id is None
        history: list[tuple[str, str]] = []
        if thread_id is None:
            title = _title_from(request.question)
        else:
            existing = await self._find_thread(thread_id)
            title = existing.title
            history = await self._history(thread_id)

        known = await self._known()
        facts = await context.build(self._store, adherence=adherence, today=current)
        memory = context.memory_lines(known)

        payload = await ai.ask_json(
            instruction=conversation.INSTRUCTION,
            prompt=conversation.build_prompt(
                question=request.question,
                context=facts,
                memory=memory,
                history=history,
                actions=catalogue.describe_catalogue(),
                slices=[],
                naming=opening,
            ),
            max_tokens=MAX_TOKENS,
        )

        reports = await self._run_actions(conversation.read_actions(payload))

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

        if opening:
            title = conversation.read_title(payload, fallback=title)
            thread_id = await self._open_thread(title, moment=moment)
        if thread_id is None:  # pragma: no cover - `opening` vient de l'ouvrir
            raise StorageNotFoundError("Cette discussion n'existe pas.")
        await self._append_messages(
            thread_id,
            [("user", request.question), ("assistant", reply)],
            moment=moment,
        )

        return ChatReply(
            thread_id=thread_id,
            title=title,
            reply=reply,
            remember=proposed,
            actions=reports,
            context=facts,
        )


__all__ = ["AssistantService", "new_id"]
