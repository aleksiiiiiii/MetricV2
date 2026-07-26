"""Modèle de base des lignes CSV (`STO-02`).

Un fichier CSV par domaine, en-tête explicite, une colonne par champ. La conversion
vers et depuis le texte vit ici et nulle part ailleurs : c'est ce qui garantit qu'une
date s'écrit de la même façon dans tous les fichiers.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict


def format_csv_value(value: Any) -> str:
    """Rend une valeur sous sa forme texte, lisible dans un tableur.

    `None` devient une cellule vide : c'est la convention de tout le stockage, et elle
    permet d'ajouter une colonne sans toucher aux lignes anciennes (`STO-04`).
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        # Pas « True »/« False » : le CSV est lu par des humains et par des tableurs.
        return "true" if value else "false"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, datetime):
        # Toujours avec décalage horaire : une prise à 23 h 30 doit rester
        # interprétable sans deviner le fuseau (`HEAT-32`).
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


class CsvModel(BaseModel):
    """Ligne d'un fichier CSV."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        validate_assignment=True,
    )

    @classmethod
    def csv_columns(cls) -> tuple[str, ...]:
        """Colonnes du fichier, dans l'ordre de déclaration des champs."""
        return tuple(cls.model_fields)

    @classmethod
    def from_csv(cls, row: Mapping[str, str]) -> Self:
        """Construit un modèle depuis une ligne brute.

        Une cellule vide, ou une colonne absente du fichier, se comporte comme une
        valeur non fournie :

        * champ avec valeur par défaut → le défaut s'applique. C'est ce qui rend
          `STO-04` vrai : ajouter une colonne au modèle n'invalide aucune ligne ancienne.
        * champ requis et nullable → `None`.
        * champ requis non nullable → erreur de validation, ce qui est le comportement
          voulu : la donnée manque vraiment.
        """
        data: dict[str, str | None] = {}
        for name, field in cls.model_fields.items():
            raw = row.get(name)
            if raw is None or raw == "":
                if field.is_required():
                    data[name] = None
                continue
            data[name] = raw
        return cls.model_validate(data)

    def to_csv(self) -> dict[str, str]:
        """Rend la ligne sous forme de cellules texte."""
        return {name: format_csv_value(getattr(self, name)) for name in type(self).model_fields}
