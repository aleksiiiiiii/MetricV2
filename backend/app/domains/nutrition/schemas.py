"""Formes échangées pour la nutrition (`NUT-01` → `NUT-10`)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.validation import Calories, Label, Note, PastDateTime, ProteinG, SugarG


class MealPayload(BaseModel):
    """Correction d'un repas (`NUT-05`, `NUT-09`).

    La création passe par un formulaire multipart — un fichier ne se transporte pas en
    JSON — et ses champs sont déclarés directement sur l'endpoint.
    """

    meal_type: Label
    comment: Note | None = None
    protein_g: ProteinG | None = None
    added_sugar_g: SugarG | None = None
    calories: Calories | None = None
    datetime: PastDateTime | None = None
    #: Provenance, **seulement quand elle change** (`NUT-04`).
    #:
    #: Absente — le cas de toute correction ordinaire — la provenance d'origine est
    #: préservée : corriger une macro estimée ne la transforme pas en saisie manuelle
    #: (`NUT-09`). Présente, elle dit un changement réel : un repas relevé à la main dont
    #: on accepte ensuite une estimation devient `ai`, et le fichier le raconte.
    source: Literal["manual", "ai"] | None = None

    @model_validator(mode="after")
    def require_content(self) -> MealPayload:
        """Un repas sans commentaire ni macro ne relève rien.

        À la correction, la photo d'origine est préservée : elle suffit donc à donner
        du contenu au repas. Le contrôle porte ici sur ce que la requête apporte.
        """
        return self


class Meal(BaseModel):
    id: int
    token: str
    datetime: datetime
    meal_type: str
    comment: str | None = None
    #: Chemin relatif, à passer à `/api/nutrition/photos/{chemin}`.
    photo: str | None = None
    protein_g: float | None = None
    added_sugar_g: float | None = None
    calories: int | None = None
    source: str


class DayTotals(BaseModel):
    """Totaux du jour (`NUT-06`)."""

    protein_g: float
    protein_target_g: float
    #: Ce qu'il reste à prendre pour atteindre la cible, **plancher à zéro**.
    #:
    #: Même raison que `HydrationStats.remaining_ml` : la soustraction se fait ici, une
    #: fois, par le service qui détient la cible — pas dans chaque écran ni dans chaque
    #: réponse de l'assistant.
    protein_remaining_g: float = Field(ge=0)
    #: Rapport à l'objectif, plafonné pour l'affichage.
    protein_ratio: float = Field(ge=0, le=1)
    added_sugar_g: float
    added_sugar_max_g: float
    #: Vrai quand le plafond de sucres est dépassé — un signal, pas une réussite.
    over_sugar: bool
    calories: int
    #: Nombre de repas dont les calories sont renseignées, sur le total du jour.
    calories_known: int
    meals: int


class Favorite(BaseModel):
    id: int
    token: str
    favorite_id: str
    name: str
    protein_g: float | None = None
    added_sugar_g: float | None = None
    calories: int | None = None


class FavoritePayload(BaseModel):
    name: Label
    protein_g: ProteinG | None = None
    added_sugar_g: SugarG | None = None
    calories: Calories | None = None


class MealEstimate(BaseModel):
    """Ce qu'un modèle propose pour une assiette (`NUT-04`).

    **Une proposition, pas une mesure.** Tous les champs sont facultatifs : un modèle qui
    ne distingue pas les sucres ajoutés rend `null`, et l'écran laisse le champ vide. Ils
    portent les mêmes bornes qu'une saisie humaine — ce qui les dépasse a été écarté à la
    relecture, pas ramené à la borne.
    """

    comment: str | None = None
    protein_g: ProteinG | None = None
    added_sugar_g: SugarG | None = None
    calories: Calories | None = None
    #: Faux quand le modèle annonce lui-même ne pas voir de nourriture.
    readable: bool = True
    #: Vrai quand la réponse ne porte **aucun** chiffre : l'écran le dit plutôt que
    #: d'afficher trois champs vides sans explication.
    empty: bool = False


class NutritionView(BaseModel):
    """Tout l'écran nutrition en une requête."""

    date: date
    totals: DayTotals
    meals: list[Meal]
    favorites: list[Favorite]
    #: Type présélectionné selon l'heure courante (`NUT-03`), calculé par le serveur pour
    #: que le client ne redéfinisse pas la règle.
    suggested_type: str
    types: list[str]
