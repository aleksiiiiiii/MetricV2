"""Modèles CSV de la nutrition.

`nutrition/meals.csv` : datetime, meal_type, comment, photo, protein_g, added_sugar_g,
calories, source
`nutrition/favorites.csv` : id, name, protein_g, added_sugar_g, calories
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from app.storage.model import CsvModel


class MealType(StrEnum):
    """Typage du repas (`NUT-03`)."""

    BREAKFAST = "petit-déjeuner"
    LUNCH = "déjeuner"
    DINNER = "dîner"
    SNACK = "collation"


class MealRow(CsvModel):
    """Un repas.

    `photo` porte le chemin **relatif** au dossier des photos. Le stocker relatif plutôt
    qu'absolu permet de déplacer le dossier de données sans réécrire le fichier.
    """

    datetime_: datetime
    meal_type: str
    comment: str | None = None
    photo: str | None = None
    protein_g: float | None = None
    added_sugar_g: float | None = None
    calories: int | None = None
    #: `manual` ou `ai` — l'origine d'une estimation reste lisible dans le fichier.
    source: str = "manual"

    @classmethod
    def csv_columns(cls) -> tuple[str, ...]:
        return (
            "datetime",
            "meal_type",
            "comment",
            "photo",
            "protein_g",
            "added_sugar_g",
            "calories",
            "source",
        )

    def to_csv(self) -> dict[str, str]:
        row = super().to_csv()
        return {"datetime": row.pop("datetime_"), **row}

    @classmethod
    def from_csv(cls, row):  # type: ignore[no-untyped-def]
        mapped = dict(row)
        if "datetime" in mapped:
            mapped["datetime_"] = mapped.pop("datetime")
        return super().from_csv(mapped)


class FavoriteRow(CsvModel):
    """Un repas récurrent, rejouable en une action (`NUT-10`).

    Catalogue et non mesure : une ligne incomplète est ignorée, elle ne rend pas le
    fichier illisible (`STO-04`).
    """

    id: str = ""
    name: str = ""
    protein_g: float | None = None
    added_sugar_g: float | None = None
    calories: int | None = None


#: Bornes horaires du type suggéré (`NUT-03`). Le type reste modifiable : ce n'est
#: qu'une présélection, elle doit tomber juste souvent, pas toujours.
TYPE_BY_HOUR: tuple[tuple[int, MealType], ...] = (
    (11, MealType.BREAKFAST),
    (15, MealType.LUNCH),
    (18, MealType.SNACK),
    (24, MealType.DINNER),
)
