"""Assistant conversationnel, mémoire de santé et actions (`IA-09` → `IA-16`).

## `ask` sait écrire, désormais

Ce module s'ouvrait sur l'inverse : « **`ask` ne sait pas écrire**, et c'est la garantie du
lot ». La garantie a été levée sciemment, et trois autres la remplacent — elles ne sont pas
ici mais dans [`actions.py`](actions.py), qui est la seule autorité sur ce qui est
faisable :

* l'assistant ne peut rien que l'API ne permettrait, parce qu'il emprunte les schémas et
  les services des domaines, sans chemin d'écriture parallèle ;
* un ajout s'annule d'un appui, un changement ne s'écrit pas sans appui, et **le niveau
  vient de la table, jamais du modèle** ;
* aucune action ne fait échouer l'échange : un nom inventé rend un refus lisible, pas un
  `500` qui emporterait la réponse et la question avec lui.

Le carnet, lui, se remplit **tout seul** (`IA-10`). L'appui qui séparait la proposition de
l'écriture a disparu ; ce qui le remplace est une correction *après* plutôt qu'une
validation *avant* — la note est marquée `ia`, annoncée dans le fil, et se retire d'un
geste. Le compromis tient pour une mémoire et ne tiendrait pas pour une mesure : une note
fausse ne casse aucun chiffre, elle change ce que l'assistant croit savoir, et cela se lit.

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
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from app.core.dates import local_moment, now_local, today_local
from app.core.exceptions import AiUnreadableError, MetricError, ValidationFailedError
from app.domains.ai.service import AiService, DeltaReporter
from app.domains.app_settings.service import SettingsService
from app.domains.assistant import actions as catalogue
from app.domains.assistant import context, conversation, profile
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
    ProfilePayload,
    ProfileView,
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

#: Jetons laissés au modèle.
#:
#: 900 suffisaient à `{reply, remember}`. Le contrat en porte cinq champs depuis le L18, et
#: la moitié des modèles gratuits raisonnent à voix haute avant de répondre — une réponse
#: tronquée en plein raisonnement ne rend aucun JSON, donc rien du tout.
#:
#: **Monté de 1 600 au lot 7, et ce n'est pas de la prudence.** Tant que la consigne disait
#: « quatre phrases au plus », une réponse utile tenait sous 400 jetons et 1 600 était une
#: marge pour le raisonnement. La consigne autorise désormais un plan à se développer, et
#: `MAX_REPLY` va jusqu'à 4 000 caractères — soit près de 1 300 jetons pour le seul `reply`,
#: avant `remember`, `actions`, `need` et `title`. Laisser 1 600 aurait fait couper le
#: modèle en plein JSON exactement sur les réponses que le lot cherche à obtenir, et une
#: réponse coupée là ne rend pas un texte tronqué : elle ne rend **rien**.
MAX_TOKENS = 3000


#: Ce qu'un appelant fournit pour être tenu au courant : une coroutine par étape.
#:
#: Un alias plutôt qu'un `Protocol` : il n'y a qu'une forme, elle tient sur une ligne, et
#: la nommer suffit à ce que la signature de `ask` se lise.
StepReporter = Callable[[str], Awaitable[None]]


async def _step(reporter: StepReporter | None, message: str) -> None:
    """Annonce une étape, si quelqu'un écoute."""
    if reporter is not None:
        await reporter(message)


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


def _int_or_none(raw: str) -> int | None:
    """Année brute telle qu'elle est rangée. Illisible vaut absente, jamais une erreur."""
    try:
        return int(float(raw.strip()))
    except ValueError:
        return None


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
            resolved=model.resolved,
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

    async def update(
        self, index: int, token: str, payload: MemoryPayload, *, today: date | None = None
    ) -> MemoryEntry:
        """Corrige une note, sous garde anti-conflit (`STO-05`).

        L'identifiant et la provenance survivent à la correction : préciser « genou droit »
        ne transforme pas une note proposée par l'assistant en note écrite de toutes
        pièces. C'est la même règle qu'au L13 pour une séance déplacée, et qu'au L12 pour
        une estimation retouchée.

        **`resolved` absent ne touche à rien**, et ce n'est pas une commodité : corriger
        une faute de frappe dans « épaule gauche » ne doit pas réveiller une blessure
        guérie il y a trois mois. Seul un `True` ou un `False` explicite change le statut,
        et la date de résolution vient du serveur — un client ne date aucune donnée.
        """
        rows = await self._repo.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Cette note n'existe pas.")
        existing = rows[index].model

        changes: dict[str, object] = {
            "topic": normalise_topic(payload.topic),
            "note": payload.note.strip(),
        }
        if payload.resolved is True:
            # Résoudre deux fois ne repousse pas la date : c'est le jour où ça a cessé
            # d'être vrai qui compte, pas le jour du dernier appui sur le bouton.
            changes["resolved"] = existing.resolved or (today or today_local())
        elif payload.resolved is False:
            changes["resolved"] = None

        row = await self._repo.replace_by_token(index, token, existing.model_copy(update=changes))
        return self._to_schema(row)

    async def forget(self, index: int, token: str) -> None:
        """Retire une note, sous garde anti-conflit (`STO-05`)."""
        await self._repo.delete_by_token(index, token)

    # ── Le profil (`IA-10` a contrario : saisi, jamais proposé) ──

    async def profile(self, *, today: date | None = None) -> ProfileView:
        """Le profil, tel que l'écran le reçoit — âge et lignes de consigne compris."""
        settings = SettingsService(self._store)
        stored = await settings.all()
        return ProfileView(
            height_cm=profile.height_cm(stored.get(profile.HEIGHT, "")),
            birth_year=_int_or_none(stored.get(profile.BIRTH_YEAR, "")),
            training_days=stored.get(profile.TRAINING_DAYS, ""),
            equipment=stored.get(profile.EQUIPMENT, ""),
            preferences=stored.get(profile.PREFERENCES, ""),
            age=profile.age(stored.get(profile.BIRTH_YEAR, ""), today=today),
            # Publiées avec le profil pour la même raison que le condensé l'est avec la
            # réponse : ce qui part au modèle se vérifie à l'écran, il ne se déclare pas.
            lines=profile.lines(stored, today=today),
            token=await settings.token(),
        )

    async def set_profile(
        self, payload: ProfilePayload, token: str, *, today: date | None = None
    ) -> ProfileView:
        """Remplace le profil en entier, sous garde anti-conflit (`STO-05`).

        Remplacement et non fusion : vider un champ est un geste normal sur un formulaire
        qu'on voit en entier, et `update_keys` écrit les valeurs vides au lieu de les
        ignorer — c'est exactement pourquoi il existe.
        """
        await SettingsService(self._store).update_keys(
            {
                profile.HEIGHT: "" if payload.height_cm is None else str(payload.height_cm),
                profile.BIRTH_YEAR: "" if payload.birth_year is None else str(payload.birth_year),
                profile.TRAINING_DAYS: (payload.training_days or "").strip(),
                profile.EQUIPMENT: (payload.equipment or "").strip(),
                profile.PREFERENCES: (payload.preferences or "").strip(),
            },
            token,
        )
        return await self.profile(today=today)

    async def _known(self) -> list[context.MemoryNote]:
        """Le carnet sous la forme que la consigne attend, **dates comprises**.

        Elles étaient lues du fichier et jetées ici. Une contrainte notée en mars pesait donc
        autant qu'une note d'hier dans ce que le modèle en déduisait.
        """
        return [
            context.MemoryNote(
                topic=normalise_topic(row.model.topic),
                note=row.model.note,
                created=row.model.created,
                resolved=row.model.resolved,
            )
            for row in await self._rows()
        ]

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
                # `splitlines()` sur une chaîne vide rend `[]`, ce qui est exactement ce
                # qu'un message d'avant la colonne doit dire : rien, et non un contexte
                # reconstitué qui n'aurait jamais servi.
                context=message.model.context.splitlines(),
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
        entries: list[tuple[str, str, list[str]]],
        *,
        moment: datetime,
    ) -> None:
        """Ajoute des tours à un fil et repousse sa date d'activité.

        Chaque entrée est un triplet `(rôle, contenu, condensé)`. Le condensé n'accompagne
        que la réponse — une question n'en a pas — et il est **rangé**, pas recalculé : il
        dépend des chiffres du jour où elle a été posée.
        """
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
                    context="\n".join(lines),
                )
                for offset, (role, content, lines) in enumerate(entries)
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

    async def rename_thread(self, thread_id: str, title: str) -> ThreadSummary:
        """Renomme un fil (`C04-3`).

        Les titres sont écrits par le modèle à l'ouverture, et il se trompe : « Où j'en
        suis » pour une discussion qui a fini par porter sur une blessure. On ne pouvait
        que supprimer le fil, ce qui emportait la conversation avec le mauvais titre.

        **Le titre seul change.** Ni `updated` ni les messages : renommer n'est pas
        parler, et faire remonter le fil en tête de liste parce qu'on a corrigé son
        libellé rangerait l'historique dans un ordre qui ne veut plus rien dire.
        """
        cleaned = title.strip()[:MAX_TITLE]
        if not cleaned:
            raise ValidationFailedError("Une discussion a besoin d'un titre.")

        rows = await self._threads.read_all(fresh=True)
        for index, row in enumerate(rows):
            if row.model.id != thread_id:
                continue
            saved = await self._threads.replace_by_token(
                index, row.token, row.model.model_copy(update={"title": cleaned})
            )
            return ThreadSummary(
                thread_id=saved.model.id,
                title=saved.model.title,
                created=saved.model.created,
                updated=saved.model.updated,
                messages=len(
                    [
                        message
                        for message in await self._messages.read_all()
                        if message.model.thread_id == thread_id
                    ]
                ),
            )
        raise StorageNotFoundError("Cette discussion n'existe pas.")

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
        on_step: StepReporter | None = None,
        on_delta: DeltaReporter | None = None,
    ) -> ChatReply:
        """Répond à une question, dans un fil.

        ## `on_delta` : la réponse pendant qu'elle s'écrit

        Fourni, le texte de `reply` est annoncé au fil de l'eau. **Jamais au prix d'un
        effacement** : la première passe n'est diffusée que si le modèle a déclaré n'avoir
        besoin de rien — le contrat place `need` avant `reply` exactement pour que ce soit
        connu à temps. La seconde passe, finale par construction, se diffuse toujours.

        Ce qui est diffusé reste un **aperçu**. L'autorité est `ChatReply.reply`, relu et
        borné à `MAX_REPLY`, et c'est lui qui est stocké — d'où la même borne passée au
        lecteur de flux, pour que l'aperçu ne puisse pas dépasser ce qui sera conservé.

        ## `on_step` : dire ce qu'on fait pendant qu'on le fait

        Une réponse demande cinq à quinze secondes, et l'écran n'affichait que trois points
        pendant tout ce temps. Le rappel n'est pas un ornement : la durée varie du simple au
        triple selon qu'une seconde passe est nécessaire, et rien ne le disait.

        Le rapporteur est appelé **au moment où chaque étape commence**, jamais après ni
        d'avance. C'est ce qui distingue un compte rendu d'une animation : ce que l'écran
        affiche est arrivé. `None` — le cas de la route non diffusée — ne coûte rien.

        ## Ce qui n'a pas changé

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

        await _step(on_step, "je relis tes chiffres")

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
        # Les constantes, avant les chiffres : un plan qui suppose un rack quand il n'y en
        # a pas ne vaut rien, quels que soient les chiffres qui le précèdent.
        who = profile.lines(await SettingsService(self._store).all(), today=current)

        available = list(context.SLICES)

        def prompt_for(extra: list[str]) -> str:
            return conversation.build_prompt(
                question=request.question,
                context=facts + extra,
                memory=memory,
                profile=who,
                history=history,
                actions=catalogue.describe_catalogue(),
                slices=available,
                naming=opening,
            )

        async def consult(prompt: str, *, assured: bool) -> dict[str, Any]:
            """Une passe. Diffusée si quelqu'un écoute, ordinaire sinon.

            Les deux chemins portent les mêmes réglages — c'est la raison d'être de cette
            fermeture. Un `temperature` qui ne serait retiré que d'un côté ferait répondre
            la route diffusée autrement que l'autre, et le défaut ne se verrait qu'en
            comparant deux copies d'écran.
            """
            if on_delta is None:
                return await ai.ask_json(
                    instruction=conversation.INSTRUCTION,
                    prompt=prompt,
                    max_tokens=MAX_TOKENS,
                    # **Pas le tirage d'une extraction.** `0,1` est arrivé pour qu'une photo
                    # d'assiette rende deux fois le même chiffre ; appliqué à une
                    # conversation, il rend dix réponses quasi identiques à dix questions
                    # voisines. Le champ part d'ici plutôt que de prendre une autre valeur :
                    # sur la famille Claude 5 il est filtré de toute façon (voir
                    # `EXTRACTION_TEMPERATURE`), et inventer un `0,7` que personne n'a mesuré
                    # vaudrait moins que le défaut du fournisseur.
                    temperature=None,
                )
            return await ai.stream_json(
                instruction=conversation.INSTRUCTION,
                prompt=prompt,
                max_tokens=MAX_TOKENS,
                temperature=None,
                on_delta=on_delta,
                assured=assured,
                # L'aperçu ne peut pas dépasser ce qui sera conservé : `read_reply` borne à
                # `MAX_REPLY`, et un texte diffusé plus long serait raccourci sous les yeux
                # au moment où la réponse définitive arrive.
                limit=conversation.MAX_REPLY,
            )

        await _step(on_step, "je demande au modèle")
        # `assured=False` : cette passe n'est diffusable que si le modèle déclare lui-même
        # n'avoir besoin d'aucune tranche, ce que le contrat lui fait écrire **avant** sa
        # réponse. Voir `ReplyStream` et §7.1 du plan.
        payload = await consult(prompt_for([]), assured=False)

        # ── La seconde passe, et il n'y en a jamais de troisième (`IA-16`)
        #
        # Supprimer le repas de midi demande son identifiant ; ajouter une série demande
        # l'exercice au catalogue. Un agent classique boucle — lire, réfléchir, écrire,
        # relire — et sur des modèles gratuits cela veut dire une latence imprévisible, un
        # coût imprévisible, et un écran qui tourne sans qu'on sache pourquoi.
        #
        # Le plafond est donc **dans la forme du code** et non dans la consigne : deux
        # appels, parce qu'il y a deux appels écrits. Aucune borne à respecter, aucune
        # récursion à surveiller.
        need = conversation.read_need(payload, available=available)
        if need:
            # La seconde passe est **la** raison pour laquelle une réponse peut durer trois
            # fois plus longtemps qu'une autre. La nommer, avec ce qui manquait, remplace
            # une attente inexpliquée par une attente qu'on comprend.
            await _step(on_step, f"il me manque {', '.join(need)} — je relis")
            # `assured=True` : il n'y a pas de troisième passe, donc celle-ci est finale
            # quoi qu'elle réponde. C'est le plafond de `IA-16` qui rend la preuve inutile
            # ici — et c'est aussi ce qui fait que la question la plus lente de toutes est
            # celle qui se diffuse à coup sûr.
            payload = await consult(
                prompt_for(await context.slices(self._store, need, today=current)),
                assured=True,
            )

        wanted = conversation.read_actions(payload)
        if wanted:
            # Ce n'est pas la même attente : ici le modèle a fini, et c'est le stockage
            # qu'on sollicite. Le dire distingue « le modèle réfléchit » de « on écrit »,
            # et la seconde n'a pas le même remède quand elle traîne.
            await _step(on_step, "j’écris ce qu’il a décidé")
        reports = await self._run_actions(wanted)

        reply, proposed, _ = conversation.read_reply(
            payload,
            # La relecture écarte ce que le condensé disait déjà : une note qui figerait un
            # chiffre recalculé serait fausse le mois suivant.
            context=facts,
            # Les notes seules : `_echoes` compare des phrases, pas des dates. Une note
            # résolue reste dans la comparaison — la reproposer serait encore une redite.
            known=[entry.note for entry in known],
        )

        if not reply:
            # La chaîne a fonctionné, la réponse ne contient rien d'affichable. `422` et
            # non `503` : rien n'est en panne, reformuler est la conduite utile.
            raise AiUnreadableError(
                "Le modèle n'a rien rendu d'exploitable. Reformule ta question — les "
                "chiffres, eux, restent lisibles sur les autres écrans."
            )

        # Le carnet se remplit tout seul (`IA-10`).
        #
        # Rien ne valide plus avant l'écriture. Ce qui remplace la validation : la note
        # est marquée `ia`, annoncée dans le fil au moment où elle est prise, et se
        # corrige ou se retire depuis le carnet — qui existe déjà. Une note fausse ne
        # casse aucun chiffre : elle change ce que l'assistant croit savoir, et cela se
        # lit. C'est ce qui rend le compromis tenable ici, et intenable pour une mesure.
        remembered = [
            await self.remember(
                MemoryPayload(topic=note.topic, note=note.note), source="ai", today=current
            )
            for note in proposed
        ]

        if opening:
            title = conversation.read_title(payload, fallback=title)
            thread_id = await self._open_thread(title, moment=moment)
        if thread_id is None:  # pragma: no cover - `opening` vient de l'ouvrir
            raise StorageNotFoundError("Cette discussion n'existe pas.")
        await self._append_messages(
            thread_id,
            [("user", request.question, []), ("assistant", reply, facts)],
            moment=moment,
        )

        return ChatReply(
            thread_id=thread_id,
            title=title,
            reply=reply,
            remember=remembered,
            actions=reports,
            context=facts,
        )


__all__ = ["AssistantService", "new_id"]
