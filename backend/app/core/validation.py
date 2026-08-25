"""Bornes de vraisemblance réutilisables (`API-06`).

Une saisie aberrante est rejetée **avant** le stockage. Les bornes viennent du backlog ;
les nommer ici évite qu'un domaine accepte une fréquence cardiaque de 2600 parce que son
auteur a oublié la limite.

Ce ne sont pas des bornes physiologiques strictes mais des garde-fous de saisie : elles
attrapent la faute de frappe et le champ mal rempli, pas la performance inhabituelle.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated

from pydantic import AfterValidator, Field

# Le découpage du temps vit dans `app.core.dates`, un seul endroit (`HEAT-32`).
# L'import le remet à disposition des domaines qui valident une date.
from app.core.dates import today_local

__all__ = ["today_local"]


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

#: Amplitude d'un planning, de part et d'autre d'aujourd'hui (`PLAN-02`).
#: Vers l'arrière : on replanifie la semaine en cours, pas l'an dernier. Vers l'avant :
#: une préparation de marathon se pose à un an, jamais à dix.
PLAN_PAST_DAYS = 400
PLAN_FUTURE_DAYS = 400


def reject_implausible_plan_date(value: date) -> date:
    """Borne une date de planning, sans lui interdire l'avenir.

    Le planning est le **seul** domaine du projet à porter des dates futures : il
    n'utilise donc pas `PastDate`. Il n'est pas pour autant sans garde-fou — une faute de
    frappe sur l'année (`2062` pour `2026`) poserait une séance qu'aucun écran ne montre
    jamais et qui traînerait dans le flux iCal pour toujours.
    """
    today = today_local()
    if value < today - timedelta(days=PLAN_PAST_DAYS):
        raise ValueError("cette date est trop ancienne pour un planning")
    if value > today + timedelta(days=PLAN_FUTURE_DAYS):
        raise ValueError("cette date est trop lointaine pour un planning")
    return value


PlannedDate = Annotated[date, AfterValidator(reject_implausible_plan_date)]

# ── Corps (`BODY`) ────────────────────────────────────

WeightKg = Annotated[float, Field(gt=0, le=500, description="Poids en kilogrammes")]
BodyFatPct = Annotated[float, Field(ge=1, le=70, description="Masse grasse en pourcent")]
MeasurementCm = Annotated[float, Field(gt=0, le=300, description="Mensuration en centimètres")]

# ── Activité (`ACT`) ──────────────────────────────────

DistanceKm = Annotated[float, Field(gt=0, le=1000, description="Distance en kilomètres")]
DurationMin = Annotated[float, Field(gt=0, le=1440, description="Durée en minutes")]
HeartRate = Annotated[int, Field(ge=1, le=260, description="Fréquence cardiaque moyenne")]
#: Allure en minutes par kilomètre. La borne basse est en dessous d'un sprint sur piste,
#: la haute au-dessus d'une marche lente : ce qui sort de là n'est pas une allure de
#: course à pied, et vaut mieux refusé que rangé (`API-06`).
PaceMinKm = Annotated[float, Field(gt=1, le=60, description="Allure en minutes par km")]
#: Cadence en pas par minute. Une foulée de course tient entre 150 et 200 ; la marche
#: descend vers 100. Les bornes laissent large sans accepter un nombre qui n'en est pas un.
CadenceSpm = Annotated[int, Field(ge=30, le=300, description="Cadence en pas par minute")]
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
#: Objectif **quotidien**, distinct d'une prise : il se compte en litres, pas en verres.
HydrationTargetMl = Annotated[
    int, Field(ge=250, le=10000, description="Objectif quotidien en millilitres")
]

# ── Texte libre ───────────────────────────────────────

Note = Annotated[str, Field(max_length=500, description="Note libre")]
Label = Annotated[str, Field(min_length=1, max_length=80, description="Libellé court")]

# ── Adresses d'applications externes ──────────────────

#: Adresse **de base** d'une application tierce, à laquelle on ajoutera une query string.
#:
#: Trois bornes, et chacune évite un lien cassé plutôt qu'une valeur aberrante :
#:
#: * **La chaîne vide est acceptée**, et c'est une valeur au sens plein : elle veut dire
#:   « pas d'adresse ». Sans elle, un réglage renseigné par erreur ne pourrait plus être
#:   effacé — il n'y a pas de défaut sur lequel retomber, contrairement à un objectif.
#: * **Ni `?` ni `#`.** Une base qui porte déjà une query string ou une ancre donnerait
#:   `…?a=b?w=…` une fois le paramètre ajouté, ce qui n'est pas une URL mais un texte qui
#:   y ressemble. Le refus arrive à la saisie, où il se corrige, et non à l'ouverture du
#:   lien, où il ne se comprend pas.
#: * **`http` ou `https` seulement.** Un `javascript:` ou un `data:` dans un `href` rendu
#:   par l'application est une porte qu'on n'ouvre pas, fût-elle à un seul utilisateur.
BaseUrl = Annotated[
    str,
    Field(
        max_length=200,
        pattern=r"^$|^https?://[^\s?#]+$",
        description="Adresse de base d'une application externe, ou vide",
    ),
]
