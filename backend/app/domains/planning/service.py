"""Planning sport : calendrier, écart au réalisé, génération assistée.

Ce service lit **trois** fichiers et n'en écrit qu'un.

Il lit `planning/plan.csv`, qui lui appartient, et `activity/runs.csv` +
`activity/workouts.csv`, qui ne lui appartiennent pas. Le calendrier ne recopie jamais ce
qui a eu lieu : il le regarde là où il est écrit. Sans cela, cocher « fait » sur une
séance prévue créerait une seconde vérité sur ce qui s'est passé ce jour-là — et il y a
déjà eu assez de mal à n'en avoir qu'une.

Trois fichiers, donc, et `FileStore.prefetch` pour les ouvrir ensemble : à ~180 ms
l'aller-retour mesuré sur l'instance réelle, les lire l'un après l'autre coûterait une
demi-seconde de plus par affichage de mois.
"""

from __future__ import annotations

import secrets as secrets_module
from collections import defaultdict
from datetime import date, timedelta

from app.core.dates import today_local, week_start
from app.core.exceptions import AiUnreadableError
from app.domains.activity import circuit_link
from app.domains.activity.models import RunRow, WorkoutRow
from app.domains.activity.stats import ActivityStats
from app.domains.ai.service import AiService
from app.domains.goals.service import GoalService
from app.domains.planning.generation import INSTRUCTION, build_prompt, read_proposals
from app.domains.planning.models import PlanRow, normalise_kind
from app.domains.planning.schemas import (
    AdherenceView,
    AdoptionResult,
    DayCell,
    DoneActivity,
    MonthView,
    PlannedSession,
    PlanPayload,
    Proposal,
    ProposalRequest,
    WeekAdherence,
)
from app.storage.csv_repo import CsvRepository, Row
from app.storage.errors import StorageNotFoundError
from app.storage.files import FileStore
from app.storage.paths import PLAN, RUNS, WORKOUTS

#: Profondeur d'historique servie au flux iCal.
#:
#: Un abonnement n'a pas à porter trois ans de séances passées — il les recharge à chaque
#: rafraîchissement, et un calendrier saturé de vieilles séances est un calendrier qu'on
#: finit par masquer. Trois mois suffisent à retrouver « ce que j'avais prévu le mois
#: dernier », ce qui est la seule question qu'on pose au passé d'un planning.
FEED_PAST_DAYS = 90

#: Fenêtre de calcul du taux de respect, en semaines (`PLAN-06`).
DEFAULT_ADHERENCE_WEEKS = 8

#: Semaines d'historique résumées au modèle (`PLAN-03`).
HISTORY_WEEKS = 4


def new_id() -> str:
    """Identifiant stable d'une séance planifiée.

    Stable et non positionnel, parce que le flux iCal en fait son `UID` : une séance qui
    changerait d'identifiant réapparaîtrait en double dans un calendrier abonné.
    """
    return secrets_module.token_hex(6)


class PlanningService:
    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._plan: CsvRepository[PlanRow] = CsvRepository(store, PLAN, PlanRow)
        self._runs: CsvRepository[RunRow] = CsvRepository(store, RUNS, RunRow)
        self._workouts: CsvRepository[WorkoutRow] = CsvRepository(store, WORKOUTS, WorkoutRow)

    # ── Lecture du planning ───────────────────────────

    @staticmethod
    def _to_schema(row: Row[PlanRow]) -> PlannedSession:
        model = row.model
        assert model.date is not None  # garanti par le filtre de `_rows`
        return PlannedSession(
            id=row.index,
            token=row.token,
            session_id=model.id,
            date=model.date,
            time=model.time.strip() or None,
            kind=normalise_kind(model.kind),
            title=model.title,
            duration_min=model.duration_min,
            note=model.note or None,
            source=model.source or "manual",
            workout_url=circuit_link.find_in_text(model.note),
        )

    async def _rows(self, *, fresh: bool = False) -> list[PlannedSession]:
        """Séances exploitables, triées par date puis par heure.

        Une ligne sans identifiant ou sans date est écartée : on ne saurait ni quel jour
        l'afficher, ni quelle ligne l'écriture suivante viserait. Elle survit dans le
        fichier — on n'efface pas ce qu'on ne comprend pas.
        """
        rows = await self._plan.read_all(fresh=fresh)
        sessions = [
            self._to_schema(row) for row in rows if row.model.id and row.model.date is not None
        ]
        return sorted(sessions, key=lambda item: (item.date, item.time or ""))

    async def between(self, start: date, end: date) -> list[PlannedSession]:
        """Séances prévues dans une plage, bornes comprises."""
        return [session for session in await self._rows() if start <= session.date <= end]

    # ── Calendrier mensuel (`PLAN-01`) ────────────────

    async def month(self, first: date, *, today: date | None = None) -> MonthView:
        """Un mois entier, semaine au lundi, prévu **et** effectué.

        La grille déborde des deux côtés jusqu'aux lundi et dimanche qui l'encadrent :
        c'est ce que dessine un calendrier, et le débordement calculé ici est un
        débordement que le client n'a pas à recalculer (`HEAT-30`).
        """
        current = today or today_local()
        month_start = first.replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        month_end = next_month - timedelta(days=1)

        start = week_start(month_start)
        end = week_start(month_end) + timedelta(days=6)

        await self._store.prefetch([PLAN, RUNS, WORKOUTS])
        planned = await self.between(start, end)
        done = await self._done_between(start, end)

        by_day: dict[date, list[PlannedSession]] = defaultdict(list)
        for session in planned:
            by_day[session.date].append(session)

        days: list[DayCell] = []
        cursor = start
        while cursor <= end:
            days.append(
                DayCell(
                    date=cursor,
                    in_month=month_start <= cursor <= month_end,
                    planned=by_day.get(cursor, []),
                    done=done.get(cursor, []),
                )
            )
            cursor += timedelta(days=1)

        return MonthView(month=month_start, start=start, end=end, days=days, today=current)

    async def _done_between(self, start: date, end: date) -> dict[date, list[DoneActivity]]:
        """Activités **réellement effectuées**, lues chez le domaine Activité."""
        done: dict[date, list[DoneActivity]] = defaultdict(list)

        for run in await self._runs.read_all():
            if start <= run.model.date <= end:
                done[run.model.date].append(
                    DoneActivity(
                        kind="run",
                        id=run.index,
                        label=f"{run.model.distance_km:.2f} km".replace(".", ","),
                        duration_min=run.model.duration_min,
                    )
                )

        for workout in await self._workouts.read_all():
            if start <= workout.model.date <= end:
                done[workout.model.date].append(
                    DoneActivity(
                        kind="workout",
                        id=workout.index,
                        label=workout.model.type,
                        duration_min=workout.model.duration_min,
                    )
                )

        return done

    # ── Écriture (`PLAN-02`) ──────────────────────────

    @staticmethod
    def _to_row(payload: PlanPayload, *, session_id: str, source: str) -> PlanRow:
        return PlanRow(
            id=session_id,
            date=payload.date,
            time=payload.time or "",
            kind=payload.kind,
            title=payload.title,
            duration_min=payload.duration_min,
            note=payload.note or "",
            source=source,
        )

    async def create(self, payload: PlanPayload, *, source: str = "manual") -> PlannedSession:
        row = await self._plan.append(
            self._to_row(await self._with_link(payload), session_id=new_id(), source=source)
        )
        return self._to_schema(row)

    async def _with_link(self, payload: PlanPayload) -> PlanPayload:
        """La charge utile, note enrichie du lien de la séance Cadence demandée (**D5**).

        Le lien est **ajouté à la note**, pas rangé dans une colonne. Trois conséquences,
        toutes assumées :

        * une note reste lisible seule, dans un tableur, sans rien à rejoindre ;
        * supprimer le circuit ne casse pas la séance prévue — une URL Cadence porte la
          séance entière, c'est le seul endroit où l'absence de base de données aide ;
        * en contrepartie, le lien ne suit pas les corrections du circuit. Une séance
          prévue la semaine dernière garde la version de la semaine dernière, ce qui est
          défendable pour un plan.

        Un `circuit_id` qui ne désigne rien est **ignoré en silence**. Refuser toute la
        séance prévue parce qu'un modèle a nommé un circuit supprimé coûterait plus que
        ça ne protège : ce qui compte — le jour, l'heure, le titre — est juste.
        """
        if not payload.circuit_id:
            return payload

        from app.domains.activity.service import CircuitService

        circuit = await CircuitService(self._store).find(payload.circuit_id)
        if circuit is None or circuit.url is None:
            return payload

        note = (payload.note or "").strip()
        return payload.model_copy(update={"note": f"{note} {circuit.url}".strip()})

    async def update(self, index: int, token: str, payload: PlanPayload) -> PlannedSession:
        rows = await self._plan.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Cette séance n'est pas au planning.")
        existing = rows[index].model

        row = await self._plan.replace_by_token(
            index,
            token,
            self._to_row(
                payload,
                # L'identifiant survit à la correction : c'est l'`UID` du flux iCal, et
                # le voir changer ferait apparaître un doublon dans un calendrier abonné.
                session_id=existing.id or new_id(),
                # La provenance aussi. Déplacer une séance proposée d'un jour ne la
                # transforme pas en séance inventée de toutes pièces — c'est la même
                # règle qu'au L12 pour une estimation retouchée.
                source=existing.source or "manual",
            ),
        )
        return self._to_schema(row)

    async def remove(self, index: int, token: str) -> None:
        await self._plan.delete_by_token(index, token)

    # ── Adoption d'une proposition (`PLAN-04`) ────────

    async def adopt(self, payloads: list[PlanPayload]) -> AdoptionResult:
        """Écrit les séances retenues **en une seule fois**, marquées `source=ai`.

        Une adoption est un geste : elle mérite une écriture, pas huit. Et un `PUT` par
        séance laisserait le fichier à moitié rempli si la coupure survient à la
        cinquième — un planning dont on ne saurait plus s'il a été adopté ou non.
        """
        rows = await self._plan.extend(
            [self._to_row(payload, session_id=new_id(), source="ai") for payload in payloads]
        )
        return AdoptionResult(created=[self._to_schema(row) for row in rows])

    # ── Écart plan / réalisé (`PLAN-06`) ──────────────

    async def adherence(
        self, *, today: date | None = None, weeks: int = DEFAULT_ADHERENCE_WEEKS
    ) -> AdherenceView:
        """Séances prévues contre séances effectuées, semaine par semaine.

        **Ce que « respectée » veut dire ici** : une séance prévue un jour donné est
        honorée si ce jour porte au moins une activité réelle. Le rapprochement se fait
        par jour et non par semaine, et il compte `min(prévu, réalisé)` sur la journée :
        trois sorties un mardi n'honorent pas trois séances prévues le jeudi, et deux
        séances prévues le même mardi demandent deux activités ce mardi-là.

        On ne compare **ni la nature ni la durée**. Une séance de muscu remplacée par une
        sortie parce qu'il faisait beau reste une séance faite ; exiger l'identité rendrait
        le taux plus sévère que ce qu'il prétend mesurer.

        Ce taux n'est ni celui de `AGG-03` ni celui de `HEAT-27` — voir `AdherenceView`.
        """
        current = today or today_local()
        this_week = week_start(current)
        start = this_week - timedelta(weeks=weeks - 1)
        end = this_week + timedelta(days=6)

        await self._store.prefetch([PLAN, RUNS, WORKOUTS])
        planned = await self.between(start, end)
        done = await self._done_between(start, end)

        planned_by_day: dict[date, int] = defaultdict(int)
        for session in planned:
            planned_by_day[session.date] += 1

        rows: list[WeekAdherence] = []
        total_planned = 0
        total_honoured = 0

        for offset in range(weeks):
            monday = start + timedelta(weeks=offset)
            days = [monday + timedelta(days=step) for step in range(7)]

            week_planned = sum(planned_by_day.get(day, 0) for day in days)
            week_done = sum(len(done.get(day, [])) for day in days)
            week_honoured = sum(
                min(planned_by_day.get(day, 0), len(done.get(day, []))) for day in days
            )

            total_planned += week_planned
            total_honoured += week_honoured

            rows.append(
                WeekAdherence(
                    week=monday,
                    planned=week_planned,
                    done=week_done,
                    honoured=week_honoured,
                    # Rien de prévu n'est pas 0 % de respect : c'est l'absence de taux.
                    # Afficher un zéro ferait passer une semaine sans planning pour une
                    # semaine ratée (« aucune valeur inventée à l'écran »).
                    rate=(week_honoured / week_planned) if week_planned else None,
                )
            )

        return AdherenceView(
            weeks=rows,
            rate=(total_honoured / total_planned) if total_planned else None,
            planned=total_planned,
            honoured=total_honoured,
        )

    # ── Flux iCal (`PLAN-05`) ─────────────────────────

    async def feed_sessions(self, *, today: date | None = None) -> list[PlannedSession]:
        """Séances à publier dans le flux : le passé proche et tout l'avenir."""
        current = today or today_local()
        return [
            session
            for session in await self._rows()
            if session.date >= current - timedelta(days=FEED_PAST_DAYS)
        ]

    # ── Génération assistée (`PLAN-03`) ───────────────

    async def propose(
        self, ai: AiService, request: ProposalRequest, *, today: date | None = None
    ) -> Proposal:
        """Demande un planning à un modèle. **N'écrit rien** (`PLAN-04`).

        La symétrie avec `AppleImportService.analyze` est voulue : cette méthode ne
        connaît pas l'écriture, `adopt` ne connaît pas l'IA, et entre les deux il y a un
        écran et un appui. C'est là que vit « rien n'est écrit sans validation ».
        """
        current = today or today_local()
        # Par défaut, le lundi qui vient : on ne remplit pas une semaine déjà entamée,
        # dont les séances passées ne se planifient plus.
        start = request.start or (week_start(current) + timedelta(days=7))
        end = start + timedelta(days=7 * request.weeks - 1)

        await self._store.prefetch([PLAN, RUNS, WORKOUTS])
        existing = await self.between(start, end)
        history, basis = await self._history(current)
        muscles = await self._muscles(current)

        payload = await ai.ask_json(
            instruction=INSTRUCTION,
            prompt=build_prompt(
                start=start,
                end=end,
                history=history,
                muscles=muscles,
                existing=[
                    f"{session.date.isoformat()} : {session.kind} — {session.title}"
                    for session in existing
                ],
                objective=await self._objective(request),
                constraints=request.constraints,
            ),
            max_tokens=1600,
        )

        sessions, dropped = read_proposals(
            payload,
            start=start,
            end=end,
            taken={(session.date, session.kind) for session in existing},
        )

        if not sessions:
            # La chaîne a fonctionné, la réponse ne contient rien qu'on puisse écrire.
            # Un `503` dirait « réessaie plus tard » ; ici, réessayer ou planifier à la
            # main sont deux conduites également valables, et c'est ce que dit `422`.
            raise AiUnreadableError(
                "Le modèle n'a proposé aucune séance exploitable. Réessaie, ou planifie "
                "à la main — les deux formulaires sont juste à côté."
            )

        return Proposal(sessions=sessions, start=start, end=end, basis=basis, dropped=dropped)

    async def _objective(self, request: ProposalRequest) -> str:
        """Objectif à faire tenir au planning — celui qui est actif, sauf mention contraire.

        Dette du lot L13 soldée. Le champ était alors fourni par l'écran en texte libre,
        parce que `goals/goals.csv` n'existait pas : un objectif qu'on venait d'adopter
        devait être **retapé** pour que le planning en tienne compte, et l'oublier une
        fois suffisait à obtenir une semaine qui l'ignorait sans le dire.

        Le champ ne disparaît pas pour autant : rempli, il **remplace** ponctuellement
        l'objectif du moment — « cette semaine je prépare une course » n'a pas vocation à
        devenir un objectif de six semaines dans `goals.csv`.
        """
        typed = request.objective.strip()
        return typed or await GoalService(self._store).objective_sentence()

    async def _history(self, today: date) -> tuple[list[str], list[str]]:
        """Fréquence réelle des quatre dernières semaines (`PLAN-03`).

        Rend deux formulations du même fait : l'une pour le modèle, l'autre pour l'écran.
        Elles viennent du **même calcul** — afficher un argument différent de celui qu'on
        a envoyé serait la meilleure façon de rendre une proposition incompréhensible.
        """
        this_week = week_start(today)
        start = this_week - timedelta(weeks=HISTORY_WEEKS - 1)
        done = await self._done_between(start, today)

        lines: list[str] = []
        total = 0
        for offset in range(HISTORY_WEEKS):
            monday = start + timedelta(weeks=offset)
            days = [monday + timedelta(days=step) for step in range(7)]
            entries = [item for day in days for item in done.get(day, [])]
            total += len(entries)
            runs = sum(1 for item in entries if item.kind == "run")
            lines.append(
                f"semaine du {monday.isoformat()} : {len(entries)} séance(s), dont {runs} course(s)"
            )

        average = total / HISTORY_WEEKS
        lines.append(f"moyenne : {average:.1f} séance(s) par semaine sur {HISTORY_WEEKS} semaines")

        basis = [
            f"{average:.1f} séance par semaine en moyenne sur {HISTORY_WEEKS} semaines".replace(
                ".", ","
            )
        ]
        return lines, basis

    async def _muscles(self, today: date) -> list[str]:
        """Groupes musculaires et ancienneté de leur dernière sollicitation (`ACT-16`).

        Lu chez `ActivityStats` plutôt que recalculé : la règle « jamais travaillé rend
        `None`, pas un grand nombre » y est déjà écrite et testée, et un second calcul
        finirait par répondre autre chose.
        """
        overview = await ActivityStats(self._store).overview(today, limit=1)
        lines: list[str] = []
        for group in overview.neglected:
            if group.days_since is None:
                lines.append(f"{group.muscle_group} : jamais travaillé")
            else:
                lines.append(f"{group.muscle_group} : il y a {group.days_since} jour(s)")
        return lines
