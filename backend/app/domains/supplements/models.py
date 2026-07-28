"""Modèles CSV des suppléments.

`supplements/schedule.csv` : id, name, dose, unit, time, frequency, active, created
`supplements/intake_log.csv` : datetime, schedule_id, name, dose, unit

Deux colonnes méritent une explication.

**`frequency`** porte la cadence sérialisée (`app.core.cadence`). Elle était prévue mais
inutilisée dans la v1 ; la renseigner est le prérequis de `HEAT-23` — un seul endroit
décrit « je prends de la whey un jour sur deux », et le planning ne peut pas diverger de
la heatmap.

**`created`** date l'entrée du complément au planning. C'est ce qui rend `HEAT-07` vrai :
ajouter la créatine aujourd'hui ne doit pas rendre rouges les six mois précédents.

Le journal duplique le nom, la dose et l'unité pour la même raison qu'au domaine
Activité : retirer un supplément du planning ne doit pas rendre son historique illisible
(`SUP-02`, `STO-02`).
"""

from __future__ import annotations

from datetime import date, datetime

from app.storage.model import CsvModel


class ScheduleRow(CsvModel):
    """Une ligne de planning. `supplements/schedule.csv`.

    **Toutes les colonnes portent un défaut**, et c'est ce qui rend `STO-04` vrai ici :
    une ligne écrite avant qu'une colonne n'existe, ou une cellule vidée dans un tableur,
    doit rester lisible. Sans défaut, une seule cellule vide rendait le fichier entier
    illisible — et avec lui la checklist, la routine **et le tableau de bord**, qui lit le
    planning pour son ratio du jour.

    La contrepartie est assumée : le fichier peut contenir une ligne partielle héritée,
    une **saisie** ne le peut pas. Les bornes vivent dans `SupplementPayload`, à la
    frontière de l'API.
    """

    id: str = ""
    name: str = ""
    dose: float = 0
    unit: str = ""
    #: Moment de prise, `HH:MM`. Sert au tri de la checklist (`SUP-01`) ; vide, la ligne
    #: passe en tête plutôt que de faire tomber l'écran.
    time: str = ""
    #: Cadence sérialisée — voir `app.core.cadence` (`HEAT-23`).
    frequency: str = "daily"
    active: bool = True
    #: Date d'entrée au planning (`HEAT-07`).
    created: date | None = None


class SupplementIntakeRow(CsvModel):
    datetime_: datetime
    schedule_id: str
    name: str
    dose: float
    unit: str

    @classmethod
    def csv_columns(cls) -> tuple[str, ...]:
        return ("datetime", "schedule_id", "name", "dose", "unit")

    def to_csv(self) -> dict[str, str]:
        row = super().to_csv()
        return {"datetime": row.pop("datetime_"), **row}

    @classmethod
    def from_csv(cls, row):  # type: ignore[no-untyped-def]
        mapped = dict(row)
        if "datetime" in mapped:
            mapped["datetime_"] = mapped.pop("datetime")
        return super().from_csv(mapped)


#: Unités proposées (`SUP-01`).
UNITS: tuple[str, ...] = ("g", "mg", "UI", "gélule", "ml")
