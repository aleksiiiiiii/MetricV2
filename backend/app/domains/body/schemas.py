"""Formes échangées avec le client pour le domaine Corps.

Distinctes des modèles CSV : ce sont elles qui portent les bornes de vraisemblance
(`API-06`) et le jeton de garde anti-conflit (`STO-05`). Le fichier peut contenir une
ligne partielle héritée ; une saisie, non.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.core.validation import BodyFatPct, MeasurementCm, Note, PastDate, WeightKg

# ── Pesées ────────────────────────────────────────────


class WeightPayload(BaseModel):
    """Saisie d'une pesée (`BODY-01`)."""

    date: PastDate = Field(description="Jour de la pesée, jamais dans le futur")
    weight_kg: WeightKg
    note: Note | None = None


class WeightEntry(BaseModel):
    """Pesée telle qu'elle est rendue au client."""

    id: int = Field(description="Position de la ligne dans le fichier")
    token: str = Field(description="À renvoyer en « If-Match » pour modifier ou supprimer")
    date: date
    weight_kg: float
    note: str | None = None
    source: str


class WeightPoint(BaseModel):
    """Point de la série temporelle (`BODY-04`)."""

    date: date
    weight_kg: float
    #: Moyenne mobile 7 jours (`BODY-05`). `None` tant que la fenêtre est vide.
    trend_kg: float | None = None


class WeightStats(BaseModel):
    """Indicateurs prêts à afficher (`BODY-03`, `BODY-04`)."""

    latest_kg: float | None = Field(default=None, description="Dernière pesée")
    latest_date: date | None = None
    #: Variation sur les 8 dernières pesées (`BODY-03`).
    change_kg: float | None = None
    #: Écart restant jusqu'à l'objectif. Négatif = objectif dépassé vers le bas.
    to_target_kg: float | None = None
    target_kg: float
    #: Sur toute la série (`BODY-04`).
    min_kg: float | None = None
    max_kg: float | None = None
    amplitude_kg: float | None = None
    count: int


class WeightView(BaseModel):
    """Réponse unique de l'écran Corps, volet poids.

    Série, statistiques et historique en un seul appel : trois requêtes pour peindre un
    écran seraient trois allers-retours vers Nextcloud (`AGG-01` en esprit).
    """

    stats: WeightStats
    series: list[WeightPoint]
    entries: list[WeightEntry]
    total: int


# ── Mensurations ──────────────────────────────────────


class MeasurementPayload(BaseModel):
    """Saisie de mensurations (`BODY-07`)."""

    date: PastDate
    waist_cm: MeasurementCm | None = None
    chest_cm: MeasurementCm | None = None
    arm_cm: MeasurementCm | None = None
    hips_cm: MeasurementCm | None = None
    thigh_cm: MeasurementCm | None = None
    body_fat_pct: BodyFatPct | None = None
    note: Note | None = None

    @model_validator(mode="after")
    def require_at_least_one(self) -> MeasurementPayload:
        """Au moins une mesure : une ligne datée sans valeur ne mesure rien."""
        measures = (
            self.waist_cm,
            self.chest_cm,
            self.arm_cm,
            self.hips_cm,
            self.thigh_cm,
            self.body_fat_pct,
        )
        if all(measure is None for measure in measures):
            raise ValueError("renseigne au moins une mesure")
        return self


class MeasurementEntry(BaseModel):
    id: int
    token: str
    date: date
    waist_cm: float | None = None
    chest_cm: float | None = None
    arm_cm: float | None = None
    hips_cm: float | None = None
    thigh_cm: float | None = None
    body_fat_pct: float | None = None
    note: str | None = None


class MeasurementIndicator(BaseModel):
    """Dernière valeur, écart et sens de variation (`BODY-08`)."""

    field: str
    label: str
    latest: float | None = None
    latest_date: date | None = None
    delta: float | None = Field(default=None, description="Écart avec le relevé précédent")
    direction: str | None = Field(default=None, description="« up », « down » ou « flat »")
    unit: str


class MeasurementView(BaseModel):
    indicators: list[MeasurementIndicator]
    entries: list[MeasurementEntry]
    total: int
