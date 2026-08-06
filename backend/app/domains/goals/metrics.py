"""Les cinq métriques sur lesquelles un objectif peut porter (`GOAL-04`).

**Ce module ne définit aucune métrique.** Il en désigne cinq parmi celles du registre
`app.domains.aggregates.service.METRICS`, et leur ajoute la seule chose que le registre
n'a pas à savoir : comment réduire une série en une valeur *courante*, et entre quelles
bornes une cible reste plausible.

Le partage est délibéré. Le libellé, l'unité, la granularité et le chargement des points
appartiennent au registre, qui les sert déjà à `/api/aggregates/series` ; les recopier ici
donnerait deux tables à tenir en phase, et « la même constante écrite à deux endroits tient
jusqu'au premier oubli ». Les trois métriques que `GOAL-04` demandait et qui manquaient —
séances par semaine, kilomètres par semaine, protéines par jour — ont donc été **ajoutées
au registre**, où les séries génériques en profitent au passage.

## Deux façons de lire « où j'en suis »

`latest` — le **poids**. Une pesée est une mesure : la dernière vaut, et moyenner les
relevés lisserait précisément ce que l'objectif suit.

`rate` — les quatre autres. Ce sont des cadences : « trois séances par semaine »,
« 150 g de protéines par jour ». Elles se comptent sur la **fenêtre entière**, périodes
sans donnée comprises. Une semaine sans séance compte zéro et non rien : c'est déjà ce que
fait `HydrationService._average`, qui moyenne sur trente jours zéros compris, et répondre
autrement ici donnerait deux moyennes d'hydratation différentes selon l'écran ouvert.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.aggregates.service import METRICS
from app.domains.goals.progress import Reduction


@dataclass(frozen=True, slots=True)
class GoalMetric:
    """Ce qu'il faut savoir en plus du registre pour en faire un objectif."""

    #: Clé du registre `METRICS`. C'est lui qui porte le libellé, l'unité et les points.
    key: str
    reduction: Reduction
    #: Bornes de vraisemblance d'une **cible** (`API-06`). Plus serrées que celles de la
    #: saisie : `WeightKg` accepte 3 kg parce qu'un fichier ancien pourrait le contenir,
    #: mais personne ne se fixe 3 kg pour objectif. Hors bornes, on écarte.
    minimum: float
    maximum: float
    #: Sens de l'objectif, pour la consigne envoyée au modèle. Le calcul de progression,
    #: lui, n'en a pas besoin : il se repère sur le point de départ (voir `progress.py`).
    hint: str


#: Les cinq de `GOAL-04`, dans l'ordre où l'écran les propose.
GOAL_METRICS: dict[str, GoalMetric] = {
    metric.key: metric
    for metric in (
        GoalMetric(
            key="weight",
            reduction="latest",
            minimum=30,
            maximum=300,
            hint="peut monter ou descendre selon le point de départ",
        ),
        GoalMetric(
            key="weekly_sessions",
            reduction="rate",
            minimum=1,
            maximum=14,
            hint="nombre de séances par semaine, à faire monter",
        ),
        GoalMetric(
            key="weekly_distance_km",
            reduction="rate",
            minimum=1,
            maximum=300,
            hint="kilomètres courus par semaine, à faire monter",
        ),
        GoalMetric(
            key="daily_protein_g",
            reduction="rate",
            minimum=20,
            maximum=400,
            hint="grammes de protéines par jour, à faire monter",
        ),
        GoalMetric(
            key="hydration",
            reduction="rate",
            minimum=500,
            maximum=8000,
            hint="millilitres bus par jour, à faire monter",
        ),
    )
}

# Garde structurelle : une clé d'objectif qui ne serait pas dans le registre produirait un
# objectif adoptable et impossible à mesurer — l'écran afficherait une cible et un tiret,
# indéfiniment. Mieux vaut que l'application refuse de démarrer.
_orphans = sorted(set(GOAL_METRICS) - set(METRICS))
if _orphans:  # pragma: no cover - erreur de câblage, vérifiée par un test dédié
    raise RuntimeError(f"Métriques d'objectif absentes du registre : {', '.join(_orphans)}")


def label_of(key: str) -> str:
    """Libellé du registre, ou la clé si elle lui est étrangère."""
    metric = METRICS.get(key)
    return metric.label if metric else key


def unit_of(key: str) -> str:
    """Unité du registre — jamais recopiée par le client, jamais devinée."""
    metric = METRICS.get(key)
    return metric.unit if metric else ""


def granularity_of(key: str) -> str:
    """`day` ou `week`. C'est elle qui décide de la fenêtre d'observation."""
    metric = METRICS.get(key)
    return metric.granularity if metric else "day"


__all__ = [
    "GOAL_METRICS",
    "GoalMetric",
    "Reduction",
    "granularity_of",
    "label_of",
    "unit_of",
]
