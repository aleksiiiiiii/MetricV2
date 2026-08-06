"""Modèle de base des lignes CSV (`STO-02`).

Un fichier CSV par domaine, en-tête explicite, une colonne par champ. La conversion
vers et depuis le texte vit ici et nulle part ailleurs : c'est ce qui garantit qu'une
date s'écrit de la même façon dans tous les fichiers.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict

# ── Colonnes tolérantes (famille *planning*) ──────────
#
# Le §2 de `docs/etat-du-projet.md` distingue deux familles de fichiers. Ceux de
# **mesure** restent stricts : une ligne illisible lève, on ne devine pas une donnée. Ceux
# de **configuration, catalogue et planning** promettent l'inverse — « une cellule vide,
# un nombre illisible, une source mal orthographiée y sont des possibilités normales ».
#
# Une valeur par défaut ne suffit pas à tenir cette promesse : `CsvModel.from_csv` ne
# l'applique qu'aux cellules **vides**. Une cellule *remplie de travers* — un horodatage
# dans une colonne de date, « douze » dans une colonne de nombre — lève encore, et cela
# suffit à rendre un écran entier inaccessible en `502`.
#
# C'est arrivé : un `goals/goals.csv` écrit par une version antérieure portait
# `2026-07-10T16:26` dans `created`, et il a fait tomber l'écran Objectif **et**
# l'assistant, qui lit le même fichier. Les types ci-dessous rendent la promesse vraie.


def lenient_date(value: object) -> object:
    """Une date de fichier de planning, ou `None` si elle est illisible.

    Un horodatage est **récupéré**, pas écarté : `2026-07-10T16:26` veut dire le 10 juillet
    2026, le jour est écrit là, et le lire n'est pas l'inventer. Le rattachement au jour
    suit l'unique implémentation du projet (`HEAT-32`), pour qu'une prise à 23 h 30 ne
    bascule pas d'un jour selon le chemin qui l'a lue.

    Tout le reste rend `None`, c'est-à-dire le repli de la colonne : « on ne sait pas
    quand », qui est une réponse, là où un `502` n'en est pas une.
    """
    if value is None or (isinstance(value, date) and not isinstance(value, datetime)):
        return value

    if isinstance(value, datetime):
        return _local_day(value)

    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return _local_day(datetime.fromisoformat(text))
    except ValueError:
        return None


def _local_day(moment: datetime) -> date:
    """Jour d'un horodatage, par l'unique implémentation du projet.

    Importée tardivement : `app.core.dates` lit la configuration, et le socle de stockage
    est chargé bien avant elle.
    """
    from app.core.dates import local_day_of

    return local_day_of(moment)


def lenient_number(value: object) -> object:
    """Un nombre de fichier de planning, ou `0` s'il est illisible.

    La virgule française est acceptée — c'est ce qu'un tableur écrit quand on tape `12,5`
    dans une cellule, et refuser sa propre sortie serait absurde pour un fichier dont la
    promesse est de rester exploitable dans un tableur (`STO-02`).
    """
    if value is None or isinstance(value, int | float):
        return value

    text = str(value).strip().replace(",", ".").replace(" ", "").replace(" ", "")
    if not text:
        return 0
    try:
        return float(text)
    except ValueError:
        return 0


#: Date d'un fichier de planning. Illisible, elle vaut « pas de date ».
CsvDate = Annotated[date | None, BeforeValidator(lenient_date)]

#: Nombre d'un fichier de planning. Illisible, il vaut zéro.
CsvNumber = Annotated[float, BeforeValidator(lenient_number)]


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
