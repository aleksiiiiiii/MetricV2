"""Formes échangées par l'import Apple (`IMP-01` → `IMP-06`)."""

from __future__ import annotations

# Le module et non le nom : ces schémas portent un champ **appelé** `date`, et un champ
# avec une valeur par défaut masque le type homonyme au moment où pydantic relit
# l'annotation. `dt.date` ne peut être masqué par rien.
import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.parsing import (
    ParseError,
    parse_clock_time,
    parse_decimal,
    parse_distance_km,
    parse_duration_minutes,
)
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
from app.domains.activity.schemas import RunSplitPayload

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


class SplitDraft(BaseModel):
    """Un palier lu dans une capture, **avant** toute écriture (`ACT-19`).

    `partial` et `distance_km` sont déjà posés par le serveur : ils ne viennent pas du
    modèle, qui n'a fait que recopier des durées. C'est ce qui permet à l'écran d'afficher
    « reliquat, 0,14 km » sur la neuvième ligne sans rien décider lui-même.
    """

    index: int
    duration_s: float
    distance_km: float | None = None
    pace_min_km: float | None = None
    cadence_spm: int | None = None
    avg_hr: int | None = None
    elevation_m: int | None = None
    partial: bool = False


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
    #: Kilocalories **actives**. Le nom reste celui d'avant pour ne pas casser l'écran
    #: existant, mais le champ n'a jamais voulu dire autre chose.
    calories: int | None = None
    #: Kilocalories **totales**, métabolisme de base compris. Une capture Apple en affiche
    #: deux — 439 actives, 492 totales — et les confondre change la lecture d'une séance.
    total_calories: int | None = None
    start_time: dt.time | None = None
    end_time: dt.time | None = None
    #: Longueur d'un palier plein, lue dans l'en-tête de la liste.
    split_length_km: float | None = None
    #: Les paliers relevés, reliquat compris et marqué.
    splits: list[SplitDraft] = Field(default_factory=list)
    #: Verdict de la **relecture serveur** (`IMP-03`). Faux, l'écran affiche les paliers
    #: marqués douteux — il ne les refuse pas : l'utilisateur a la capture sous les yeux,
    #: nous non, et lui faire ressaisir neuf lignes pour vingt secondes d'écart serait pire
    #: que de lui montrer ce qu'on doute.
    splits_trusted: bool = True
    #: Ce qui cloche, en français et prêt à afficher — la somme qui ne tombe pas, la
    #: capture qui manque au milieu. Vide quand `splits_trusted` est vrai.
    splits_doubts: list[str] = Field(default_factory=list)
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
    #: Les kilocalories totales, et les paliers, quand l'analyse en a trouvé. Ils
    #: traversent l'écran sans être modifiables : le formulaire d'import corrige des
    #: chiffres de résumé, pas neuf lignes de tableau.
    total_calories: Calories | None = None
    start_time: dt.time | None = None
    end_time: dt.time | None = None
    split_length_km: DistanceKm | None = None
    #: Le type est celui du domaine Activité, **pas une copie locale** : les paliers
    #: finissent dans `run_splits.csv` par le service de ce domaine, et deux définitions
    #: de la même chose finiraient par accepter deux bornes différentes.
    splits: list[RunSplitPayload] = Field(default_factory=list)

    @field_validator("split_length_km", mode="before")
    @classmethod
    def read_split_length(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if not value.strip():
            return None
        try:
            return parse_distance_km(value)
        except ParseError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def read_clock(cls, value: object) -> object:
        """Une borne horaire illisible vaut `None`, jamais un refus.

        C'est un contexte, pas une mesure : perdre l'import d'une course entière parce
        qu'une heure d'horloge a mal été recopiée serait échanger une donnée contre un
        ornement.
        """
        return parse_clock_time(value) if isinstance(value, str) else value

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
