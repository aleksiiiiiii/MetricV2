"""Endpoints de la nutrition (`NUT-01` → `NUT-10`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Path, Query, Response, UploadFile, status

from app.core.dates import today_local
from app.core.deps import StoreDep
from app.domains.ai.deps import AiServiceDep
from app.domains.nutrition.photos import MAX_BYTES, PhotoError
from app.domains.nutrition.schemas import (
    Favorite,
    FavoritePayload,
    Meal,
    MealEstimate,
    MealPayload,
    NutritionView,
)
from app.domains.nutrition.service import NutritionService
from app.storage.errors import StorageConflictError

router = APIRouter(prefix="/nutrition", tags=["nutrition"])

RowId = Annotated[int, Path(ge=0)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]

#: Un an. Le chemin d'une photo contient son horodatage et un aléa : il ne désigne jamais
#: deux contenus différents, la réponse est donc cachable durablement (`NUT-08`).
PHOTO_CACHE = "private, max-age=31536000, immutable"


def _token(value: str | None) -> str:
    if not value:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.", detail="en-tête If-Match absent"
        )
    return value.strip('"')


@router.get("", response_model=NutritionView, summary="Repas et totaux du jour")
async def read(
    store: StoreDep,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
) -> NutritionView:
    """Totaux, repas du jour et favoris en une requête. Sans `limit`, la liste est
    complète (`NUT-07`)."""
    return await NutritionService(store).view(today_local(), limit=limit)


@router.post(
    "",
    response_model=Meal,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un repas",
)
async def create(
    store: StoreDep,
    meal_type: Annotated[str, Form(max_length=80)],
    comment: Annotated[str | None, Form(max_length=500)] = None,
    photo: Annotated[UploadFile | None, File()] = None,
    protein_g: Annotated[float | None, Form(ge=0, le=500)] = None,
    added_sugar_g: Annotated[float | None, Form(ge=0, le=1000)] = None,
    calories: Annotated[int | None, Form(ge=0, le=10000)] = None,
    source: Annotated[str, Form(pattern="^(manual|ai)$")] = "manual",
) -> Meal:
    """Photo et/ou description, au moins l'un des deux (`NUT-01`).

    Le formulaire est en multipart : un fichier ne se transporte pas en JSON. Le type
    déclaré par le client est ignoré — c'est la signature du contenu qui décide.

    `source=ai` marque un repas dont les macros viennent d'une estimation **acceptée**
    (`NUT-04`). Elle le reste même corrigée au doigt avant l'enregistrement : ce que la
    colonne raconte, c'est d'où vient la ligne, et une estimation retouchée n'est pas une
    valeur qu'on a lue sur un emballage. Refuser l'estimation la ramène à `manual`.
    """
    data = await photo.read() if photo is not None else None
    if photo is not None:
        await photo.close()

    text = (comment or "").strip()
    if not data and not text:
        raise PhotoError("Un repas a besoin d'une photo ou d'une description.")

    return await NutritionService(store).create(
        meal_type=meal_type,
        comment=text or None,
        photo=data,
        protein_g=protein_g,
        added_sugar_g=added_sugar_g,
        calories=calories,
        source=source,
    )


# ── Estimation assistée (`NUT-04`) ────────────────────


@router.post("/analyze", response_model=MealEstimate, summary="Estimer une assiette")
async def analyze(
    ai: AiServiceDep,
    photo: Annotated[UploadFile, File()],
) -> MealEstimate:
    """Propose protéines, sucres ajoutés et calories depuis une photo (`NUT-04`).

    **Rien n'est écrit** : ni ligne, ni fichier photo. La photo n'est même pas rangée sur
    Nextcloud — elle est réduite, envoyée, et oubliée. C'est l'enregistrement du repas,
    ensuite, qui décide de ce qui reste.

    `200` seulement si l'on a une proposition. Sans clé, cet endpoint ne s'exécute pas et
    rend `ai_unavailable` : l'écran continue de proposer la saisie manuelle (`IA-07`).
    """
    data = await photo.read()
    await photo.close()
    return await NutritionService.estimate(ai, data)


@router.post(
    "/{row_id}/analyze",
    response_model=MealEstimate,
    summary="Estimer un repas déjà enregistré",
)
async def analyze_meal(row_id: RowId, store: StoreDep, ai: AiServiceDep) -> MealEstimate:
    """Même estimation, depuis la photo déjà rangée d'un repas (`NUT-04`).

    Ne modifie pas le repas : la proposition remonte à l'écran, qui la fait valider par
    une correction ordinaire (`PATCH`) — sous garde de jeton comme toute écriture.
    """
    return await NutritionService(store).estimate_meal(ai, row_id)


@router.patch("/{row_id}", response_model=Meal, summary="Corriger un repas")
async def update(
    row_id: RowId, payload: MealPayload, store: StoreDep, if_match: IfMatch = None
) -> Meal:
    """Corrige l'heure, le type, le commentaire ou les macros. Photo et provenance
    d'origine sont préservées (`NUT-09`)."""
    return await NutritionService(store).update(row_id, _token(if_match), payload)


@router.delete("/{row_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un repas")
async def delete(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    await NutritionService(store).delete(row_id, _token(if_match))


@router.get(
    "/photos/{relative:path}",
    summary="Servir une photo de repas",
    response_class=Response,
)
async def photo(relative: str, store: StoreDep) -> Response:
    """Service authentifié des photos (`NUT-08`).

    L'endpoint est **derrière l'authentification** comme toute route de données, et le
    chemin est validé contre une forme stricte avant la moindre lecture. Un chemin qui ne
    ressemble pas à une de nos photos rend `404` — jamais un message qui renseignerait
    sur l'arborescence.
    """
    data, kind = await NutritionService(store).read_photo(relative)
    return Response(
        content=data,
        media_type=kind,
        headers={
            "Cache-Control": PHOTO_CACHE,
            # Une image servie depuis notre domaine ne doit pas être interprétée
            # autrement que comme une image, quoi qu'en pense le navigateur.
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@router.get("/limits", response_model=dict[str, int], summary="Bornes de téléversement")
def limits() -> dict[str, int]:
    """Le client affiche la limite plutôt que de la deviner."""
    return {"max_photo_bytes": MAX_BYTES}


# ── Favoris (`NUT-10`) ────────────────────────────────


@router.post(
    "/favorites",
    response_model=Favorite,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer un repas favori",
)
async def add_favorite(payload: FavoritePayload, store: StoreDep) -> Favorite:
    return await NutritionService(store).add_favorite(payload)


@router.post(
    "/favorites/{favorite_id}/replay",
    response_model=Meal,
    status_code=status.HTTP_201_CREATED,
    summary="Rejouer un repas favori",
)
async def replay_favorite(favorite_id: str, store: StoreDep) -> Meal:
    """En une action, sans photo ni IA : couvre les repas identiques du quotidien."""
    return await NutritionService(store).replay_favorite(favorite_id)


@router.delete(
    "/favorites/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer un repas favori",
)
async def remove_favorite(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    await NutritionService(store).remove_favorite(row_id, _token(if_match))
