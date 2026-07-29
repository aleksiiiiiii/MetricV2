"""Formes échangées pour le moteur d'assiduité (spec `HEAT` v2, §8).

Une piste est de la **configuration**, pas une mesure. Ce qui circule dans la première
moitié de ce module décrit donc ce qu'on attend — source, seuil, cadence, seuils
d'intensité — et jamais ce qui s'est passé. La seconde moitié, les grilles, est
l'inverse : ce qui s'est passé, jugé par le moteur, et rien qui s'édite.

Deux choses sont servies au client qu'il aurait pu déduire : le **libellé de la cadence**
et le **catalogue des sources**. Dans les deux cas c'est délibéré — `HEAT-30` interdit au
client de réimplémenter la moindre règle de cadence, et une liste de sources recopiée
dans le frontend cesserait de décrire le serveur au premier ajout.

Les formes de grille — tout ce qui vient après `RangeView` — suivent le §8 de la spec au
mot près : `from`/`to` plutôt que `start`/`end`, `days`, `weeks`, `stats`. Le contrat
publié est celui qui a été écrit, pas sa traduction en noms Python.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


# ── Grilles (spec §8, `HEAT-24` → `HEAT-29`) ──────────


class RangeView(BaseModel):
    """Plage évaluée, bornes comprises.

    `from` est un mot réservé de Python : le champ s'appelle `from_` dans le code et
    `from` dans le JSON. Renommer la clé publique en `start` aurait été plus simple à
    écrire et aurait fait mentir le contrat de la spec.
    """

    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date


class DayView(BaseModel):
    """Une cellule (`HEAT-24`)."""

    date: date
    value: float
    #: `off` · `missed` · `done` · `bonus` (`HEAT-05`).
    state: str
    #: 0 à 4 (`HEAT-15`). Nul sur tout ce qui n'est pas validé.
    level: int
    #: Pourquoi ce jour est `off`, quand ce n'est pas la cadence qui l'a décidé :
    #: `neutralised`, `before_track`, `future`, `pending`. `None` sinon.
    #:
    #: Sert **uniquement** à l'affichage. Le client peint dessus, il n'en déduit rien :
    #: c'est `state` qui dit si le jour compte, et lui seul.
    reason: str | None = None


class WeekView(BaseModel):
    """Statut d'une semaine ISO, pour une piste `per_week` (`HEAT-28`).

    Le rouge d'une piste hebdomadaire se pose **ici** et jamais sur un jour : `HEAT-11`
    interdit qu'un jour non validé d'une telle piste soit `missed`. Un écran qui
    chercherait des jours rouges sur « torse 2×/semaine » y verrait un sans-faute
    permanent.
    """

    start: date
    #: `reached` · `partial` · `missed` · `off`.
    status: str
    done: int
    expected: int


class StatsView(BaseModel):
    """Les chiffres d'une grille (`HEAT-26`, `HEAT-27`)."""

    validated_days: int
    #: Sur une piste hebdomadaire ce sont des **créneaux**, pas des jours.
    expected_days: int
    #: `None` quand rien n'était attendu — un taux de respect sans attente n'existe pas,
    #: et zéro se lirait comme un échec (`HEAT-07`).
    compliance: float | None = None
    longest_streak: int
    current_streak: int
    #: `None` en binaire : une prise ne bat pas une prise.
    best_day: date | None = None
    best_value: float | None = None
    total: float


class GridTrack(BaseModel):
    """La piste telle que la grille la décrit.

    Plus courte que `Track` : ni jeton, ni journal de cadences, ni position. Une grille
    se lit, elle ne s'édite pas — servir de quoi modifier la piste depuis l'écran de
    lecture inviterait à écrire sans avoir rechargé.
    """

    id: str
    label: str
    #: Unité de la source, pour l'infobulle : « série », « ml », « km ».
    unit: str
    binary: bool
    accent: str
    source: str
    #: Bornes d'intensité, pour légender le gradient. Vide en binaire.
    levels: list[float] = Field(default_factory=list)
    validation_threshold: float
    created: date | None = None


class GridView(BaseModel):
    """Grille d'une piste (`HEAT-24`), forme du §8."""

    track: GridTrack
    cadence: CadenceView
    range: RangeView
    days: list[DayView]
    #: Renseigné pour les seules pistes `per_week`, `null` sinon.
    weeks: list[WeekView] | None = None
    stats: StatsView


class GridsView(BaseModel):
    """Plusieurs grilles sur la même plage (`HEAT-25`).

    La plage est remontée d'un cran : les neuf grilles la partagent, et la répéter neuf
    fois inviterait un client à les afficher désalignées.
    """

    range: RangeView
    grids: list[GridView]


class TrackImpact(BaseModel):
    """Ce qu'une modification ferait à l'historique — **avant** de la valider.

    `HEAT-20` et la décision **D4** exigent que le recalcul rétroactif soit annoncé, et
    l'annoncer sans le chiffrer ne renseigne personne : « ta grille va changer » est vrai
    de tout et n'aide à décider de rien. Le lot L09 n'avait livré que l'avertissement,
    faute de moteur ; le compte s'obtient en évaluant la grille deux fois — avec l'ancienne
    configuration et avec la nouvelle — et en comparant les états jour par jour.

    Le calcul ne touche à rien : c'est une simulation, et aucun fichier n'est écrit.
    """

    #: Vrai quand la modification rejuge le passé. Faux pour un simple changement de
    #: cadence, qui ne vaut que pour l'avenir (`HEAT-14`).
    retroactive: bool
    #: Plage sur laquelle la comparaison a été faite.
    range: RangeView
    #: Jours dont l'**état** changerait.
    changed_days: int
    #: Validés qui deviendraient manqués. Le chiffre que cite la spec.
    to_missed: int
    #: Manqués qui deviendraient validés.
    to_done: int
    #: Jours qui gardent leur état mais changent d'intensité — le cas d'un seuil de
    #: gradient déplacé seul. Sans lui, une modification bien réelle s'annoncerait comme
    #: « aucun jour ne change », et l'utilisateur croirait son réglage sans effet.
    restyled: int
    #: Phrases françaises prêtes à afficher. Le client décide sur les nombres.
    warnings: list[str] = Field(default_factory=list)


class DayEntry(BaseModel):
    """Une ligne de saisie sous une cellule (`HEAT-29`).

    Des **nombres**, pas des phrases : le client compose son libellé. Les champs sont
    larges parce que six sources très différentes s'y expriment, et nuls quand ils n'ont
    pas de sens pour la source en question.
    """

    label: str
    #: Contribution de cette ligne au total du jour.
    value: float
    unit: str
    time: datetime | None = None
    sets: int | None = None
    reps: int | None = None
    weight_kg: float | None = None
    muscle_group: str | None = None
    distance_km: float | None = None
    duration_min: float | None = None
    pace_min_km: float | None = None
    dose: float | None = None
    dose_unit: str | None = None
    note: str | None = None


class DayInspection(BaseModel):
    """Détail explorable d'une cellule (`HEAT-29`).

    La cellule **et** ce qui la compose. Rendre les seules lignes de saisie obligerait le
    client à retrouver l'état du jour dans la grille dont il vient — et à le recalculer
    s'il ne l'a plus, ce que `HEAT-30` interdit.
    """

    track: GridTrack
    day: DayView
    #: Vide quand rien n'a été saisi, ou quand la source ne sait pas se détailler.
    entries: list[DayEntry] = Field(default_factory=list)
