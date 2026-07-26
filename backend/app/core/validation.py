"""Bornes de vraisemblance réutilisables (`API-06`).

Une saisie aberrante est rejetée **avant** le stockage. Les bornes viennent du backlog ;
les nommer ici évite qu'un domaine accepte une fréquence cardiaque de 2600 parce que son
auteur a oublié la limite.

Ce ne sont pas des bornes physiologiques strictes mais des garde-fous de saisie : elles
attrapent la faute de frappe et le champ mal rempli, pas la performance inhabituelle.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, Field

from app.config import get_settings


def today_local() -> date:
    """Date du jour dans le fuseau de l'application (`HEAT-32`).

    Jamais `date.today()` en UTC : le 26 juillet à 1 h du matin à Paris est encore le
    25 juillet en UTC, et une pesée légitime serait refusée comme « future ».
    """
    return datetime.now(tz=get_settings().tz).date()


def reject_future_date(value: date) -> date:
    """Refuse une date postérieure à aujourd'hui.

    On ne relève pas ce qui n'a pas eu lieu. Le planning (`PLAN-02`) est le seul domaine
    à porter des dates futures, et il n'utilise pas ce type.
    """
    if value > today_local():
        raise ValueError("la date ne peut pas être dans le futur")
    return value


def reject_future_datetime(value: datetime) -> datetime:
    """Même règle, à l'horodatage près."""
    if value.date() > today_local():
        raise ValueError("l'horodatage ne peut pas être dans le futur")
    return value


# ── Dates ─────────────────────────────────────────────

PastDate = Annotated[date, AfterValidator(reject_future_date)]
PastDateTime = Annotated[datetime, AfterValidator(reject_future_datetime)]

# ── Corps (`BODY`) ────────────────────────────────────

WeightKg = Annotated[float, Field(gt=0, le=500, description="Poids en kilogrammes")]
BodyFatPct = Annotated[float, Field(ge=1, le=70, description="Masse grasse en pourcent")]
MeasurementCm = Annotated[float, Field(gt=0, le=300, description="Mensuration en centimètres")]

# ── Activité (`ACT`) ──────────────────────────────────

DistanceKm = Annotated[float, Field(gt=0, le=1000, description="Distance en kilomètres")]
DurationMin = Annotated[float, Field(gt=0, le=1440, description="Durée en minutes")]
HeartRate = Annotated[int, Field(ge=1, le=260, description="Fréquence cardiaque moyenne")]
ElevationM = Annotated[int, Field(ge=0, le=10000, description="Dénivelé positif en mètres")]
Reps = Annotated[int, Field(ge=1, le=200, description="Répétitions par série")]
Sets = Annotated[int, Field(ge=1, le=50, description="Nombre de séries")]
LoadKg = Annotated[float, Field(ge=0, le=1000, description="Charge en kg, 0 = poids du corps")]
Rpe = Annotated[int, Field(ge=1, le=10, description="Effort perçu (`ACT-18`)")]
Calories = Annotated[int, Field(ge=0, le=10000, description="Calories")]

# ── Nutrition (`NUT`) ─────────────────────────────────

ProteinG = Annotated[float, Field(ge=0, le=500, description="Protéines en grammes")]
SugarG = Annotated[float, Field(ge=0, le=1000, description="Sucres ajoutés en grammes")]

# ── Hydratation (`HYD`) ───────────────────────────────

VolumeMl = Annotated[int, Field(gt=0, le=5000, description="Volume d'une prise en millilitres")]

# ── Texte libre ───────────────────────────────────────

Note = Annotated[str, Field(max_length=500, description="Note libre")]
Label = Annotated[str, Field(min_length=1, max_length=80, description="Libellé court")]
