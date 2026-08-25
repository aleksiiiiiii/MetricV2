"""La lecture du jour : lecture, génération, semis du fil.

Ce service ne calcule **aucun chiffre**. Il assemble trois choses qui existent déjà —
le condensé factuel de l'assistant, la couche IA, le fil de discussion — et range le
résultat dans un fichier. C'est le même partage que `WeeklyInsightService`, dont il
recopie le découpage à l'identique.

## Ce qui est fourni, et pourquoi

`adherence` arrive **construit par l'appelant** — le routeur ou l'ordonnanceur —, jamais
recalculé ici. `PLAN-06` en détient l'unique implémentation, et deux taux de respect
divergents pour la même semaine sont exactement ce que le §2 du document d'état interdit.
C'est aussi ce qui évite un cycle d'imports : `planning/service.py` lit l'objectif actif,
qui lit le registre des métriques des agrégats, et la flèche ne va que dans un sens.

## Pourquoi la génération écrit sans second appui

Partout ailleurs — un objectif, un bilan, un repas estimé, un planning proposé — le modèle
rend et **un appui écrit**. La règle protège les *données de l'utilisateur* : ses pesées,
ses séances, ses objectifs, tout ce qui se relira dans dix ans comme un fait.

Une lecture du jour n'en est pas une. C'est un **cache daté**, du même genre que
`notifications/sent.csv` : elle ne prétend à aucune vérité sur le passé, elle porte une
date, elle se remplace, et rien d'autre ne s'y rattache. Lui demander une validation
aurait ajouté un geste quotidien sur l'écran qu'on ouvre le plus, pour garder une phrase
que personne ne relit.

Ce qu'elle **ne** fait pas, en revanche : elle n'écrit rien dans les autres domaines. Une
lecture qui noterait un verre d'eau au passage serait une écriture non validée, et là la
règle vaudrait pleinement.

## Une journée, une ligne

`day` est la clé naturelle du fichier, comme `week` pour le bilan. Régénérer remplace la
ligne du jour plutôt que d'en ajouter une seconde, et **efface son fil** : le fil semé
porte le message d'avant, la nouvelle lecture en dit un autre, et les rattacher ferait
répondre l'utilisateur à un texte que l'écran n'affiche plus. L'ancien fil survit dans les
discussions avec son propre contenu, ce qui est la lecture honnête.
"""

from __future__ import annotations

from datetime import date, datetime

from app.core.dates import now_local
from app.core.exceptions import AiUnreadableError
from app.domains.ai.service import AiService
from app.domains.assistant import context as assistant_context
from app.domains.assistant.service import AssistantService
from app.domains.brief import compose
from app.domains.brief.models import MAX_BASIS, BriefRow, current_slot, normalise_slot
from app.domains.brief.schemas import BriefThread, BriefView
from app.storage.csv_repo import CsvRepository, Row
from app.storage.errors import StorageNotFoundError
from app.storage.files import FileStore
from app.storage.paths import BRIEF

#: Jetons laissés au modèle. Un paragraphe de quatre phrases tient très en deçà ; au-delà,
#: ce n'est pas de la place qui manquait, c'est la consigne qui a été comprise autrement.
MAX_TOKENS = 400

#: Titre du fil semé. Fixe et non écrit par le modèle, contrairement aux autres fils : on
#: sait déjà de quoi il parle, et « Lecture du 19/08 » se retrouve dans la liste mieux
#: qu'une reformulation qui varierait d'un jour à l'autre.
THREAD_TITLE = "Lecture du {day:%d/%m}"


class BriefService:
    """La lecture du jour, dans son fichier."""

    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._repo: CsvRepository[BriefRow] = CsvRepository(store, BRIEF, BriefRow)

    # ── Lecture ───────────────────────────────────────

    async def _row_for(self, day: date, slot: str, *, fresh: bool = False) -> Row[BriefRow] | None:
        """La ligne d'un jour **et d'un créneau**, ou `None`.

        Une ligne sans date ou sans message est écartée : on ne saurait ni quel jour elle
        commente, ni quoi afficher. Elle **survit dans le fichier** — on n'efface pas ce
        qu'on ne comprend pas.

        Le créneau passe par `normalise_slot` : une cellule vide vaut `matin`, ce qui rend
        les lectures écrites avant ce lot lisibles à leur juste place plutôt qu'invisibles.
        """
        wanted = normalise_slot(slot)
        rows = await self._repo.read_all(fresh=fresh)
        for row in rows:
            same = row.model.day == day and normalise_slot(row.model.slot) == wanted
            if same and row.model.message:
                return row
        return None

    @staticmethod
    def _to_schema(day: date, slot: str, row: Row[BriefRow] | None) -> BriefView:
        if row is None:
            return BriefView(day=day, slot=normalise_slot(slot), state="absent")
        model = row.model
        return BriefView(
            day=day,
            slot=normalise_slot(slot),
            state="ready",
            message=model.message,
            basis=[line for line in model.basis.split("\n") if line],
            thread_id=model.thread_id or None,
        )

    async def view(
        self, *, today: date | None = None, slot: str | None = None, now: datetime | None = None
    ) -> BriefView:
        """La lecture d'un créneau si elle a été écrite, `absent` sinon. **N'écrit rien.**

        Sans `slot`, c'est **le créneau en cours** qui est rendu — celui dont l'heure est
        passée. L'écran ne le calcule pas : il n'a ni l'horloge ni le fuseau du serveur, et
        deux idées de « il est midi » finiraient par diverger (`HEAT-32`).
        """
        moment = now or now_local()
        day = today or moment.date()
        wanted = slot or current_slot(moment)
        return self._to_schema(day, wanted, await self._row_for(day, wanted))

    # ── Génération ────────────────────────────────────

    async def generate(
        self,
        ai: AiService,
        *,
        adherence: object,
        today: date | None = None,
        now: datetime | None = None,
        slot: str | None = None,
    ) -> BriefView:
        """Demande la lecture d'un créneau et la range. Une journée et un créneau, une ligne.

        `adherence` est typé `object` et repassé tel quel : ce service n'en lit aucun
        champ, il ne fait que le transmettre à `context.build`. L'annoter précisément
        obligerait à importer le domaine Planning, que ce module n'a aucune raison de
        connaître — c'est le même arbitrage que le `TYPE_CHECKING` de `goals/service.py`,
        résolu ici dans l'autre sens parce qu'aucun champ n'est touché.
        """
        moment = now or now_local()
        day = today or moment.date()
        wanted = normalise_slot(slot or current_slot(moment))

        lines = await assistant_context.build(
            self._store,
            adherence=adherence,  # type: ignore[arg-type]
            today=day,
            now=moment,
        )

        payload = await ai.ask_json(
            instruction=compose.INSTRUCTION,
            prompt=compose.build_prompt(day=day, context=lines, slot=wanted),
            max_tokens=MAX_TOKENS,
        )
        message = compose.read_message(payload)
        if not message:
            raise AiUnreadableError(
                "Le modèle n'a rien rendu de lisible pour ce moment de la journée. "
                "Réessaie — les chiffres restent lisibles sur les autres écrans."
            )

        item = BriefRow(
            day=day,
            slot=wanted,
            created=moment,
            message=message,
            basis="\n".join(lines)[:MAX_BASIS],
            # Régénérer casse le lien vers l'ancien fil : voir l'en-tête du module.
            thread_id="",
            source="ai",
        )

        rows = await self._repo.read_all(fresh=True)
        existing = next(
            (
                (index, row)
                for index, row in enumerate(rows)
                if row.model.day == day and normalise_slot(row.model.slot) == wanted
            ),
            None,
        )
        if existing is None:
            saved = await self._repo.append(item)
        else:
            index, row = existing
            saved = await self._repo.replace_by_token(index, row.token, item)
        return self._to_schema(day, wanted, saved)

    # ── Le fil dans lequel on répond ──────────────────

    async def thread(self, *, today: date | None = None, slot: str | None = None) -> BriefThread:
        """Le fil d'une lecture, **créé au premier appui seulement**.

        Semer le fil à la génération remplirait « Discussions » d'une entrée quotidienne
        que personne n'a ouverte. Il naît donc quand on décide de répondre, et la colonne
        `thread_id` dit du même coup si la lecture a servi.

        Rappelé, il rend le fil déjà ouvert : deux appuis sur la même carte continuent la
        même conversation plutôt que d'en ouvrir deux.

        **Un fil par créneau**, et non un par jour : répondre à la lecture du soir dans le
        fil ouvert ce matin ferait continuer une conversation dont le premier message ne
        s'affiche plus sur la carte.
        """
        moment = now_local()
        day = today or moment.date()
        wanted = normalise_slot(slot or current_slot(moment))

        row = await self._row_for(day, wanted, fresh=True)
        if row is None:
            raise StorageNotFoundError("Aucune lecture n'a été écrite pour ce moment.")
        if row.model.thread_id:
            return BriefThread(thread_id=row.model.thread_id)

        thread_id = await AssistantService(self._store).seed_thread(
            title=THREAD_TITLE.format(day=day),
            message=row.model.message,
            context_lines=[line for line in row.model.basis.split("\n") if line],
            moment=moment,
        )

        # La position est relue **après** l'écriture du fil : celle-ci ne touche pas à ce
        # fichier-ci, mais la relire coûte une lecture et évite d'écrire à l'aveugle sur
        # un index vieilli d'un appel réseau.
        rows = await self._repo.read_all(fresh=True)
        for index, current in enumerate(rows):
            if current.model.day == day and normalise_slot(current.model.slot) == wanted:
                await self._repo.replace_by_token(
                    index, current.token, current.model.model_copy(update={"thread_id": thread_id})
                )
                break
        return BriefThread(thread_id=thread_id)


__all__ = ["MAX_TOKENS", "THREAD_TITLE", "BriefService"]
