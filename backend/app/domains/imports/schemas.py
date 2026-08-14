"""Formes échangées par l'import Apple (`IMP-01` → `IMP-06`)."""

from __future__ import annotations

# Le module et non le nom : ces schémas portent un champ **appelé** `date`, et un champ
# avec une valeur par défaut masque le type homonyme au moment où pydantic relit
# l'annotation. `dt.date` ne peut être masqué par rien.
import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.parsing import ParseError, parse_decimal, parse_distance_km, parse_duration_minutes
from app.core.validation import (
    CadenceSpm,
    Calories,
    DistanceKm,
    DurationMin,
    ElevationM,
    HeartRate,
    Label,
    Note,
    PaceMinKm,
    PastDate,
)

#: Les deux natures d'activité que le domaine sait écrire — `runs.csv` et `workouts.csv`.
Kind = Literal["run", "workout"]


class DuplicateWarning(BaseModel):
    """Activité déjà enregistrée qui ressemble à celle qu'on s'apprête à importer (`IMP-04`).

    Un **avertissement**, jamais un refus : deux sorties de trente minutes le même jour
    existent, et c'est à l'utilisateur de trancher. L'import qui déciderait à sa place
    ferait perdre une séance réelle sans rien dire.
    """

    kind: Kind
    id: int = Field(description="Position de la ligne existante, pour aller la voir")
    date: dt.date
    label: str
    duration_min: float


class AppleDraft(BaseModel):
    """Pré-remplissage lu dans une capture (`IMP-02`). **Rien n'est écrit** (`IMP-01`).

    Tous les champs sont facultatifs, y compris la date : `IMP-03` interdit d'inventer ce
    que la capture ne portait pas. Un champ absent arrive à `null`, l'écran le montre vide,
    et l'utilisateur le complète — ou pas.
    """

    kind: Kind
    date: dt.date | None = None
    #: Type de séance lu sur la capture (`Course à pied`, `Vélo`, `Musculation`…).
    workout_type: str | None = None
    distance_km: float | None = None
    duration_min: float | None = None
    #: Allure lue sur la capture, en minutes par kilomètre. Elle n'est pas **déduite** de
    #: la distance et de la durée : ce que l'écran montre en pointillé doit venir de
    #: l'image, sinon la marque « proposée » désignerait un calcul de notre propre code.
    pace_min_km: float | None = None
    cadence_spm: int | None = None
    avg_hr: int | None = None
    elevation_m: int | None = None
    calories: int | None = None
    #: Champs que la capture ne portait pas, nommés pour que l'écran puisse le **dire**
    #: plutôt que de laisser croire à un oubli de lecture.
    missing: list[str] = Field(default_factory=list)
    duplicate: DuplicateWarning | None = None


class AppleImportPayload(BaseModel):
    """Ce que l'utilisateur valide, après l'avoir corrigé autant qu'il veut (`IMP-02`).

    C'est une saisie ordinaire : elle porte les mêmes bornes de vraisemblance que le
    formulaire manuel (`API-06`) et accepte les mêmes formats souples (`ACT-01`). Un
    import ne mérite pas des règles plus laxistes qu'une saisie au clavier — il en mérite
    plutôt de plus strictes, puisque personne n'a tapé les chiffres.
    """

    kind: Kind
    date: PastDate
    duration_min: DurationMin
    type: Label = "Course"
    distance_km: DistanceKm | None = None
    #: L'une des deux suffit : le serveur calcule celle qui manque. Quand les deux sont
    #: là, **l'allure gagne** — c'est la règle de `RunPayload`, et elle est unique.
    pace_min_km: PaceMinKm | None = None
    cadence_spm: CadenceSpm | None = None
    avg_hr: HeartRate | None = None
    elevation_m: ElevationM | None = None
    calories: Calories | None = None
    note: Note | None = None

    @field_validator("duration_min", mode="before")
    @classmethod
    def read_duration(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            return parse_duration_minutes(value)
        except ParseError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("distance_km", mode="before")
    @classmethod
    def read_distance(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if not value.strip():
            return None
        try:
            return parse_distance_km(value)
        except ParseError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("pace_min_km", mode="before")
    @classmethod
    def read_pace(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if not value.strip():
            return None
        try:
            return parse_duration_minutes(value)
        except ParseError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("avg_hr", "elevation_m", "calories", "cadence_spm", mode="before")
    @classmethod
    def read_optional_number(cls, value: object) -> object:
        if isinstance(value, str):
            return None if not value.strip() else round(parse_decimal(value))
        return value

    @model_validator(mode="after")
    def a_run_needs_a_distance_or_a_pace(self) -> AppleImportPayload:
        """Une course sans distance **ni allure** n'est pas une course.

        Les deux sont liées par la durée et le serveur calcule celle qui manque (`ACT-02`).
        Il en faut donc une, pas les deux — une capture qui n'affiche que l'allure suffit
        désormais, ce qui n'était pas le cas. Sans aucune des deux, on demande de basculer
        en séance, ce que l'écran permet en un appui.
        """
        if self.kind == "run" and self.distance_km is None and self.pace_min_km is None:
            raise ValueError(
                "une course a besoin de sa distance ou de son allure ; sinon, importe une séance"
            )
        return self


class ImportResult(BaseModel):
    """Ce qui a été écrit, une fois la validation donnée (`IMP-01`, `IMP-05`)."""

    kind: Kind
    id: int
    date: dt.date
    label: str
    duration_min: float
    distance_km: float | None = None
    #: Toujours `apple` ici : l'origine reste lisible jusque dans le CSV (`IMP-05`).
    source: str
