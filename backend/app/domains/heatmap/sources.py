"""Registre des sources de données (`HEAT-02`, `HEAT-03`).

Le contrat tient en une phrase : **une source rend un nombre par jour.** Séries,
kilomètres, millilitres, prises — le moteur ne sait pas ce que le nombre représente, et
c'est exactement ce qui lui permet de traiter neuf pistes avec un seul algorithme.

Tout le reste — seuil de validation, cadence, intensité, série — ne travaille que sur ce
nombre (`HEAT-03`). C'est pourquoi il n'existe pas de code « heatmap whey » ou « heatmap
jambes » : ajouter une piste ne demande aucune ligne, et **ajouter une source est le seul
cas qui en demande** (`HEAT-02`).

## Sur l'absence de zéros

Une source ne rend que les jours où il s'est passé quelque chose. Les jours à zéro sont
posés par le moteur, qui seul connaît la plage demandée et la date de création de la
piste — une source qui inventerait des zéros avant l'existence de la piste ferait mentir
`HEAT-07`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from app.core.dates import local_day_of
from app.domains.activity.service import ExerciseService, RunService, WorkoutService
from app.domains.aggregates.service import DashboardService
from app.domains.hydration.service import HydrationService
from app.domains.supplements.service import SupplementService
from app.storage.files import FileStore

#: Séparateur des listes internes à une cellule (`STO-02`).
SEPARATOR = ";"


def split_filter(raw: str) -> list[str]:
    """Découpe un filtre multi-valeurs. Tolère les espaces et les séparateurs en trop."""
    return [chunk.strip() for chunk in raw.split(SEPARATOR) if chunk.strip()]


# ── Implémentations ───────────────────────────────────


async def _muscle_group(store: FileStore, filter_: str) -> dict[date, float]:
    """Séries effectuées sur un ou plusieurs groupes musculaires.

    L'unité est la **série** et non le tonnage : « ai-je travaillé le dos cette
    semaine » ne se répond pas en kilos, et un jour à charge légère compte autant qu'un
    jour lourd pour l'assiduité.
    """
    groups = set(split_filter(filter_))
    per_day: defaultdict[date, float] = defaultdict(float)
    for row in await ExerciseService(store).log_entries():
        if not groups or row.model.muscle_group in groups:
            per_day[row.model.date] += row.model.sets
    return dict(per_day)


async def _runs(store: FileStore, filter_: str) -> dict[date, float]:
    """Kilomètres courus."""
    del filter_
    per_day: defaultdict[date, float] = defaultdict(float)
    for row in await RunService(store).all():
        per_day[row.model.date] += row.model.distance_km
    return dict(per_day)


async def _duration(store: FileStore, filter_: str) -> dict[date, float]:
    """Minutes d'activité, courses et séances confondues."""
    del filter_
    per_day: defaultdict[date, float] = defaultdict(float)
    for run in await RunService(store).all():
        per_day[run.model.date] += run.model.duration_min
    for workout in await WorkoutService(store).all():
        per_day[workout.model.date] += workout.model.duration_min
    return dict(per_day)


async def _supplement_intake(store: FileStore, filter_: str) -> dict[date, float]:
    """Prises d'un supplément donné. Le filtre est son identifiant de planning."""
    schedule_id = filter_.strip()
    per_day: defaultdict[date, float] = defaultdict(float)
    for row in await SupplementService(store).intakes():
        if not schedule_id or row.model.schedule_id == schedule_id:
            per_day[local_day_of(row.model.datetime_)] += 1
    return dict(per_day)


async def _hydration_intake(store: FileStore, filter_: str) -> dict[date, float]:
    """Millilitres bus."""
    del filter_
    volumes = await HydrationService(store).daily_volumes()
    return {day: float(value) for day, value in volumes.items()}


async def _entry_count(store: FileStore, filter_: str) -> dict[date, float]:
    """Nombre de domaines renseignés dans la journée.

    Mesure l'assiduité de **suivi** elle-même, indépendamment de la performance. La
    définition de « un domaine a été renseigné » est celle de `AGG-03`, réutilisée telle
    quelle : deux définitions du même mot donneraient deux grilles pour la même semaine.
    """
    del filter_
    per_day: defaultdict[date, float] = defaultdict(float)
    for days in (await DashboardService(store).sources()).values():
        for day in days:
            per_day[day] += 1
    return dict(per_day)


# ── Registre ──────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Source:
    """Description d'une source publiable au client."""

    key: str
    label: str
    unit: str
    #: Ce que le filtre désigne, ou `None` quand la source n'en prend pas. Sert à l'écran
    #: de configuration : il n'a pas à savoir quelle source attend quoi.
    filter_label: str | None
    load: Callable[[FileStore, str], Awaitable[dict[date, float]]]


SOURCES: dict[str, Source] = {
    source.key: source
    for source in (
        Source(
            key="activity.muscle_group",
            label="Séries d'un groupe musculaire",
            unit="série",
            filter_label="Groupes musculaires",
            load=_muscle_group,
        ),
        Source(
            key="activity.runs",
            label="Distance courue",
            unit="km",
            filter_label=None,
            load=_runs,
        ),
        Source(
            key="activity.duration",
            label="Minutes d'activité",
            unit="min",
            filter_label=None,
            load=_duration,
        ),
        Source(
            key="supplement.intake",
            label="Prises d'un supplément",
            unit="prise",
            filter_label="Supplément",
            load=_supplement_intake,
        ),
        Source(
            key="hydration.intake",
            label="Volume bu",
            unit="ml",
            filter_label=None,
            load=_hydration_intake,
        ),
        Source(
            key="entry_count",
            label="Domaines renseignés",
            unit="domaine",
            filter_label=None,
            load=_entry_count,
        ),
    )
}


async def daily_values(store: FileStore, source: str, filter_: str) -> dict[date, float]:
    """Agrégat quotidien d'une source. Une source inconnue rend une série vide.

    Ne pas lever est délibéré : le fichier des pistes est éditable à la main, et une
    source mal orthographiée doit rendre une grille vide — pas faire tomber l'écran
    entier avec les huit autres pistes.
    """
    known = SOURCES.get(source)
    return await known.load(store, filter_) if known else {}
