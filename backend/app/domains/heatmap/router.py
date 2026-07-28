"""Endpoints de configuration du moteur d'assiduité (spec `HEAT` v2, §8).

Le lot L09 pose la configuration ; les grilles et les statistiques — `GET /heatmap/{id}`,
`GET /heatmap?tracks=…`, le détail d'un jour — arrivent au lot L10, quand le moteur saura
juger un jour.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, status

from app.core.deps import StoreDep
from app.domains.heatmap.schemas import (
    OffDay,
    OffDayPayload,
    Order,
    Track,
    TrackPayload,
    TrackSaved,
    TracksView,
    TrackUpdate,
)
from app.domains.heatmap.service import TrackService
from app.storage.errors import StorageConflictError

router = APIRouter(prefix="/heatmap", tags=["assiduité"])

TrackId = Annotated[str, Path(min_length=1, max_length=40)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]


def _guard(if_match: str | None) -> str:
    """Un `If-Match` absent est un conflit, jamais une permission (`STO-05`)."""
    if not if_match:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.", detail="en-tête If-Match absent"
        )
    return if_match.strip('"')


@router.get("/tracks", response_model=TracksView, summary="Pistes et catalogue de sources")
async def read_tracks(store: StoreDep) -> TracksView:
    """Toute la configuration d'assiduité en une requête.

    Les pistes par défaut sont amorcées au premier appel : ouvrir l'écran pour la première
    fois doit montrer neuf grilles peuplées de son propre historique, pas un formulaire de
    création vide.
    """
    service = TrackService(store)
    await service.ensure_seeded()
    return await service.view()


@router.post(
    "/tracks", response_model=Track, status_code=status.HTTP_201_CREATED, summary="Créer une piste"
)
async def create_track(payload: TrackPayload, store: StoreDep) -> Track:
    """`HEAT-18`. Ajouter une piste ne demande aucune ligne de code — seulement une source
    du catalogue, un filtre, un seuil et une cadence."""
    return await TrackService(store).create(payload)


@router.patch("/tracks/{track_id}", response_model=TrackSaved, summary="Modifier une piste")
async def update_track(
    track_id: TrackId, payload: TrackUpdate, store: StoreDep, if_match: IfMatch = None
) -> TrackSaved:
    """`HEAT-19`, `HEAT-20`.

    La réponse dit ce que la modification a impliqué : une cadence ne vaut que pour
    l'avenir, un seuil rejuge tout l'historique. L'asymétrie est annoncée, pas subie.
    """
    return await TrackService(store).update(track_id, _guard(if_match), payload)


@router.delete(
    "/tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une piste"
)
async def delete_track(track_id: TrackId, store: StoreDep, if_match: IfMatch = None) -> None:
    """`HEAT-21`. N'efface **aucune** donnée source : séries, kilomètres et prises restent
    dans les fichiers des domaines de saisie. Pour conserver la grille sans l'afficher,
    la voie normale est la désactivation."""
    await TrackService(store).delete(track_id, _guard(if_match))


@router.post("/tracks/order", response_model=list[Track], summary="Réordonner les pistes")
async def reorder_tracks(payload: Order, store: StoreDep) -> list[Track]:
    """`HEAT-22`. L'ordre est un réglage utilisateur."""
    return await TrackService(store).reorder(payload.track_ids)


@router.post("/tracks/{track_id}/highlight", response_model=TracksView, summary="Mettre en avant")
async def highlight_track(track_id: TrackId, store: StoreDep) -> TracksView:
    """`HEAT-22`. La piste mise en avant est le réglage `heatmap_metric`, celui-là même que
    le tableau de bord expose sous `highlight`."""
    service = TrackService(store)
    await service.highlight(track_id)
    return await service.view()


@router.post(
    "/off-days",
    response_model=OffDay,
    status_code=status.HTTP_201_CREATED,
    summary="Neutraliser une plage",
)
async def create_off_days(payload: OffDayPayload, store: StoreDep) -> OffDay:
    """`HEAT-06`. Maladie, voyage, deload : ces jours ne comptent ni comme réussite ni
    comme échec. Une grippe ne casse pas une série de quatre-vingt-dix jours."""
    return await TrackService(store).add_off_days(payload)


@router.delete(
    "/off-days/{off_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Annuler une neutralisation",
)
async def delete_off_days(
    off_id: Annotated[str, Path(min_length=1, max_length=40)],
    store: StoreDep,
    if_match: IfMatch = None,
) -> None:
    await TrackService(store).remove_off_days(off_id, _guard(if_match))
