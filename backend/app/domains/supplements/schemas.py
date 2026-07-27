"""Formes échangées pour les suppléments (`SUP-01` → `SUP-06`)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.core.cadence import Cadence, CadenceError
from app.core.validation import Label, Note

DoseValue = Field(gt=0, le=10000, description="Dose par prise")


class SupplementPayload(BaseModel):
    """Configuration d'une ligne de planning (`SUP-01`)."""

    name: Label
    dose: float = DoseValue
    unit: Label
    #: `HH:MM`. Le planning trié par horaire sert de base à la checklist.
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="Moment de prise")
    #: Cadence sérialisée (`HEAT-23`). Vide = tous les jours.
    frequency: str = "daily"
    active: bool = True

    @field_validator("frequency")
    @classmethod
    def readable_cadence(cls, value: str) -> str:
        """Valide la cadence à la saisie et la **normalise**.

        Normaliser ici garantit que deux saisies équivalentes produisent la même ligne :
        sinon le journal d'historisation (`HEAT-14`) enregistrerait un changement de
        cadence qui n'en est pas un.
        """
        try:
            return Cadence.parse(value).serialize()
        except CadenceError as exc:
            raise ValueError(str(exc)) from exc


class Supplement(BaseModel):
    """Ligne de planning rendue au client."""

    id: int
    token: str
    schedule_id: str
    name: str
    dose: float
    unit: str
    time: str
    frequency: str
    #: Formulation française de la cadence, calculée par le serveur.
    cadence_label: str
    active: bool
    created: date | None = None


class ChecklistItem(BaseModel):
    """Un item de la checklist du jour (`SUP-03`)."""

    schedule_id: str
    name: str
    dose: float
    unit: str
    time: str
    cadence_label: str
    taken: bool
    #: Horodatage de la prise, quand elle a eu lieu.
    taken_at: datetime | None = None
    #: Position de la ligne dans le journal, pour pouvoir décocher (`SUP-05`).
    intake_id: int | None = None
    intake_token: str | None = None
    #: Jours consécutifs de prise jusqu'à hier inclus.
    streak: int


class DayRatio(BaseModel):
    """Ratio du jour (`SUP-06`), base de la piste d'assiduité des suppléments."""

    taken: int
    planned: int
    ratio: float = Field(ge=0, le=1)
    #: Vrai quand toutes les prises planifiées et actives ont été cochées.
    complete: bool


class ChecklistView(BaseModel):
    date: date
    items: list[ChecklistItem]
    ratio: DayRatio


class IntakePayload(BaseModel):
    """Cocher un item revient à enregistrer une prise horodatée (`SUP-03`)."""

    schedule_id: str
    note: Note | None = None
