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
