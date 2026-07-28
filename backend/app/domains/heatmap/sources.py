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
from datetime import date, datetime

from app.core.dates import local_day_of
from app.core.parsing import pace_min_per_km
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


@dataclass(frozen=True, slots=True)
class DayDetail:
    """Ce qui compose la valeur d'un jour (`HEAT-29`).

    Des **nombres**, pas des phrases. Le client compose son libellé et le formate ; le
    serveur ne lui envoie pas « 4 × 8 à 80 kg » sous peine de décider à sa place de la
    virgule décimale et de l'unité affichée. Les champs sont larges parce que quatre
    sources très différentes s'y expriment, et vides quand ils n'ont pas de sens.
    """

    label: str
    #: Contribution de cette ligne au total du jour.
    value: float
    unit: str
    time: datetime | None = None
    #: Musculation.
    sets: int | None = None
    reps: int | None = None
    weight_kg: float | None = None
    muscle_group: str | None = None
    #: Course et séances.
    distance_km: float | None = None
    duration_min: float | None = None
    pace_min_km: float | None = None
    #: Suppléments.
    dose: float | None = None
    dose_unit: str | None = None
    note: str | None = None


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


# ── Détail par source (`HEAT-29`) ─────────────────────


async def _muscle_group_detail(store: FileStore, filter_: str, day: date) -> list[DayDetail]:
    groups = set(split_filter(filter_))
    return [
        DayDetail(
            label=row.model.exercise_name,
            value=row.model.sets,
            unit="série",
            sets=row.model.sets,
            reps=row.model.reps,
            weight_kg=row.model.weight_kg,
            muscle_group=row.model.muscle_group,
            note=row.model.note,
        )
        for row in await ExerciseService(store).log_entries()
        if row.model.date == day and (not groups or row.model.muscle_group in groups)
    ]


async def _runs_detail(store: FileStore, filter_: str, day: date) -> list[DayDetail]:
    del filter_
    return [
        DayDetail(
            label="Course",
            value=row.model.distance_km,
            unit="km",
            distance_km=row.model.distance_km,
            duration_min=row.model.duration_min,
            pace_min_km=row.model.pace_min_km
            or pace_min_per_km(row.model.distance_km, row.model.duration_min),
            note=row.model.note,
        )
        for row in await RunService(store).all()
        if row.model.date == day
    ]


async def _duration_detail(store: FileStore, filter_: str, day: date) -> list[DayDetail]:
    del filter_
    items = [
        DayDetail(
            label="Course",
            value=row.model.duration_min,
            unit="min",
            distance_km=row.model.distance_km,
            duration_min=row.model.duration_min,
            note=row.model.note,
        )
        for row in await RunService(store).all()
        if row.model.date == day
    ]
    items += [
        DayDetail(
            label=row.model.type,
            value=row.model.duration_min,
            unit="min",
            duration_min=row.model.duration_min,
            note=row.model.note,
        )
        for row in await WorkoutService(store).all()
        if row.model.date == day
    ]
    return items


async def _supplement_detail(store: FileStore, filter_: str, day: date) -> list[DayDetail]:
    schedule_id = filter_.strip()
    return [
        DayDetail(
            label=row.model.name,
            value=1,
            unit="prise",
            time=row.model.datetime_,
            dose=row.model.dose,
            dose_unit=row.model.unit,
        )
        for row in await SupplementService(store).intakes()
        if local_day_of(row.model.datetime_) == day
        and (not schedule_id or row.model.schedule_id == schedule_id)
    ]


async def _hydration_detail(store: FileStore, filter_: str, day: date) -> list[DayDetail]:
    del filter_
    return [
        DayDetail(
            label=intake.kind or "Boisson",
            value=intake.volume_ml,
            unit="ml",
            time=intake.datetime,
        )
        for intake in (await HydrationService(store).view(day, days=1)).today
    ]


async def _entry_count_detail(store: FileStore, filter_: str, day: date) -> list[DayDetail]:
    del filter_
    labels = {
        "weight": "Poids",
        "measurements": "Mensurations",
        "runs": "Course",
        "workouts": "Séance",
        "meals": "Repas",
        "hydration": "Hydratation",
        "supplements": "Suppléments",
    }
    sources = await DashboardService(store).sources()
    return [
        DayDetail(label=labels.get(name, name), value=1, unit="domaine")
        for name, days in sorted(sources.items())
        if day in days
    ]


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
    #: Ce qui compose la valeur d'un jour (`HEAT-29`). Chaque cellule est explorable.
    explain: Callable[[FileStore, str, date], Awaitable[list[DayDetail]]] | None = None


SOURCES: dict[str, Source] = {
    source.key: source
    for source in (
        Source(
            key="activity.muscle_group",
            label="Séries d'un groupe musculaire",
            unit="série",
            filter_label="Groupes musculaires",
            load=_muscle_group,
            explain=_muscle_group_detail,
        ),
        Source(
            key="activity.runs",
            label="Distance courue",
            unit="km",
            filter_label=None,
            load=_runs,
            explain=_runs_detail,
        ),
        Source(
            key="activity.duration",
            label="Minutes d'activité",
            unit="min",
            filter_label=None,
            load=_duration,
            explain=_duration_detail,
        ),
        Source(
            key="supplement.intake",
            label="Prises d'un supplément",
            unit="prise",
            filter_label="Supplément",
            load=_supplement_intake,
            explain=_supplement_detail,
        ),
        Source(
            key="hydration.intake",
            label="Volume bu",
            unit="ml",
            filter_label=None,
            load=_hydration_intake,
            explain=_hydration_detail,
        ),
        Source(
            key="entry_count",
            label="Domaines renseignés",
            unit="domaine",
            filter_label=None,
            load=_entry_count,
            explain=_entry_count_detail,
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


async def explain_day(store: FileStore, source: str, filter_: str, day: date) -> list[DayDetail]:
    """Détail sous-jacent d'une cellule (`HEAT-29`). Vide si la source ne sait pas."""
    known = SOURCES.get(source)
    if known is None or known.explain is None:
        return []
    return await known.explain(store, filter_, day)
