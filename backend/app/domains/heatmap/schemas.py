"""Formes échangées pour le moteur d'assiduité (spec `HEAT` v2, §8).

Une piste est de la **configuration**, pas une mesure. Ce qui circule ici décrit donc ce
qu'on attend — source, seuil, cadence, seuils d'intensité — et jamais ce qui s'est passé.
Les grilles et les statistiques arrivent au lot L10.

Deux choses sont servies au client qu'il aurait pu déduire : le **libellé de la cadence**
et le **catalogue des sources**. Dans les deux cas c'est délibéré — `HEAT-30` interdit au
client de réimplémenter la moindre règle de cadence, et une liste de sources recopiée
dans le frontend cesserait de décrire le serveur au premier ajout.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.cadence import Cadence, CadenceError
from app.core.validation import Label, Note, PastDate

#: Tons de la charte. Un accent hors de cette liste n'aurait pas de couleur à l'écran.
ACCENTS: tuple[str, ...] = ("signal", "effort", "load", "recover")


class CadenceView(BaseModel):
    """Une cadence et sa date de prise d'effet (`HEAT-14`)."""

    type: str
    params: dict[str, str | int] = Field(default_factory=dict)
    #: Formulation française, calculée par le serveur (`HEAT-30`).
    label: str
    #: Forme stockée, pour renvoyer la cadence inchangée lors d'une modification.
    serialized: str
    #: `None` sur la cadence courante d'un supplément, qui vient du planning et non du
    #: journal (décision **D3**).
    valid_from: date | None = None


class SourceDescriptor(BaseModel):
    """Une entrée du catalogue de sources (`HEAT-02`)."""

    key: str
    label: str
    unit: str
    #: Ce que le filtre désigne, ou `None` quand la source n'en prend pas.
    filter_label: str | None = None


class Track(BaseModel):
    """Une piste telle qu'elle est rendue au client (`HEAT-01`)."""

    id: int = Field(description="Position de la ligne dans le fichier")
    token: str = Field(description="À renvoyer en « If-Match » pour modifier ou supprimer")
    track_id: str = Field(description="Identifiant stable, utilisé par les grilles")
    label: str
    source: str
    #: Repris du catalogue : l'écran n'a pas à traduire une clé technique.
    source_label: str
    unit: str
    filter: str
    validation_threshold: float
    #: Quatre bornes croissantes. Vide en mode binaire.
    levels: list[float] = Field(default_factory=list)
    binary: bool
    accent: str
    position: int
    active: bool
    created: date | None = None
    #: Cadence en vigueur aujourd'hui.
    cadence: CadenceView
    #: Journal des prises d'effet, la plus ancienne en premier (`HEAT-14`).
    cadence_history: list[CadenceView] = Field(default_factory=list)


class TrackPayload(BaseModel):
    """Création d'une piste (`HEAT-18`)."""

    label: Label
    source: str = Field(min_length=1, max_length=40)
    filter: str = Field(default="", max_length=200)
    validation_threshold: float = Field(default=1, ge=0, le=1_000_000)
    levels: list[float] = Field(default_factory=list, max_length=4)
    binary: bool = False
    accent: str = "signal"
    #: Forme sérialisée — `window:min_count=1;window_days=2`.
    cadence: str = "daily"
    active: bool = True

    @field_validator("accent")
    @classmethod
    def known_accent(cls, value: str) -> str:
        if value not in ACCENTS:
            raise ValueError(f"accent inconnu : {value}")
        return value

    @field_validator("cadence")
    @classmethod
    def readable_cadence(cls, value: str) -> str:
        """La cadence est validée **à la saisie**, pas à la lecture.

        Une cadence illisible enregistrée aujourd'hui se découvrirait dans six mois, au
        moment de juger un historique — trop tard pour savoir ce qui était voulu.
        """
        try:
            return Cadence.parse(value).serialize()
        except CadenceError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("levels")
    @classmethod
    def increasing_levels(cls, value: list[float]) -> list[float]:
        """Quatre bornes croissantes (`HEAT-15`).

        Des bornes désordonnées rendraient l'intensité incalculable : `1;6;3;10` ne
        décrit aucun gradient.
        """
        if value and value != sorted(value):
            raise ValueError("les seuils d'intensité doivent être croissants")
        if len(set(value)) != len(value):
            raise ValueError("deux seuils d'intensité identiques")
        return value


class TrackUpdate(TrackPayload):
    """Modification d'une piste (`HEAT-19`, `HEAT-20`).

    Même forme que la création : l'écran renvoie la piste entière, cadence comprise. Le
    service décide seul de ce qui est versionné et de ce qui est rétroactif — le client
    n'a pas à connaître cette asymétrie, il en reçoit le compte rendu.
    """


class TrackSaved(BaseModel):
    """Compte rendu d'une modification.

    `HEAT-20` exige que le recalcul rétroactif de l'historique soit **annoncé**. Il ne
    suffit pas de l'appliquer : un seuil de validation abaissé peut faire passer trente
    journées de manquées à validées, et l'utilisateur doit savoir que sa grille vient de
    changer de sens.
    """

    track: Track
    #: Vrai quand la modification a rejugé le passé (seuil de validation, seuils
    #: d'intensité). Faux quand elle ne vaut que pour l'avenir (cadence).
    recalculated_history: bool = False
    #: Messages en français, prêts à afficher. Le client décide sur les booléens.
    warnings: list[str] = Field(default_factory=list)


class OffDay(BaseModel):
    """Une plage neutralisée (`HEAT-06`)."""

    id: int
    token: str
    off_id: str
    #: Vide = toutes les pistes.
    track_id: str
    date_from: date
    date_to: date
    reason: str
    days: int = Field(description="Nombre de jours couverts, bornes comprises")


class OffDayPayload(BaseModel):
    track_id: str = Field(default="", max_length=40)
    #: Neutraliser l'avenir n'a pas de sens : on ne sait pas encore qu'on sera malade.
    date_from: PastDate
    date_to: PastDate
    reason: Note = ""

    @model_validator(mode="after")
    def ordered(self) -> OffDayPayload:
        """Une plage à l'envers ne couvrirait aucun jour, et l'utilisateur croirait sa
        semaine neutralisée."""
        if self.date_to < self.date_from:
            raise ValueError("la fin de la plage précède son début")
        return self


class Order(BaseModel):
    """Nouvel ordre d'affichage (`HEAT-22`)."""

    track_ids: list[str] = Field(min_length=1, max_length=100)


class TracksView(BaseModel):
    """Réponse unique de l'écran de configuration."""

    tracks: list[Track]
    #: Catalogue des sources : l'écran de création n'en code aucune (`HEAT-02`).
    sources: list[SourceDescriptor]
    off_days: list[OffDay]
    #: Piste mise en avant (`HEAT-22`), réglage `heatmap_metric`.
    highlight: str
    accents: list[str] = Field(default_factory=lambda: list(ACCENTS))
