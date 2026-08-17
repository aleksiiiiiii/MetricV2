"""Formes échangées pour l'hydratation (`HYD-01` → `HYD-05`)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.validation import Label, PastDateTime, VolumeMl


class IntakePayload(BaseModel):
    """Saisie d'une prise (`HYD-01`)."""

    volume_ml: VolumeMl
    kind: Label | None = None
    #: Facultatif : par défaut, maintenant. La cible est un relevé en un geste, et
    #: renseigner l'heure de ce qu'on vient de boire n'en fait pas partie.
    datetime: PastDateTime | None = None


class Intake(BaseModel):
    id: int
    token: str
    datetime: datetime
    volume_ml: int
    kind: str | None = None


class DayVolume(BaseModel):
    """Un jour de la série (`HYD-05`)."""

    date: date
    volume_ml: int
    #: Objectif atteint ce jour-là.
    reached: bool


class HydrationStats(BaseModel):
    """Indicateurs prêts à afficher (`HYD-03`, `HYD-05`)."""

    #: Volume cumulé du jour courant.
    today_ml: int
    target_ml: int
    #: Rapport au but, plafonné à 1 pour l'affichage — le dépassement reste lisible
    #: dans `today_ml`.
    ratio: float = Field(ge=0, le=1)
    #: Ce qu'il reste à boire pour atteindre la cible, **plancher à zéro**.
    #:
    #: Servi et non déduit. « Il me reste combien à boire ? » est la question la plus
    #: naturelle qui soit, et sans ce champ chacun la calcule dans son coin — l'écran en
    #: TypeScript, l'assistant dans sa réponse. « Moyennes, écarts, ratios : le serveur
    #: calcule » vaut pour les deux, et un écart soustrait par un modèle est le moins
    #: auditable de tous.
    #:
    #: Zéro quand la cible est atteinte : le dépassement se lit dans `today_ml`, comme
    #: pour `ratio`. Un restant négatif dirait « bois -200 ml ».
    remaining_ml: int = Field(ge=0)
    average_7d_ml: int | None = None
    average_30d_ml: int | None = None
    #: Jours ayant atteint l'objectif sur la plage retournée.
    days_reached: int
    days_counted: int


class HydrationView(BaseModel):
    """Tout l'écran hydratation en une requête."""

    stats: HydrationStats
    #: Volumes quotidiens, plage **complète** : les jours sans prise valent zéro.
    series: list[DayVolume]
    #: Prises du jour courant, pour pouvoir en corriger une (`HYD-04`).
    today: list[Intake]
    #: Raccourcis paramétrables (`HYD-02`).
    presets_ml: list[int]
    kinds: list[str]
