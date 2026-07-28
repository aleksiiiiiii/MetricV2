"""Endpoints des agrégats (`AGG-01` → `AGG-04`)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.core.dates import today_local
from app.core.deps import StoreDep
from app.domains.aggregates.schemas import DashboardView, MetricDescriptor, SeriesView
from app.domains.aggregates.service import (
    DEFAULT_METRIC,
    DEFAULT_RANGE,
    DashboardService,
    SeriesService,
)

router = APIRouter(prefix="/aggregates", tags=["agrégats"])

#: Les trois plages de `AGG-04`. Déclarées en `Literal` : une plage inconnue est refusée
#: par le contrat lui-même, sans code de garde et avec un message de validation utile.
Range = Annotated[Literal["1m", "3m", "all"], Query(description="Plage de la série")]
Metric = Annotated[str, Query(min_length=1, max_length=40, description="Clé de la métrique")]
Subject = Annotated[str | None, Query(max_length=40, description="Sujet, si la métrique en exige")]


@router.get("/dashboard", response_model=DashboardView, summary="Tous les indicateurs de synthèse")
async def dashboard(
    store: StoreDep,
    metric: Metric = DEFAULT_METRIC,
    range: Range = DEFAULT_RANGE,
) -> DashboardView:
    """Le tableau de bord en une requête (`AGG-01`).

    La série du graphique est incluse pour que la première peinture de l'écran n'en
    demande pas une seconde ; `metric` et `range` permettent au client de recharger la
    page sur la métrique que l'utilisateur regardait.
    """
    return await DashboardService(store).view(today_local(), metric=metric, range_key=range)


@router.get("/metrics", response_model=list[MetricDescriptor], summary="Métriques suivies")
async def metrics(store: StoreDep) -> list[MetricDescriptor]:
    """Catalogue des séries disponibles, pour que le sélecteur n'en code aucune."""
    return await SeriesService(store).catalogue()


@router.get("/series", response_model=SeriesView, summary="Série temporelle d'une métrique")
async def series(
    store: StoreDep,
    metric: Metric = DEFAULT_METRIC,
    range: Range = DEFAULT_RANGE,
    subject: Subject = None,
) -> SeriesView:
    """Un seul contrat pour toute métrique suivie (`AGG-04`)."""
    return await SeriesService(store).series(
        metric, today_local(), range_key=range, subject=subject
    )
