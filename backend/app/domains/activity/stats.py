"""Agrégats du domaine Activité (`ACT-09` → `ACT-16`).

Toutes les fenêtres hebdomadaires sont des **semaines ISO** : lundi → dimanche. Le
backlog le dit deux fois (`ACT-11` « remise à zéro chaque lundi », `PLAN-01` « semaine
commençant le lundi ») et la spec d'assiduité en dépend (`HEAT-11`). Un seul endroit
calcule cette borne.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.dates import week_start
from app.core.parsing import pace_min_per_km
from app.domains.activity.models import CircuitSessionRow, MuscleGroup, RunRow
from app.domains.activity.schemas import (
    ActivityItem,
    ActivityOverview,
    DayVolume,
    NeglectedGroup,
    TrainingSplit,
    TrainingTotals,
    WeekTotals,
    WeekVolume,
)
from app.domains.activity.service import (
    CircuitSessionService,
    RunService,
)
from app.storage.csv_repo import Row
from app.storage.files import FileStore

#: Profondeur de l'historique hebdomadaire (`ACT-12`).
WEEKS_BACK = 8


@dataclass(frozen=True, slots=True)
class _Session:
    """Ce qu'une séance apporte aux totaux : un jour et des minutes.

    **Les totaux ne connaissent plus le fichier d'où vient une séance.** Une séance
    historique et un tabata déclaré fait n'ont ni les mêmes colonnes ni le même
    identifiant, mais ils pèsent la même chose dans « combien de temps cette semaine » —
    et c'est tout ce que `_per_day`, `_week_totals` et `_split` demandent.

    Le passage par cette forme n'est pas de la cérémonie : `docs/refonte-activite.md`
    rebranche les totaux sur `circuit_sessions.csv` tandis que l'écran `/activite` lit
    encore `workouts.csv` jusqu'à la phase 5. Sans elle, l'arithmétique aurait été
    recopiée pour la durée de la transition, et deux copies auraient fini par répondre
    deux chiffres différents à la même question.
    """

    date: date
    duration_min: float


def _sessions_of(rows: Sequence[Row[CircuitSessionRow]]) -> list[_Session]:
    """Les séances tabata, réduites à ce qui compte dans un total."""
    return [_Session(date=row.model.date, duration_min=row.model.duration_min) for row in rows]


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


class ActivityStats:
    """Lecture agrégée de l'activité."""

    def __init__(self, store: FileStore) -> None:
        self._runs = RunService(store)
        self._tabata = CircuitSessionService(store)

    @staticmethod
    def _per_day(
        runs: Sequence[Row[RunRow]], sessions_in: Sequence[_Session]
    ) -> tuple[dict[date, float], dict[date, int]]:
        """Minutes et nombre de séances par jour, toutes activités confondues."""
        minutes: defaultdict[date, float] = defaultdict(float)
        sessions: defaultdict[date, int] = defaultdict(int)
        for run in runs:
            minutes[run.model.date] += run.model.duration_min
            sessions[run.model.date] += 1
        for session in sessions_in:
            minutes[session.date] += session.duration_min
            sessions[session.date] += 1
        return minutes, sessions

    async def overview(self, today: date, *, limit: int = 30) -> ActivityOverview:
        """Ce que `/activite` affiche : la semaine, les volumes, et l'historique fusionné.

        **Deux fichiers, et plus trois.** Depuis la phase 5, une séance d'entraînement est
        soit une course, soit un circuit déclaré fait. Le tonnage a disparu avec
        `exercise_log.csv` et ne revient pas : un exercice au temps porte `reps = -1`, et
        le multiplier par une charge donnerait un chiffre négatif (**C4**).
        """
        runs = await self._runs.all()
        done = await self._tabata.all()

        current = week_start(today)
        history = _sessions_of(done)
        minutes, sessions = self._per_day(runs, history)

        return ActivityOverview(
            today=today,
            week=self._week_totals(runs, history, current),
            days=self._days(minutes, current),
            weeks=self._weeks(minutes, sessions, current),
            neglected=self._neglected(await self._tabata.sets(), today),
            history=self._history(runs, done)[:limit],
            total=len(runs) + len(done),
        )

    # ── Totaux d'entraînement (`AGG-02`) ──────────────

    async def training(self, today: date) -> TrainingTotals:
        """Totaux du tableau de bord : deux fichiers lus, rien de plus.

        Le journal des exercices n'est pas ouvert : `AGG-02` demande des séances et des
        minutes, pas du tonnage. Une lecture Nextcloud évitée par affichage d'accueil.

        ## Les deux fichiers ne sont plus les mêmes

        `runs.csv` et **`circuit_sessions.csv`**, là où c'était `runs.csv` et
        `workouts.csv` (`docs/refonte-activite.md` §4). Le remplacement est **exclusif** et
        c'est la seule forme correcte : depuis la phase 1, déclarer un circuit fait écrit
        dans les deux mondes, donc lire les deux additionnerait chaque tabata deux fois.

        Ce que ça coûte, et qui est assumé : la musculation historique cesse de compter
        ici avant d'être supprimée. Elle reste **entière dans son fichier** jusqu'à la
        phase 6, et visible sur `/activite` — c'est le tableau de bord qui a changé de
        source, pas l'historique qui a été touché.
        """
        runs = await self._runs.all()
        sessions_rows = await self._tabata.all()
        tabata = _sessions_of(sessions_rows)

        current = week_start(today)
        minutes, sessions = self._per_day(runs, tabata)

        return TrainingTotals(
            sessions_total=len(runs) + len(tabata),
            minutes_total=_round(sum(minutes.values())) or 0,
            week=self._week_totals(runs, tabata, current),
            weeks=self._weeks(minutes, sessions, current),
            split=self._split(runs, tabata),
        )

    @staticmethod
    def _split(runs: Sequence[Row[RunRow]], tabata: Sequence[_Session]) -> list[TrainingSplit]:
        """Répartition course / tabata (`AGG-02`).

        **Deux parts et non trois.** Les trois d'avant — course, musculation, autre —
        découpaient le champ `type` de `workouts.csv`, qui est libre (`ACT-03`) : il
        fallait une troisième part pour ne pas ranger une heure de yoga sous
        « musculation ». Ce champ n'existe plus dans la source ; un tabata *est* un
        tabata, et inventer une part « autre » toujours vide serait afficher une
        catégorie que rien ne peut remplir.

        La part disparaît quand elle est vide, comme avant : une semaine sans course ne
        montre pas une barre à zéro.
        """
        total = len(runs) + len(tabata)
        parts: tuple[tuple[str, str, int, float], ...] = (
            (
                "run",
                "Course",
                len(runs),
                sum(row.model.duration_min for row in runs),
            ),
            (
                "tabata",
                "Tabata",
                len(tabata),
                sum(item.duration_min for item in tabata),
            ),
        )

        return [
            TrainingSplit(
                kind=kind,
                label=label,
                sessions=count,
                minutes=_round(minutes) or 0,
                ratio=count / total if total else 0.0,
            )
            for kind, label, count, minutes in parts
            if count
        ]

    # ── Séries pour `AGG-04` ──────────────────────────

    async def weekly_minutes(self) -> list[tuple[date, float]]:
        """Minutes d'activité par semaine ISO, datées au lundi."""
        minutes, _ = self._per_day(await self._runs.all(), _sessions_of(await self._tabata.all()))
        return self._by_week(minutes)

    async def weekly_sessions(self) -> list[tuple[date, float]]:
        """Nombre de séances par semaine ISO, datées au lundi.

        Toutes catégories confondues, comme `AGG-02` compte les totaux : une sortie de
        course et une heure de muscu sont deux séances. Sert la métrique `weekly_sessions`
        du registre, donc aussi bien les séries génériques (`AGG-04`) qu'un objectif de
        régularité (`GOAL-04`).
        """
        _, sessions = self._per_day(await self._runs.all(), _sessions_of(await self._tabata.all()))
        return self._by_week({day: float(count) for day, count in sessions.items()})

    async def weekly_distance(self) -> list[tuple[date, float]]:
        """Kilomètres courus par semaine ISO.

        La course seule : additionner les kilomètres d'une séance de musculation n'aurait
        pas de sens, et c'est déjà la raison pour laquelle `_week_totals` calcule l'allure
        moyenne sur les courses uniquement.
        """
        per_day: defaultdict[date, float] = defaultdict(float)
        for row in await self._runs.all():
            per_day[row.model.date] += row.model.distance_km
        return self._by_week(per_day)

    @staticmethod
    def _by_week(per_day: dict[date, float]) -> list[tuple[date, float]]:
        per_week: defaultdict[date, float] = defaultdict(float)
        for day, value in per_day.items():
            per_week[week_start(day)] += value
        return sorted((day, _round(value) or 0) for day, value in per_week.items())

    # ── Semaine en cours (`ACT-10`, `ACT-11`) ─────────

    @staticmethod
    def _week_totals(
        runs: Sequence[Row[RunRow]], sessions: Sequence[_Session], current: date
    ) -> WeekTotals:
        end = current + timedelta(days=7)
        week_runs = [row.model for row in runs if current <= row.model.date < end]
        week_sessions = [item for item in sessions if current <= item.date < end]

        distance = sum(run.distance_km for run in week_runs)
        running_minutes = sum(run.duration_min for run in week_runs)

        return WeekTotals(
            week_start=current,
            minutes=_round(
                sum(run.duration_min for run in week_runs)
                + sum(item.duration_min for item in week_sessions)
            )
            or 0,
            sessions=len(week_runs) + len(week_sessions),
            distance_km=_round(distance) or 0,
            # L'allure moyenne ne porte que sur la course : mélanger une heure de yoga
            # aux kilomètres n'aurait aucun sens.
            pace_min_km=_round(pace_min_per_km(distance, running_minutes), 3),
        )

    @staticmethod
    def _days(minutes: dict[date, float], current: date) -> list[DayVolume]:
        """Les sept jours de la semaine en cours, repos distingué (`ACT-10`)."""
        days: list[DayVolume] = []
        for offset in range(7):
            day = current + timedelta(days=offset)
            volume = minutes.get(day, 0.0)
            days.append(
                DayVolume(
                    date=day,
                    weekday=offset + 1,
                    minutes=_round(volume) or 0,
                    # Un jour de repos est un choix, pas un trou de données.
                    rest=volume == 0,
                )
            )
        return days

    @staticmethod
    def _weeks(
        minutes: dict[date, float], sessions: dict[date, int], current: date
    ) -> list[WeekVolume]:
        """Les huit dernières semaines, la plus ancienne en premier (`ACT-12`)."""
        totals: list[tuple[date, float, int]] = []
        for offset in range(WEEKS_BACK - 1, -1, -1):
            start = current - timedelta(weeks=offset)
            end = start + timedelta(days=7)
            total = sum(value for day, value in minutes.items() if start <= day < end)
            count = sum(value for day, value in sessions.items() if start <= day < end)
            totals.append((start, _round(total) or 0, count))

        # L'échelle de l'histogramme se calcule **ici**, où la fenêtre entière est sous la
        # main. La rendre à l'écran l'obligerait à reparcourir la liste pour trouver son
        # maximum, ce qui est un calcul métier — et c'était le cas jusqu'à ce lot.
        peak = max((volume for _start, volume, _count in totals), default=0.0)
        return [
            WeekVolume(
                week_start=start,
                minutes=volume,
                sessions=count,
                # Une fenêtre sans une minute d'entraînement n'a pas de barre pleine :
                # elle n'a pas de barre du tout.
                ratio=volume / peak if peak > 0 else 0.0,
            )
            for start, volume, count in totals
        ]

    # ── Muscles (`ACT-14`, `ACT-16`) ──────────────────

    @staticmethod
    def _neglected(entries: list, today: date) -> list[NeglectedGroup]:  # type: ignore[type-arg]
        """Jours depuis la dernière sollicitation de chaque groupe (`ACT-16`).

        Un groupe jamais travaillé rend `None` et non un nombre géant : « jamais » et
        « il y a très longtemps » ne se traitent pas pareil, et une valeur inventée
        fausserait la génération IA de planning (`PLAN-03`).

        **Même règle, autre source.** Les lignes viennent de `circuit_session_sets.csv`
        depuis le rebranchement du coach (`docs/refonte-activite.md` §5 bis) : c'est le
        seul historique par groupe musculaire qui survivra à `exercise_log.csv`. La règle,
        elle, ne bouge pas — la repenser au passage aurait mélangé deux changements dans
        un seul chiffre, et rendu impossible de dire lequel a fait quoi.
        """
        last: dict[str, date] = {}
        for row in entries:
            model = row.model
            current = last.get(model.muscle_group)
            if current is None or model.date > current:
                last[model.muscle_group] = model.date

        neglected: list[NeglectedGroup] = []
        for group in (item.value for item in MuscleGroup):
            if group == MuscleGroup.AUTRE.value:
                continue  # « autre » n'est pas un groupe à solliciter
            seen = last.get(group)
            neglected.append(
                NeglectedGroup(
                    muscle_group=group,
                    days_since=(today - seen).days if seen else None,
                    last_date=seen,
                )
            )
        return sorted(
            neglected,
            # Jamais travaillé d'abord, puis du plus ancien au plus récent.
            key=lambda item: (item.days_since is not None, -(item.days_since or 0)),
        )

    # ── Historique fusionné (`ACT-13`) ────────────────

    @staticmethod
    def _history(
        runs: list[Row[RunRow]],
        done: Sequence[Row[CircuitSessionRow]],
    ) -> list[ActivityItem]:
        items: list[ActivityItem] = []

        for run in runs:
            model = run.model
            items.append(
                ActivityItem(
                    kind="run",
                    id=run.index,
                    token=run.token,
                    date=model.date,
                    label="Course",
                    duration_min=model.duration_min,
                    distance_km=model.distance_km,
                    pace_min_km=_round(
                        model.pace_min_km or pace_min_per_km(model.distance_km, model.duration_min),
                        3,
                    ),
                    source=model.source,
                )
            )

        for row in done:
            session = row.model
            items.append(
                ActivityItem(
                    kind="workout",
                    id=row.index,
                    token=row.token,
                    date=session.date,
                    # Le nom du circuit, dupliqué au moment où il a été fait : supprimer le
                    # patron laisse l'historique lisible (`ACT-06`).
                    label=session.name,
                    duration_min=session.duration_min,
                    rpe=session.rpe,
                    entries=session.rounds,
                    source=session.source,
                )
            )

        return sorted(items, key=lambda item: (item.date, item.kind), reverse=True)
