"""Modèles CSV du domaine Corps (`body/weight.csv`, `body/measurements.csv`).

Colonnes reprises de l'annexe du backlog. Ces modèles décrivent le **fichier** ; les
formes échangées avec le client vivent dans `schemas.py` et portent les bornes de
vraisemblance (`API-06`).
"""

from __future__ import annotations

from datetime import date

from app.storage.model import CsvModel


class WeightRow(CsvModel):
    """Une pesée. `body/weight.csv` : date, weight_kg, note, source."""

    date: date
    weight_kg: float
    note: str | None = None
    #: `manual` ou `apple` — l'origine d'une donnée est lisible jusque dans le fichier
    #: (`IMP-05`).
    source: str = "manual"


class MeasurementRow(CsvModel):
    """Un relevé de mensurations.

    Toutes les mesures sont facultatives : on ne mesure pas tout à chaque fois. La règle
    « au moins une » (`BODY-07`) est une contrainte de saisie, portée par le schéma
    d'API — le fichier, lui, doit pouvoir contenir une ligne partielle.
    """

    date: date
    waist_cm: float | None = None
    arm_cm: float | None = None
    chest_cm: float | None = None
    hips_cm: float | None = None
    thigh_cm: float | None = None
    #: Composition corporelle (`BODY-10`), suivie comme une mesure du domaine Corps.
    body_fat_pct: float | None = None
    note: str | None = None


#: Mesures dans l'ordre d'affichage, avec leur libellé. L'ordre vient d'ici et de nulle
#: part ailleurs : le client ne doit pas décider dans quel ordre lire un tour de bras.
MEASUREMENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("waist_cm", "Taille"),
    ("chest_cm", "Poitrine"),
    ("arm_cm", "Bras"),
    ("hips_cm", "Hanches"),
    ("thigh_cm", "Cuisse"),
    ("body_fat_pct", "Masse grasse"),
)
