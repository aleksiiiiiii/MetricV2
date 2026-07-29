"""Endpoints du moteur d'assiduité (spec `HEAT` v2, §8).

Deux familles, et l'ordre de déclaration compte.

* **Configuration** — pistes, cadences, plages neutralisées. Posée au lot L09.
* **Lecture** — grilles, statistiques, détail d'un jour. Publiée au lot L11 ; tout le
  calcul existait déjà dans `GridService`, il n'y avait qu'à l'exposer.

`GET /heatmap/{track_id}` est déclaré **après** `/heatmap/tracks` : FastAPI retient la
première route qui correspond, et l'ordre inverse ferait chercher une piste nommée
« tracks ».
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, status

from app.core.dates import today_local
from app.core.deps import StoreDep
from app.core.exceptions import ValidationFailedError
from app.domains.heatmap.cache import GridCache
from app.domains.heatmap.engine import Range
from app.domains.heatmap.grids import GridService
from app.domains.heatmap.schemas import (
    DayInspection,
    GridsView,
    GridView,
    OffDay,
    OffDayPayload,
    Order,
    Track,
    TrackImpact,
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

#: Profondeur maximale d'une plage demandée, en jours.
#:
#: La plage par défaut en fait 371. Le plafond n'est pas là pour contraindre l'écran mais
#: pour qu'un paramètre d'URL ne puisse pas demander mille ans de grille : chaque jour
#: coûte une cellule en mémoire et une entrée de cache, et personne ne lit dix ans
#: d'assiduité.
MAX_SPAN_DAYS = 1500


def _window(from_: date | None, to: date | None) -> Range | None:
    """Plage demandée, ou `None` pour laisser le moteur poser la sienne (`HEAT-31`).

    Les deux bornes vont ensemble : n'en donner qu'une décrirait une plage dont l'autre
    extrémité dépendrait d'un défaut invisible dans l'URL.
    """
    if from_ is None and to is None:
        return None
    if from_ is None or to is None:
        raise ValidationFailedError("Renseigne les deux bornes de la plage, ou aucune.")
    if to < from_:
        raise ValidationFailedError("La fin de la plage précède son début.")
    if (to - from_).days + 1 > MAX_SPAN_DAYS:
        raise ValidationFailedError(f"Plage trop large : {MAX_SPAN_DAYS} jours au maximum.")
    return Range(start=from_, end=to)


From = Annotated[date | None, Query(alias="from", description="Premier jour, inclus")]
To = Annotated[date | None, Query(description="Dernier jour, inclus")]


def get_grid_cache(request: Request) -> GridCache:
    """Cache des grilles, attaché à l'application et non à la requête.

    Le mémoriser par requête ne servirait à rien : c'est d'un affichage à l'autre que le
    recalcul se répète.
    """
    cache = getattr(request.app.state, "grid_cache", None)
    if not isinstance(cache, GridCache):  # pragma: no cover - erreur de câblage
        raise RuntimeError("« grid_cache » n'a pas été initialisé par le lifespan.")
    return cache


CacheDep = Annotated[GridCache, Depends(get_grid_cache)]


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


@router.post(
    "/tracks/{track_id}/preview",
    response_model=TrackImpact,
    summary="Chiffrer une modification avant de la valider",
)
async def preview_track(
    track_id: TrackId, payload: TrackUpdate, store: StoreDep, cache: CacheDep
) -> TrackImpact:
    """`HEAT-20`, décision **D4**.

    « Changer un seuil réécrit tout l'historique, et doit être annoncé à l'utilisateur ».
    Annoncer sans chiffrer n'aide personne à décider : cet endpoint rend le nombre de
    journées qui changeraient de camp, **avant** que quoi que ce soit ne soit écrit.

    `POST` parce qu'il porte un corps de requête, et non parce qu'il modifie : il ne
    touche aucun fichier.
    """
    return await GridService(store, cache).impact(track_id, payload)


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


# ── Lecture des grilles (`HEAT-24` → `HEAT-29`) ───────
#
# Déclarées après toutes les routes `/tracks` et `/off-days` : `/{track_id}` capterait
# ces chemins s'il venait avant.


@router.get("", response_model=GridsView, summary="Grilles de plusieurs pistes")
async def read_grids(
    store: StoreDep,
    cache: CacheDep,
    tracks: Annotated[
        str | None, Query(description="Identifiants séparés par des virgules")
    ] = None,
    from_: From = None,
    to: To = None,
) -> GridsView:
    """Tout l'écran d'assiduité en **une** requête (`HEAT-25`).

    Neuf grilles, c'est neuf fois les mêmes fichiers sources. Les demander une par une
    coûterait neuf allers-retours au client et autant de relectures au serveur ; groupées,
    elles partagent le cache d'une seule requête.

    Sans `tracks`, toutes les pistes actives sont rendues, dans l'ordre d'affichage.
    """
    await TrackService(store).ensure_seeded()
    wanted = [chunk.strip() for chunk in tracks.split(",") if chunk.strip()] if tracks else None
    return await GridService(store, cache).multi_view(wanted, window=_window(from_, to))


@router.get("/{track_id}", response_model=GridView, summary="Grille d'une piste")
async def read_grid(
    track_id: TrackId, store: StoreDep, cache: CacheDep, from_: From = None, to: To = None
) -> GridView:
    """Grille, statistiques et cadence d'une piste (`HEAT-24`, `HEAT-26`).

    La plage par défaut couvre 53 semaines pleines alignées sur le lundi (`HEAT-31`,
    décision **D6**). Elle se termine au **dimanche de la semaine en cours** : les jours
    qui n'ont pas encore eu lieu sont rendus `off`, avec la nuance `future`.
    """
    return await GridService(store, cache).view(track_id, window=_window(from_, to))


@router.get(
    "/{track_id}/day/{day}",
    response_model=DayInspection,
    summary="Détail d'un jour",
)
async def read_day(track_id: TrackId, day: date, store: StoreDep, cache: CacheDep) -> DayInspection:
    """Ce qui compose une cellule (`HEAT-29`).

    Une grille qui ne s'explore pas ne se vérifie pas : voir « 12 séries » sans pouvoir
    demander lesquelles laisse l'utilisateur sans recours quand le chiffre le surprend.

    Un jour à venir est refusé — il n'a rien à montrer, et le demander est le signe d'une
    URL forgée à la main.
    """
    if day > today_local():
        raise ValidationFailedError("Ce jour n'est pas encore arrivé.")
    return await GridService(store, cache).inspect(track_id, day)
