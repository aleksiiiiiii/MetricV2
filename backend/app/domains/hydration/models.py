"""Modèle CSV de l'hydratation. `hydration/intake_log.csv` : datetime, volume_ml, kind."""

from __future__ import annotations

from datetime import datetime

from app.storage.model import CsvModel


class IntakeRow(CsvModel):
    """Une prise de boisson (`HYD-01`).

    L'horodatage porte son décalage : c'est ce qui permet de rattacher une prise de
    23 h 30 au bon jour (`HEAT-32`). Sans lui, la même ligne changerait de journée selon
    le fuseau de lecture.
    """

    datetime_: datetime
    volume_ml: int
    #: Eau, café, thé, boisson sportive, autre. Facultatif : ce qui compte d'abord est
    #: le volume, et exiger le type ajouterait un geste à une saisie qui doit en tenir
    #: en un seul.
    kind: str | None = None

    @classmethod
    def csv_columns(cls) -> tuple[str, ...]:
        # Le champ s'appelle `datetime_` en Python — `datetime` est un type — mais la
        # colonne doit garder le nom de l'annexe du backlog.
        return ("datetime", "volume_ml", "kind")

    def to_csv(self) -> dict[str, str]:
        row = super().to_csv()
        return {"datetime": row.pop("datetime_"), **row}

    @classmethod
    def from_csv(cls, row):  # type: ignore[no-untyped-def]
        mapped = dict(row)
        if "datetime" in mapped:
            mapped["datetime_"] = mapped.pop("datetime")
        return super().from_csv(mapped)


#: Types de boisson proposés (`HYD-01`). Suggestions, pas contrainte.
DRINK_KINDS: tuple[str, ...] = ("eau", "café", "thé", "boisson sportive", "autre")
