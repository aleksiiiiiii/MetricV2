"""Assemblage des agrégats (`AGG-01` → `AGG-04`).

Ce module **n'invente aucun chiffre**. Chaque indicateur est produit par le service du
domaine qui en détient la règle : le poids par `WeightService`, les totaux d'entraînement
par `ActivityStats`, les macros par `NutritionService`. Recalculer ici une moyenne déjà
écrite ailleurs serait le plus sûr moyen d'afficher deux valeurs différentes du même
chiffre selon l'écran ouvert (`HEAT-30`).

## Le coût d'une requête unique

Le tableau de bord ouvre huit fichiers. C'est beaucoup, et c'est pourtant l'économie que
vise `AGG-01` : la seule autre façon d'obtenir la même page serait dix requêtes HTTP
depuis le client, chacune rouvrant les mêmes fichiers.

Deux services différents peuvent demander le même fichier — `settings.csv` est lu par le
poids, la nutrition et l'hydratation. Le cache de `FileStore` sert alors la seconde
lecture sans requête réseau (`STO-06`), si bien qu'un fichier n'est tiré de Nextcloud
**qu'une fois par requête**. Un test le vérifie plutôt que de faire confiance à cette
phrase.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.core.dates import days_between
from app.domains.activity.service import ExerciseService, RunService, WorkoutService
from app.domains.activity.stats import ActivityStats
from app.domains.aggregates.schemas import (
    DashboardView,
    MetricDescriptor,
    MetricSubject,
    SeriesPoint,
    SeriesStats,
    SeriesView,
    Streak,
    StreakDay,
)
from app.domains.app_settings.service import SettingsService
from app.domains.body.models import MEASUREMENT_FIELDS
from app.domains.body.service import MeasurementService, WeightService
from app.domains.hydration.service import HydrationService
from app.domains.nutrition.service import NutritionService
from app.domains.supplements.service import SupplementService
from app.storage.errors import StorageNotFoundError
from app.storage.files import FileStore

#: Profondeur maximale de remontée d'une série. Au-delà, l'information n'ajoute rien et
#: le coût de calcul augmente sans raison. Même borne que les séries de suppléments.
STREAK_LIMIT = 400

#: Fenêtre montrée à côté de la série (`AGG-03`).
RECENT_DAYS = 7

#: Les trois plages de `AGG-04`.
RangeKey = Literal["1m", "3m", "all"]

#: Plages proposées, en jours. « Un mois » vaut 30 jours et non un mois calendaire :
#: deux plages de longueurs inégales selon le mois rendraient deux variations
#: incomparables d'un relevé à l'autre.
RANGES: dict[RangeKey, int | None] = {"1m": 30, "3m": 90, "all": None}

#: Métrique et plage servies avec le tableau de bord quand le client n'en demande pas.
DEFAULT_METRIC = "weight"
DEFAULT_RANGE: RangeKey = "3m"


@dataclass(frozen=True, slots=True)
class Metric:
    """Description d'une métrique suivie.

    Le contrat entre une source et le moteur de séries tient en une fonction rendant des
    couples `(jour, valeur)`. Tout le reste — découpage de plage, statistiques, forme de
    la réponse — est commun, et c'est ce qui rend `AGG-04` générique : ajouter une
    métrique n'ajoute pas une ligne de code de calcul.
    """

    key: str
    label: str
    unit: str
    granularity: str
    load: Callable[[FileStore, str | None], Awaitable[list[tuple[date, float]]]]
    #: Vrai quand la métrique désigne un sujet — un exercice du catalogue.
    parameterised: bool = False


def _catalogue() -> dict[str, Metric]:
    """Métriques suivies, construites depuis les domaines qui les détiennent.

    Les mensurations sont dépliées depuis `MEASUREMENT_FIELDS` plutôt qu'énumérées :
    ajouter une mesure au domaine Corps l'ajoute à ce catalogue sans y toucher.
    """
    metrics: list[Metric] = [
        Metric(
            key="weight",
            label="Poids",
            unit="kg",
            granularity="day",
            load=lambda store, _: WeightService(store).points(),
        ),
        Metric(
            key="hydration",
            label="Hydratation",
            unit="ml",
            granularity="day",
            load=lambda store, _: _hydration_points(store),
        ),
        Metric(
            key="weekly_minutes",
            label="Volume hebdomadaire",
            unit="min",
            granularity="week",
            load=lambda store, _: ActivityStats(store).weekly_minutes(),
        ),
        Metric(
            key="weekly_volume_kg",
            label="Tonnage hebdomadaire",
            unit="kg",
            granularity="week",
            load=lambda store, _: ActivityStats(store).weekly_volume(),
        ),
        Metric(
            key="exercise_load",
            label="Charge par exercice",
            unit="kg",
            granularity="day",
            load=lambda store, subject: ActivityStats(store).exercise_load(subject or ""),
            parameterised=True,
        ),
    ]

    metrics += [
        Metric(
            key=field,
            label=label,
            unit="%" if field == "body_fat_pct" else "cm",
            granularity="day",
            load=(lambda name: lambda store, _: MeasurementService(store).points(name))(field),
        )
        for field, label in MEASUREMENT_FIELDS
    ]

    return {metric.key: metric for metric in metrics}


METRICS: dict[str, Metric] = _catalogue()


async def _hydration_points(store: FileStore) -> list[tuple[date, float]]:
    volumes = await HydrationService(store).daily_volumes()
    return sorted((day, float(value)) for day, value in volumes.items())


class SeriesService:
    """Séries temporelles génériques (`AGG-04`)."""

    def __init__(self, store: FileStore) -> None:
        self._store = store

    async def catalogue(self) -> list[MetricDescriptor]:
        """Métriques choisissables, sujets compris.

        Publier le catalogue évite au client d'en tenir une copie : une liste recopiée
        dans deux langages finit par ne plus décrire la même chose.
        """
        exercises = await ExerciseService(self._store).catalogue()
        subjects = [
            MetricSubject(key=item.exercise_id, label=item.name)
            for item in sorted(exercises, key=lambda item: item.name)
        ]

        return [
            MetricDescriptor(
                key=metric.key,
                label=metric.label,
                unit=metric.unit,
                granularity=metric.granularity,
                subjects=subjects if metric.parameterised else [],
            )
            for metric in METRICS.values()
        ]

    async def series(
        self,
        metric_key: str,
        today: date,
        *,
        range_key: RangeKey = DEFAULT_RANGE,
        subject: str | None = None,
    ) -> SeriesView:
        metric = METRICS.get(metric_key)
        if metric is None:
            raise StorageNotFoundError("Cette métrique n'existe pas.")

        points = await metric.load(self._store, subject)

        # La plage se compte **depuis aujourd'hui**, pas depuis le dernier relevé. C'est
        # le même piège que la tendance du poids (`BODY-05`) : ancrée sur les points, une
        # fenêtre d'un mois couvrirait un an après une pause, et « rien ce mois-ci »
        # s'afficherait comme un mois plein. Une plage vide est une information.
        window = RANGES[range_key]
        if window is not None:
            horizon = today - timedelta(days=window - 1)
            points = [point for point in points if point[0] >= horizon]

        return SeriesView(
            metric=metric.key,
            label=metric.label,
            unit=metric.unit,
            granularity=metric.granularity,
            subject=subject if metric.parameterised else None,
            range=range_key,
            points=[SeriesPoint(date=day, value=value) for day, value in points],
            stats=self._stats([value for _, value in points], points[-1][0] if points else None),
        )

    @staticmethod
    def _stats(values: list[float], latest_date: date | None) -> SeriesStats:
        """Dernier, variation, moyenne, min, max (`AGG-04`).

        La plage vide rend des `None` et non des zéros : dans une application de mesure,
        un faux chiffre est pire qu'un tiret.
        """
        if not values:
            return SeriesStats(count=0)

        return SeriesStats(
            latest=values[-1],
            latest_date=latest_date,
            # Variation sur la plage, pas depuis toujours : c'est ce que le sélecteur de
            # période promet de montrer.
            change=round(values[-1] - values[0], 2) if len(values) >= 2 else None,
            average=round(sum(values) / len(values), 2),
            minimum=min(values),
            maximum=max(values),
            count=len(values),
        )


class DashboardService:
    """Tous les indicateurs de synthèse en une requête (`AGG-01`)."""

    def __init__(self, store: FileStore) -> None:
        self._store = store

    async def view(
        self, today: date, *, metric: str = DEFAULT_METRIC, range_key: RangeKey = DEFAULT_RANGE
    ) -> DashboardView:
        store = self._store

        return DashboardView(
            date=today,
            weight=await WeightService(store).summary(),
            training=await ActivityStats(store).training(today),
            nutrition=await NutritionService(store).totals(today),
            hydration=await HydrationService(store).summary(today),
            supplements=(await SupplementService(store).checklist(today)).ratio,
            streak=await self.streak(today),
            series=await SeriesService(store).series(metric, today, range_key=range_key),
            highlight=(await SettingsService(store).values()).heatmap_metric,
        )

    # ── Série d'assiduité (`AGG-03`) ──────────────────

    async def sources(self) -> dict[str, set[date]]:
        """Les sept sources de l'assiduité de suivi, chacune réduite à ses jours.

        Les sept nommées par `AGG-03` : poids, mensurations, courses, séances, repas,
        hydratation, prises. Chaque domaine dit lui-même à quel jour appartient sa ligne
        — l'hydratation et les repas portent un horodatage, dont le rattachement au jour
        local n'a qu'une implémentation (`HEAT-32`).
        """
        hydration = await HydrationService(self._store).daily_volumes()

        return {
            "weight": {day for day, _ in await WeightService(self._store).points()},
            "measurements": await MeasurementService(self._store).days(),
            "runs": {row.model.date for row in await RunService(self._store).all()},
            "workouts": {row.model.date for row in await WorkoutService(self._store).all()},
            "meals": await NutritionService(self._store).meal_days(),
            "hydration": {day for day, volume in hydration.items() if volume > 0},
            "supplements": await SupplementService(self._store).intake_days(),
        }

    async def streak(self, today: date) -> Streak:
        by_source = await self.sources()

        active: dict[date, list[str]] = {}
        for name, days in by_source.items():
            for day in days:
                active.setdefault(day, []).append(name)
        for names in active.values():
            names.sort()

        return Streak(
            current=self._current(set(active), today),
            longest=self._longest(set(active)),
            active_days=len(active),
            last_seven=[
                StreakDay(date=day, active=day in active, sources=active.get(day, []))
                # Plage complète : un jour sans rien est retourné vide, pas omis.
                for day in days_between(today - timedelta(days=RECENT_DAYS - 1), today)
            ],
        )

    @staticmethod
    def _current(days: set[date], today: date) -> int:
        """Jours consécutifs en remontant depuis aujourd'hui.

        **La journée en cours ne casse pas la série tant qu'elle n'est pas terminée** :
        si rien n'est encore saisi aujourd'hui, on compte à partir d'hier. Sans cette
        règle, une série de quarante jours tomberait à zéro chaque matin au réveil, pour
        remonter à quarante et un le soir venu — un compteur qui ment la moitié du temps.
        """
        cursor = today if today in days else today - timedelta(days=1)
        count = 0
        while cursor in days and count < STREAK_LIMIT:
            count += 1
            cursor -= timedelta(days=1)
        return count

    @staticmethod
    def _longest(days: set[date]) -> int:
        """Plus longue série jamais tenue.

        Parcours des seuls jours actifs, triés : compter jour par jour sur trois ans de
        calendrier coûterait mille itérations pour trente relevés.
        """
        longest = 0
        run = 0
        previous: date | None = None

        for day in sorted(days):
            run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
            longest = max(longest, run)
            previous = day

        return longest
