"""Le registre des métriques suivies (`AGG-04`).

**Un seul endroit du projet où « séances par semaine » a une définition.** Le moteur de
séries en tire ses courbes, les objectifs en tirent leur progression, l'assistant en tire
ses tendances : une seconde table donnerait deux réponses au même mot.

## Pourquoi il a quitté `service.py`

Il y est né, et il y a vécu jusqu'à ce que le tableau de bord serve l'objectif en cours.
`aggregates/schemas.py` importe alors `goals/schemas.py` — et `goals` importait ce
registre depuis `aggregates/service.py`, lequel importe `aggregates/schemas.py`. Le
cercle se refermait au chargement, sur un `DashboardView` qui n'existait pas encore.

Le remède est celui qui a déjà sorti `fold` du domaine Activité vers `core/text.py` : ce
dont deux couches ont besoin ne vit dans aucune des deux. Ce module ne connaît que les
services de domaine qui détiennent les données — il n'importe **aucun schéma d'agrégat**,
et c'est ce qui doit rester vrai.

`service.py` réexporte tout ce qui est ici sous les mêmes noms : c'est l'adresse que le
routeur, les objectifs et six tests connaissent, et la déplacer n'apporterait rien.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.domains.activity.service import CircuitLoadService
from app.domains.activity.stats import ActivityStats
from app.domains.body.models import MEASUREMENT_FIELDS
from app.domains.body.service import MeasurementService, WeightService
from app.domains.hydration.service import HydrationService
from app.domains.nutrition.service import NutritionService
from app.storage.files import FileStore

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
    load: Callable[[FileStore, str | None], Awaitable[Sequence[tuple[date, float]]]]
    #: Vrai quand la métrique désigne un sujet — un exercice du catalogue.
    parameterised: bool = False


def _catalogue() -> dict[str, Metric]:
    """Métriques suivies, construites depuis les domaines qui les détiennent.

    Les mensurations sont dépliées depuis `MEASUREMENT_FIELDS` plutôt qu'énumérées :
    ajouter une mesure au domaine Corps l'ajoute à ce catalogue sans y toucher.

    `daily_protein_g`, `weekly_sessions` et `weekly_distance_km` sont arrivées avec les
    objectifs (`GOAL-04`), qui avaient besoin de les mesurer. Elles ont leur place **ici**
    et non dans le domaine Objectifs : une seconde table de métriques aurait donné deux
    définitions de « séances par semaine » à tenir en phase, et les séries génériques de
    `AGG-04` y gagnent trois courbes qu'elles n'avaient pas.
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
            key="daily_protein_g",
            label="Protéines",
            unit="g",
            granularity="day",
            load=lambda store, _: NutritionService(store).protein_points(),
        ),
        Metric(
            key="weekly_minutes",
            label="Volume hebdomadaire",
            unit="min",
            granularity="week",
            load=lambda store, _: ActivityStats(store).weekly_minutes(),
        ),
        Metric(
            key="weekly_sessions",
            label="Séances par semaine",
            unit="séances",
            granularity="week",
            load=lambda store, _: ActivityStats(store).weekly_sessions(),
        ),
        Metric(
            key="weekly_distance_km",
            label="Distance hebdomadaire",
            unit="km",
            granularity="week",
            load=lambda store, _: ActivityStats(store).weekly_distance(),
        ),
        # Le tonnage hebdomadaire est parti avec `exercise_log.csv`. Il ne revient pas :
        # un tabata au temps porte `reps = -1`, et le multiplier par une charge donnerait
        # un tonnage négatif (**C4** de `docs/charges.md`).
        Metric(
            key="exercise_load",
            label="Charge par exercice",
            unit="kg",
            granularity="day",
            # Le sujet est désormais le **nom** de l'exercice de tabata, pas un
            # `exercise_id` du catalogue disparu. L'historique est celui des décisions de
            # charge, pas d'un maximum du jour — voir `CircuitLoadService.load_history`.
            load=lambda store, subject: CircuitLoadService(store).load_history(subject or ""),
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
