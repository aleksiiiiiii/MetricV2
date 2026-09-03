"""Objectifs et bilans hebdomadaires (`GOAL-01` → `GOAL-06`, `IA-08`).

Ce module lit **beaucoup** de fichiers et n'en écrit que deux. Il ne possède ni le poids,
ni les séances, ni les repas : il les regarde là où ils sont écrits, à travers le registre
`METRICS`, qui est le seul endroit du projet où « séances par semaine » a une définition.

Trois séparations tiennent les garanties du lot :

* `propose` **ne sait pas écrire** et `adopt` **ne sait pas interroger un modèle**. Entre
  les deux, un écran et un appui — c'est là que vit `GOAL-03`, comme `PLAN-04` avant lui.
* Le calcul de progression vit dans `progress.py`, qui ne lit rien. Chaque cas se vérifie
  sur cinq valeurs fixes plutôt qu'en montant une application.
* L'écart plan / réalisé n'est **jamais recalculé ici**. `WeeklyInsightService.generate`
  le reçoit tout fait : `PLAN-06` en détient l'unique implémentation, et deux taux de
  respect divergents pour la même semaine seraient exactement ce que le §2 du document
  d'état interdit.

## Sens des dépendances

Ce module ne connaît **pas** le service du domaine Planning, et c'est délibéré :
`planning/service.py` a besoin de lui pour remplir l'objectif d'une proposition
(`PLAN-03`), et les deux ne peuvent pas s'importer l'un l'autre. La flèche va donc dans un
seul sens — planning → goals — et le bilan hebdomadaire reçoit d'en haut, par son routeur,
ce qu'il aurait sinon demandé en bas.
"""

from __future__ import annotations

import secrets as secrets_module
from datetime import date, timedelta
from typing import TYPE_CHECKING

from app.core.dates import today_local, week_start
from app.core.exceptions import AiUnreadableError, ValidationFailedError
from app.domains.aggregates.metrics import METRICS
from app.domains.ai.service import AiService
from app.domains.app_settings.service import SettingsService
from app.domains.goals import weekly
from app.domains.goals.generation import (
    INSTRUCTION,
    THIN_SESSIONS,
    build_prompt,
    read_goal,
)
from app.domains.goals.metrics import GOAL_METRICS, granularity_of, label_of, unit_of
from app.domains.goals.models import (
    OUTCOME_ABANDONED,
    OUTCOME_LABELS,
    OUTCOME_PARTIAL,
    OUTCOME_REACHED,
    STATUS_ACTIVE,
    STATUS_CLOSED,
    GoalRow,
    WeeklyRow,
    normalise_outcome,
    normalise_status,
)
from app.domains.goals.progress import (
    basis,
    current_value,
    fr,
    latest,
    ratio,
    summary,
    window,
)
from app.domains.goals.schemas import (
    DEADLINE_MAX_WEEKS,
    DEADLINE_MIN_WEEKS,
    ActiveGoal,
    GoalEntry,
    GoalPayload,
    GoalProgress,
    GoalProposal,
    GoalsView,
    ProposalRequest,
    WeeklyEntry,
    WeeklyPayload,
    WeeklyReview,
    WeeklyView,
)
from app.domains.supplements.service import SupplementService
from app.storage.csv_repo import CsvRepository, Row
from app.storage.errors import StorageConflictError, StorageNotFoundError
from app.storage.files import FileStore
from app.storage.paths import (
    CIRCUIT_SESSIONS,
    GOALS,
    HYDRATION_LOG,
    MEALS,
    RUNS,
    SETTINGS,
    SUPPLEMENT_SCHEDULE,
    WEEKLY_INSIGHTS,
    WEIGHT,
)

if TYPE_CHECKING:  # pragma: no cover - import de typage seulement
    # Sous `TYPE_CHECKING` et non en clair, et ce n'est pas une commodité de style.
    #
    # Importer quoi que ce soit de `app.domains.planning` fait exécuter le `__init__` du
    # paquet, donc son routeur, donc `planning/service.py` — qui a besoin de **ce**
    # module pour l'objectif actif (`PLAN-03`). En clair, l'import échouerait sur un
    # module à moitié construit, et l'ordre de chargement de `app/domains/api.py`
    # deviendrait une question à laquelle personne ne veut avoir à répondre.
    #
    # `AdherenceView` n'est ici qu'une annotation — le taux de respect arrive **construit
    # par le routeur**, jamais recalculé (`PLAN-06`). Rien n'en a besoin à l'exécution.
    from app.domains.planning.schemas import AdherenceView

#: Fichiers ouverts pour bâtir un condensé. Préchargés ensemble : à ~180 ms l'aller-retour
#: mesuré sur l'instance réelle, les lire l'un après l'autre coûterait plus d'une seconde
#: pour une requête qui n'affiche qu'une carte.
CONTEXT_FILES = (
    WEIGHT,
    RUNS,
    CIRCUIT_SESSIONS,
    MEALS,
    HYDRATION_LOG,
    SUPPLEMENT_SCHEDULE,
    SETTINGS,
    GOALS,
)

#: Profondeur d'historique du poids résumée au modèle, en jours.
WEIGHT_RANGE_DAYS = 90

#: Semaines rappelées au bilan hebdomadaire pour qu'il ait de quoi comparer.
INSIGHT_HISTORY_WEEKS = 4

#: Jetons laissés au modèle. Un objectif tient en cinq champs, un bilan en six lignes :
#: au-delà, ce n'est pas de la place qui manquait, c'est la consigne qui a été comprise
#: autrement.
MAX_TOKENS = 700


def new_id() -> str:
    """Identifiant stable d'un objectif.

    Stable et non positionnel : l'historique se relit après des suppressions de lignes, et
    la génération suivante cite les objectifs passés (`GOAL-06`).
    """
    return secrets_module.token_hex(6)


async def load_points(store: FileStore, metric_key: str) -> list[tuple[date, float]]:
    """Série d'une métrique, chargée par le registre qui la détient.

    Passer par `METRICS` plutôt que par le service d'origine n'est pas un détour : c'est
    ce qui garantit qu'un objectif de « séances par semaine » et la courbe du même nom sur
    le tableau de bord comptent la même chose.
    """
    metric = METRICS.get(metric_key)
    if metric is None:  # pragma: no cover - les appelants filtrent sur `GOAL_METRICS`
        return []
    return list(await metric.load(store, None))


class GoalService:
    """Objectifs : lecture, progression, proposition, adoption, clôture."""

    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._repo: CsvRepository[GoalRow] = CsvRepository(store, GOALS, GoalRow)
        self._settings = SettingsService(store)

    # ── Lecture du fichier ────────────────────────────

    @staticmethod
    def _to_schema(row: Row[GoalRow]) -> GoalEntry:
        model = row.model
        assert model.deadline is not None  # garanti par le filtre de `_rows`
        outcome = normalise_outcome(model.outcome)
        return GoalEntry(
            id=row.index,
            token=row.token,
            goal_id=model.id,
            created=model.created,
            title=model.title or label_of(model.metric),
            metric=model.metric,
            target=model.target,
            unit=model.unit or unit_of(model.metric),
            deadline=model.deadline,
            rationale=model.rationale,
            source=model.source or "ai",
            status=normalise_status(model.status),
            outcome=outcome,
            outcome_label=OUTCOME_LABELS.get(outcome, ""),
        )

    async def _rows(self, *, fresh: bool = False) -> list[Row[GoalRow]]:
        """Lignes exploitables, les plus récentes d'abord.

        Une ligne sans identifiant, sans échéance ou dont la métrique n'est pas mesurable
        est écartée : on ne saurait ni sur quoi juger sa progression, ni jusqu'à quand la
        tenir. Elle **survit dans le fichier** — on n'efface pas ce qu'on ne comprend pas.
        """
        rows = await self._repo.read_all(fresh=fresh)
        usable = [
            row
            for row in rows
            if row.model.id and row.model.deadline is not None and row.model.metric in GOAL_METRICS
        ]
        return sorted(
            usable,
            key=lambda row: (row.model.created or row.model.deadline or date.min, row.index),
            reverse=True,
        )

    async def _active_row(self, *, fresh: bool = False) -> Row[GoalRow] | None:
        """L'objectif en cours, ou rien. Il n'y en a **qu'un** (`GOAL-01`).

        S'il y en avait plusieurs — fichier édité à la main —, le plus récent gagne. Le
        fichier n'est pas corrigé au passage : une lecture qui écrit est une lecture qui
        surprend, et la ligne surnuméraire reste visible plutôt que d'être escamotée.
        """
        for row in await self._rows(fresh=fresh):
            if normalise_status(row.model.status) == STATUS_ACTIVE:
                return row
        return None

    # ── Progression (`GOAL-04`) ───────────────────────

    async def progress(self, model: GoalRow, today: date) -> GoalProgress:
        """Avancement de l'objectif vers sa cible, aujourd'hui.

        Le **point de départ** est redéduit : c'est la valeur qu'avait la métrique le jour
        de l'adoption, lue dans les mêmes données et par la même réduction. Rien n'est
        stocké en plus des onze colonnes de l'annexe, et une correction d'historique se
        répercute sur la progression — ce qui est voulu, puisque la progression prétend
        décrire les données et non un souvenir de celles-ci.
        """
        key = model.metric
        rule = GOAL_METRICS[key]
        granularity = granularity_of(key)
        points = await load_points(self._store, key)

        current, as_of = current_value(
            points, reduction=rule.reduction, granularity=granularity, as_of=today
        )
        # Sans date de création — ligne écrite à la main dans un tableur —, le point de
        # départ est celui d'aujourd'hui : l'avancement vaut alors zéro, ce qui est faux
        # d'une manière visible, plutôt que n'importe quoi d'une manière plausible.
        baseline, _ = current_value(
            points,
            reduction=rule.reduction,
            granularity=granularity,
            as_of=model.created or today,
        )

        return GoalProgress(
            metric=key,
            label=label_of(key),
            unit=unit_of(key),
            baseline=None if baseline is None else round(baseline, 2),
            current=None if current is None else round(current, 2),
            target=model.target,
            ratio=ratio(baseline, current, model.target),
            summary=summary(current, model.target, unit_of(key)),
            basis=basis(rule.reduction, granularity, as_of),
        )

    # ── Vue d'écran (`GOAL-05`, `GOAL-06`) ────────────

    async def view(self, *, today: date | None = None) -> GoalsView:
        """Tout l'écran en une requête : l'état, l'objectif en cours, l'historique."""
        current = today or today_local()
        await self._store.prefetch(list(CONTEXT_FILES))

        rows = await self._rows()
        active = next(
            (row for row in rows if normalise_status(row.model.status) == STATUS_ACTIVE), None
        )
        history = [
            self._to_schema(row)
            for row in rows
            if normalise_status(row.model.status) == STATUS_CLOSED
        ]

        if active is None:
            return GoalsView(state="none", active=None, history=history, today=current)

        model = active.model
        assert model.deadline is not None
        days_left = (model.deadline - current).days

        return GoalsView(
            state="active",
            active=ActiveGoal(
                goal=self._to_schema(active),
                progress=await self.progress(model, current),
                days_left=days_left,
                # L'échéance passée ne clôt rien toute seule : l'objectif reste `active`
                # dans le fichier tant qu'un geste ne l'a pas fermé. Un `GET` qui écrirait
                # fausserait le cache autant que la promesse « rien sans validation ».
                expired=days_left < 0,
            ),
            history=history,
            today=current,
        )

    async def objective_sentence(self) -> str:
        """L'objectif actif en une phrase, pour la génération de planning (`PLAN-03`).

        C'est la dette du lot L13 soldée : le champ `objective` était jusqu'ici saisi en
        texte libre à l'écran, faute de `goals.csv`. Il reste modifiable — un remplacement
        ponctuel, « cette semaine je prépare une course » — mais il n'a plus à être rempli
        pour que le planning tienne compte de ce qu'on vise.

        Volontairement sans valeur courante : le planificateur reçoit déjà la fréquence
        réelle des quatre dernières semaines, et lui servir deux chiffres calculés sur des
        fenêtres différentes serait le meilleur moyen d'obtenir une proposition qui
        argumente contre elle-même.
        """
        row = await self._active_row()
        if row is None:
            return ""

        model = row.model
        assert model.deadline is not None
        unit = model.unit or unit_of(model.metric)
        return (
            f"{model.title or label_of(model.metric)} — cible {fr(model.target)} {unit} "
            f"({label_of(model.metric).lower()}), échéance {model.deadline:%d/%m/%Y}"
        )

    # ── Le condensé factuel (`GOAL-02`) ───────────────

    async def summary_lines(self, today: date) -> tuple[list[str], bool]:
        """Ce qui part au modèle, et rien d'autre. Rend `(lignes, données maigres)`.

        **Jamais les fichiers entiers.** Une douzaine de lignes, construites avec les mêmes
        réductions que la progression : le modèle voit donc exactement le chiffre sur
        lequel son objectif sera jugé. Lui montrer une moyenne et en mesurer une autre
        rendrait toute proposition incompréhensible six semaines plus tard.

        Ni note, ni photo, ni horodatage de repas n'entrent ici. C'est ce que
        `GoalProposal.basis` publie à l'écran, et cette publication est ce qui rend la
        promesse de `GOAL-02` vérifiable plutôt que déclarative.
        """
        await self._store.prefetch(list(CONTEXT_FILES))
        values = await self._settings.values()

        lines: list[str] = []
        sessions: list[tuple[date, float]] = []

        for key, rule in GOAL_METRICS.items():
            points = await load_points(self._store, key)
            if key == "weekly_sessions":
                sessions = points

            value, as_of = current_value(
                points, reduction=rule.reduction, granularity=granularity_of(key), as_of=today
            )
            if value is None:
                lines.append(f"{label_of(key)} : jamais relevé")
                continue
            lines.append(
                f"{label_of(key)} : {fr(value)} {unit_of(key)} "
                f"({basis(rule.reduction, granularity_of(key), as_of)})"
            )

        lines.extend(await self._weight_range(today))
        lines.append(
            f"Cibles réglées : poids {fr(values.target_weight_kg)} kg, "
            f"protéines {fr(values.target_protein_g)} g par jour, "
            f"hydratation {fr(values.target_hydration_ml)} ml par jour"
        )
        lines.append(await self._supplements_line())

        start, end, _ = window("week", today)
        recent = sum(value for day, value in sessions if start <= day <= end)

        return lines, recent < THIN_SESSIONS

    async def _weight_range(self, today: date) -> list[str]:
        """Amplitude du poids sur trois mois — l'un des faits que `GOAL-02` nomme."""
        points = await load_points(self._store, "weight")
        horizon = today - timedelta(days=WEIGHT_RANGE_DAYS)
        recent = [value for day, value in points if day >= horizon]
        if not recent:
            return []
        return [
            f"Poids sur {WEIGHT_RANGE_DAYS} jours : de {fr(min(recent))} à "
            f"{fr(max(recent))} kg, {len(recent)} pesée(s)"
        ]

    async def _supplements_line(self) -> str:
        """Suppléments suivis. Leur nom suffit : la posologie ne regarde pas le modèle."""
        schedule = await SupplementService(self._store).schedule(active_only=True)
        if not schedule:
            return "Suppléments : aucun suivi"
        return f"Suppléments suivis : {', '.join(item.name for item in schedule)}"

    async def past_lines(self) -> list[str]:
        """Objectifs passés et leur résultat, réinjectés dans la génération (`GOAL-06`).

        C'est la raison d'être de la colonne `outcome`. Sans elle, le modèle reproposerait
        indéfiniment l'objectif qu'on vient d'abandonner — et une suggestion déjà refusée
        est la plus sûre façon de faire cesser de lire les suggestions.
        """
        lines: list[str] = []
        for row in await self._rows():
            model = row.model
            if normalise_status(model.status) != STATUS_CLOSED:
                continue
            outcome = OUTCOME_LABELS.get(normalise_outcome(model.outcome), "sans résultat noté")
            unit = model.unit or unit_of(model.metric)
            lines.append(
                f"« {model.title} » ({label_of(model.metric).lower()}, cible "
                f"{fr(model.target)} {unit}) : {outcome}"
            )
        return lines

    # ── Génération (`GOAL-01`) ────────────────────────

    async def propose(
        self, ai: AiService, request: ProposalRequest, *, today: date | None = None
    ) -> GoalProposal:
        """Demande un objectif à un modèle. **N'écrit rien** (`GOAL-03`).

        La symétrie avec `PlanningService.propose` et `AppleImportService.analyze` est
        voulue : cette méthode ne connaît pas l'écriture, `adopt` ne connaît pas l'IA.

        Refuse tant qu'un objectif est en cours, et pas seulement à l'adoption : proposer
        coûte un appel payant, et le proposer pour le refuser ensuite serait payer pour
        apprendre une règle que le serveur connaissait déjà.
        """
        current = today or today_local()
        await self._refuse_if_active(
            "Un objectif est déjà en cours. Clos-le ou abandonne-le avant d'en viser un "
            "autre — deux objectifs à la fois, c'est aucun objectif."
        )

        lines, thin = await self.summary_lines(current)
        floor = current + timedelta(weeks=DEADLINE_MIN_WEEKS)
        ceiling = current + timedelta(weeks=DEADLINE_MAX_WEEKS)

        payload = await ai.ask_json(
            instruction=INSTRUCTION,
            prompt=build_prompt(
                summary=lines,
                past=await self.past_lines(),
                floor=floor,
                ceiling=ceiling,
                focus=request.focus,
                fallback=thin,
            ),
            max_tokens=MAX_TOKENS,
        )

        goal, dropped = read_goal(payload, floor=floor, ceiling=ceiling, fallback=thin)
        if goal is None:
            # La chaîne a fonctionné, la réponse ne contient rien qu'on puisse écrire.
            # `422` et non `503` : rien n'est en panne, et réessayer ou se fixer une cible
            # soi-même sont deux conduites également valables.
            raise AiUnreadableError(
                "Le modèle n'a pas proposé d'objectif exploitable. Réessaie, ou fixe-toi "
                "une cible à la main — les cinq métriques mesurables sont juste à côté."
            )

        return GoalProposal(goal=goal, basis=lines, fallback=thin, dropped=dropped)

    # ── Écriture (`GOAL-03`) ──────────────────────────

    async def _refuse_if_active(self, message: str) -> None:
        if await self._active_row() is not None:
            raise StorageConflictError(message)

    async def adopt(
        self, payload: GoalPayload, *, source: str = "ai", today: date | None = None
    ) -> GoalEntry:
        """Écrit l'objectif retenu. C'est le premier moment où quoi que ce soit est écrit.

        La métrique et la cible sont revalidées bien que la proposition les ait déjà
        passées : le client poste ce qu'il veut, et une cible immesurable adoptée
        afficherait un tiret jusqu'à son échéance.
        """
        current = today or today_local()

        rule = GOAL_METRICS.get(payload.metric)
        if rule is None:
            raise ValidationFailedError(
                f"« {payload.metric} » n'est pas une métrique mesurable dans Metric."
            )
        if not rule.minimum <= payload.target <= rule.maximum:
            raise ValidationFailedError(
                f"Une cible de {fr(payload.target)} {unit_of(payload.metric)} sort des "
                f"bornes plausibles ({fr(rule.minimum)} à {fr(rule.maximum)})."
            )

        await self._refuse_if_active(
            "Un objectif est déjà en cours. Clos-le ou abandonne-le avant d'en adopter un autre."
        )

        row = await self._repo.append(
            GoalRow(
                id=new_id(),
                created=current,
                title=payload.title,
                metric=payload.metric,
                target=payload.target,
                # L'unité vient du registre, jamais du client : servie, elle ne peut pas
                # diverger ; recopiée, elle finirait par écrire « kg » sur des protéines.
                unit=unit_of(payload.metric),
                deadline=payload.deadline,
                rationale=payload.rationale,
                source=source,
                status=STATUS_ACTIVE,
                outcome="",
            )
        )
        return self._to_schema(row)

    async def _close(self, index: int, token: str, *, outcome: str, today: date) -> GoalEntry:
        """Ferme une ligne et lui pose son résultat, sous garde anti-conflit (`STO-05`)."""
        row = next((item for item in await self._rows(fresh=True) if item.index == index), None)
        if row is None:
            raise StorageNotFoundError("Cet objectif n'existe pas.")
        if normalise_status(row.model.status) == STATUS_CLOSED:
            raise StorageConflictError("Cet objectif est déjà clos.")

        if outcome == OUTCOME_REACHED:
            # Le résultat n'est pas choisi par le client : c'est une lecture des données,
            # et la lui laisser reviendrait à laisser cocher « atteint » un objectif qui
            # ne l'est pas.
            advance = (await self.progress(row.model, today)).ratio
            outcome = OUTCOME_REACHED if advance is not None and advance >= 1 else OUTCOME_PARTIAL

        written = await self._repo.replace_by_token(
            index,
            token,
            row.model.model_copy(update={"status": STATUS_CLOSED, "outcome": outcome}),
        )
        return self._to_schema(written)

    async def close(self, index: int, token: str, *, today: date | None = None) -> GoalEntry:
        """Clôt un objectif mené à son terme, résultat **calculé** (`GOAL-06`).

        Atteint quand l'avancement vaut 1 — cible touchée ou dépassée —, partiel sinon.

        Clore avant l'échéance est permis, et c'est un cas réel : une cible touchée en
        trois semaines est atteinte, pas en avance.
        """
        return await self._close(
            index, token, outcome=OUTCOME_REACHED, today=today or today_local()
        )

    async def abandon(self, index: int, token: str, *, today: date | None = None) -> GoalEntry:
        """Abandonne un objectif en cours (`GOAL-03`).

        Distinct d'une clôture partielle, et la distinction sert la génération suivante :
        « abandonné » dit qu'on n'en voulait plus, « partiel » qu'on n'y est pas arrivé.
        Reproposer la même chose n'a pas le même sens dans les deux cas.
        """
        return await self._close(
            index, token, outcome=OUTCOME_ABANDONED, today=today or today_local()
        )


class WeeklyInsightService:
    """Bilan hebdomadaire (`IA-08`).

    Le bilan porte sur la semaine **révolue**. Une semaine en cours n'a pas de bilan : ce
    qui s'y est « décroché » un mardi peut se rattraper le samedi, et un jugement qui se
    dément tout seul n'en est pas un.
    """

    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._repo: CsvRepository[WeeklyRow] = CsvRepository(store, WEEKLY_INSIGHTS, WeeklyRow)
        self._goals = GoalService(store)

    @staticmethod
    def last_complete_week(today: date) -> date:
        """Lundi de la dernière semaine achevée."""
        return week_start(today) - timedelta(days=7)

    @staticmethod
    def _to_schema(row: Row[WeeklyRow]) -> WeeklyEntry:
        model = row.model
        assert model.week is not None  # garanti par le filtre de `_rows`
        return WeeklyEntry(
            id=row.index,
            token=row.token,
            week=model.week,
            created=model.created,
            summary=model.summary,
            source=model.source or "ai",
        )

    async def _rows(self, *, fresh: bool = False) -> list[Row[WeeklyRow]]:
        """Bilans lisibles, du plus récent au plus ancien."""
        rows = await self._repo.read_all(fresh=fresh)
        usable = [row for row in rows if row.model.week is not None and row.model.summary]
        return sorted(usable, key=lambda row: row.model.week or date.min, reverse=True)

    async def view(self, *, today: date | None = None) -> WeeklyView:
        current = today or today_local()
        week = self.last_complete_week(current)
        rows = await self._rows()
        return WeeklyView(
            entries=[self._to_schema(row) for row in rows],
            next_week=week,
            already_kept=any(row.model.week == week for row in rows),
        )

    # ── Génération (`IA-08`) ──────────────────────────

    async def generate(
        self, ai: AiService, *, adherence: AdherenceView, today: date | None = None
    ) -> WeeklyReview:
        """Demande le bilan de la semaine révolue. **N'écrit rien**.

        `adherence` est **fourni**, pas calculé : `PLAN-06` en détient l'unique
        implémentation, et un second calcul finirait par répondre autre chose pour la même
        semaine.
        """
        current = today or today_local()
        monday = self.last_complete_week(current)

        facts, history = await self._facts(monday, adherence)
        payload = await ai.ask_json(
            instruction=weekly.INSTRUCTION,
            prompt=weekly.build_prompt(
                monday=monday,
                summary=facts,
                history=history,
                goal=await self._goals.objective_sentence(),
            ),
            max_tokens=MAX_TOKENS,
        )

        progress, setbacks, action = weekly.read_review(payload)
        if not progress and not setbacks and not action:
            raise AiUnreadableError(
                "Le modèle n'a rien rendu d'exploitable pour cette semaine. Réessaie — "
                "les chiffres de la semaine restent lisibles sur les autres écrans."
            )

        return WeeklyReview(
            week=monday, progress=progress, setbacks=setbacks, action=action, basis=facts
        )

    async def _facts(self, monday: date, adherence: AdherenceView) -> tuple[list[str], list[str]]:
        """Condensé de la semaine commentée, et les semaines précédentes pour comparer.

        Même règle que pour un objectif : un condensé factuel, jamais les fichiers. Les
        séries sont chargées **une fois** puis découpées en mémoire — les redemander par
        semaine coûterait vingt lectures pour cinq fichiers.
        """
        await self._store.prefetch(list(CONTEXT_FILES))
        series = {key: await load_points(self._store, key) for key in GOAL_METRICS}
        sunday = monday + timedelta(days=6)

        facts: list[str] = []
        for key, rule in GOAL_METRICS.items():
            if rule.reduction == "latest":
                found = latest(series[key], sunday)
                if found is not None:
                    value, day = found
                    facts.append(f"{label_of(key)} au {day:%d/%m} : {fr(value)} {unit_of(key)}")
                continue
            # La valeur de cette semaine-là, et non une moyenne glissante : c'est cette
            # semaine-là qu'on commente.
            facts.append(
                f"{label_of(key)} : {fr(self._week_value(series[key], key, monday))} {unit_of(key)}"
            )

        week = next((row for row in adherence.weeks if row.week == monday), None)
        if week is not None:
            facts.append(
                f"Planning : {week.planned} séance(s) prévue(s), {week.honoured} honorée(s)"
                if week.planned
                else "Planning : rien n'était prévu cette semaine-là"
            )

        history: list[str] = []
        for offset in range(INSIGHT_HISTORY_WEEKS, 0, -1):
            past = monday - timedelta(weeks=offset)
            parts = [
                f"{label_of(key).lower()} {fr(self._week_value(series[key], key, past))}"
                for key, rule in GOAL_METRICS.items()
                if rule.reduction == "rate"
            ]
            history.append(f"semaine du {past.isoformat()} : {', '.join(parts)}")

        return facts, history

    @staticmethod
    def _week_value(points: list[tuple[date, float]], key: str, monday: date) -> float:
        """Valeur d'une cadence sur **une** semaine précise.

        Une métrique hebdomadaire porte un point daté au lundi ; une métrique quotidienne
        en porte sept, dont la moyenne se prend sur les sept jours et non sur les jours
        renseignés — c'est la convention de tout le lot, et celle que suit déjà la moyenne
        d'hydratation du domaine Hydratation.
        """
        if granularity_of(key) == "week":
            return next((value for day, value in points if day == monday), 0.0)
        sunday = monday + timedelta(days=6)
        return sum(value for day, value in points if monday <= day <= sunday) / 7

    # ── Conservation ──────────────────────────────────

    async def keep(self, payload: WeeklyPayload, *, today: date | None = None) -> WeeklyEntry:
        """Conserve un bilan. Une semaine, **une** ligne.

        Reconserver la même semaine remplace la ligne existante plutôt que d'en ajouter
        une seconde. `week` est la clé naturelle du fichier : deux lignes pour la même
        semaine rendraient « le bilan de la semaine du 3 août » ambigu, et un fichier
        destiné à un tableur ne porte pas deux vérités pour une même ligne.

        Le remplacement se fait sans jeton d'en-tête, comme les suppressions en cascade de
        `remove_where` : la ligne visée n'est pas désignée par l'utilisateur mais déduite
        de la semaine qu'il vient lui-même de demander à conserver.
        """
        item = WeeklyRow(
            week=payload.week,
            created=today or today_local(),
            summary=payload.summary,
            source="ai",
        )

        rows = await self._repo.read_all(fresh=True)
        existing = next((row for row in rows if row.model.week == payload.week), None)
        if existing is None:
            return self._to_schema(await self._repo.append(item))
        return self._to_schema(await self._repo.replace(existing.index, existing.raw, item))

    async def remove(self, index: int, token: str) -> None:
        """Retire un bilan de l'historique, sous garde anti-conflit (`STO-05`)."""
        await self._repo.delete_by_token(index, token)


__all__ = ["GoalService", "WeeklyInsightService", "load_points", "new_id"]
