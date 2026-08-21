"""Formes échangées avec le client pour le domaine Activité.

Les durées et distances entrent en **texte** : `44:12`, `8,40`, `1h30`. La normalisation
se fait ici, à la frontière, pour que le domaine ne voie jamais que des minutes décimales
(`ACT-01`).
"""

from __future__ import annotations

from datetime import date, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.parsing import (
    ParseError,
    pace_min_per_km,
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
    LoadKg,
    Note,
    PaceMinKm,
    PastDate,
    Reps,
    Rpe,
    Sets,
)

# ── Saisies souples ───────────────────────────────────


def _duration(value: str | float) -> float:
    try:
        return parse_duration_minutes(value)
    except ParseError as exc:
        raise ValueError(str(exc)) from exc


def _distance(value: str | float) -> float:
    try:
        return parse_distance_km(value)
    except ParseError as exc:
        raise ValueError(str(exc)) from exc


# ── Paliers saisis (`ACT-19`) ─────────────────────────
#
# Déclarés **avant** `RunPayload`, qui les porte : une référence avant définition laisserait
# le modèle inachevé jusqu'à un `model_rebuild()` que personne ne pense à appeler.


class RunSplitPayload(BaseModel):
    """Un palier tel qu'il arrive d'un import, **avant** relecture.

    Les champs entrent en texte comme partout ailleurs à cette frontière (`ACT-01`) :
    `05:06` est une durée, `5'06"` une allure. Le modèle recopie, cette classe normalise,
    et rien entre les deux ne convertit.

    Il n'y a **pas** de champ `partial` : le drapeau se déduit des durées, côté serveur,
    et l'accepter d'un client reviendrait à laisser décider ce qui fausse toutes les
    moyennes de la page.
    """

    index: int = Field(ge=1, le=500, description="Numéro du palier, lu sur la ligne")
    #: Le temps du palier. `05:06` vaut cinq minutes six secondes — même lecture qu'une
    #: durée de séance, par le même analyseur (`ACT-01`).
    duration_s: float = Field(gt=0, le=86400)
    pace_min_km: PaceMinKm | None = None
    cadence_spm: CadenceSpm | None = None
    avg_hr: HeartRate | None = None
    elevation_m: ElevationM | None = None

    @field_validator("duration_s", mode="before")
    @classmethod
    def read_duration(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return round(_duration(value) * 60, 1)

    @field_validator("pace_min_km", mode="before")
    @classmethod
    def read_pace(cls, value: object) -> object:
        if isinstance(value, str):
            return None if not value.strip() else _duration(value)
        return value

    @field_validator("cadence_spm", "avg_hr", "elevation_m", mode="before")
    @classmethod
    def read_optional_number(cls, value: object) -> object:
        if isinstance(value, str):
            return None if not value.strip() else round(parse_decimal(value))
        return value


# ── Courses ───────────────────────────────────────────


class RunPayload(BaseModel):
    """Saisie d'une course (`ACT-01`).

    ## Distance et allure : deux lectures du même trajet

    Elles ne sont pas indépendantes — `allure = durée ÷ distance` —, et **le serveur en
    calcule toujours une** à partir de l'autre. C'est l'invariant « aucun calcul métier
    côté client » appliqué à un cas où le client aurait été tenté de le faire.

    Trois formes de saisie sont donc acceptées, et la durée est requise dans les trois :

    | Ce qui est envoyé | Ce que le serveur en fait |
    |---|---|
    | distance seule | il calcule l'allure — c'est le cas historique, inchangé |
    | allure seule | il calcule la distance |
    | les deux | **l'allure gagne**, la distance est recalculée |

    Le dernier cas mérite sa règle. Il survient quand on corrige l'allure d'une course
    déjà saisie : les trois nombres à l'écran deviennent incohérents entre eux, et il faut
    dire lequel fait foi. C'est l'allure, parce que c'est le champ qu'on vient de toucher —
    et une distance qu'on n'a pas corrigée est une distance qu'on ne défend pas.
    """

    date: PastDate
    #: Accepte `44:12`, `1:18:44`, `44`, `1h30`.
    duration_min: DurationMin
    #: Accepte `8,40`, `8.4`, `5mi`. Facultative **si** l'allure est donnée.
    distance_km: DistanceKm | None = None
    #: Accepte `5:16` ou `5,27`. Même lecture qu'une durée : `5:16` vaut 5 min 16 s par
    #: kilomètre. Un second analyseur pour la même écriture divergerait du premier.
    pace_min_km: PaceMinKm | None = None
    avg_hr: HeartRate | None = None
    elevation_m: ElevationM | None = None
    cadence_spm: CadenceSpm | None = None
    note: Note | None = None
    #: Calories **totales**, métabolisme de base compris — le second des deux chiffres
    #: qu'affiche une capture Apple. Le nom porte le qualificatif parce que « calories »
    #: tout court désignerait tantôt l'un tantôt l'autre.
    total_calories: Calories | None = None
    #: Bornes horaires de la séance. Acceptent `7:40 PM` comme `19:40`.
    start_time: time | None = None
    end_time: time | None = None
    #: Longueur d'un palier plein : 1 pour « 1 Kilometer », 1,609 pour « 1 Mile ».
    split_length_km: DistanceKm | None = None
    #: Les paliers, quand ils viennent avec — un import de captures, jamais une saisie au
    #: clavier. Vide par défaut : les appelants d'avant ne changent pas d'un caractère, et
    #: une course sans paliers reste une course entière.
    splits: list[RunSplitPayload] = Field(default_factory=list)

    @field_validator("distance_km", mode="before")
    @classmethod
    def read_distance(cls, value: object) -> object:
        if isinstance(value, str):
            return None if not value.strip() else _distance(value)
        return value

    @field_validator("split_length_km", mode="before")
    @classmethod
    def read_split_length(cls, value: object) -> object:
        if isinstance(value, str):
            return None if not value.strip() else _distance(value)
        return value

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def read_clock(cls, value: object) -> object:
        """`7:40 PM` autant que `19:40`.

        Une borne illisible vaut `None` et non une erreur : c'est un contexte, et refuser
        la course entière parce qu'une heure d'horloge a mal été lue serait perdre une
        mesure pour un ornement.
        """
        if not isinstance(value, str):
            return value
        return parse_clock_time(value)

    @field_validator("duration_min", mode="before")
    @classmethod
    def read_duration(cls, value: object) -> object:
        return _duration(value) if isinstance(value, str) else value

    @field_validator("pace_min_km", mode="before")
    @classmethod
    def read_pace(cls, value: object) -> object:
        if isinstance(value, str):
            return None if not value.strip() else _duration(value)
        return value

    @field_validator("avg_hr", "elevation_m", "cadence_spm", mode="before")
    @classmethod
    def read_optional_number(cls, value: object) -> object:
        if isinstance(value, str):
            return None if not value.strip() else round(parse_decimal(value))
        return value

    @model_validator(mode="after")
    def resolve_distance_and_pace(self) -> RunPayload:
        """Complète l'une depuis l'autre, et refuse une course qui n'a ni l'une ni l'autre.

        Fait **ici** et non dans le service : c'est la frontière du domaine, et une course
        dont on ne connaît que la durée n'est pas une course incomplète — c'est une saisie
        qu'on ne sait pas interpréter, donc un refus de validation (`API-06`).
        """
        if self.pace_min_km is not None:
            # L'allure fait foi : la distance en découle, y compris quand elle était là.
            object.__setattr__(self, "distance_km", round(self.duration_min / self.pace_min_km, 3))
        elif self.distance_km is not None:
            object.__setattr__(
                self, "pace_min_km", pace_min_per_km(self.distance_km, self.duration_min)
            )
        else:
            raise ValueError("une course a besoin de sa distance ou de son allure")
        return self


class Run(BaseModel):
    """Course rendue au client, allure comprise (`ACT-05`)."""

    id: int
    token: str
    date: date
    distance_km: float
    duration_min: float
    pace_min_km: float | None = None
    #: Vitesse moyenne en km/h — l'autre lecture de la même mesure.
    speed_kmh: float | None = None
    avg_hr: int | None = None
    elevation_m: int | None = None
    cadence_spm: int | None = None
    note: str | None = None
    source: str
    #: Identifiant stable, celui auquel les paliers se rattachent. Vide sur une course
    #: enregistrée avant le lot C08 : elle n'a pas de paliers, et `id` suffit à la corriger.
    run_id: str = ""
    total_calories: int | None = None
    start_time: time | None = None
    end_time: time | None = None
    split_length_km: float | None = None
    #: Ce que la page Course peut montrer sans redemander. Zéro veut dire « aucun palier
    #: relevé », qui est le cas de toutes les courses saisies au clavier — pas une erreur.
    splits: int = 0


# ── Paliers rendus au client (`ACT-19`) ───────────────


class RunSplit(BaseModel):
    """Un palier rendu au client, sa longueur réelle comprise."""

    index: int
    duration_s: float
    distance_km: float | None = None
    pace_min_km: float | None = None
    cadence_spm: int | None = None
    avg_hr: int | None = None
    elevation_m: int | None = None
    #: Reliquat de distance et non kilomètre entier. L'écran le marque et grise son
    #: allure, qui est une extrapolation de l'application et non une mesure.
    partial: bool = False
    #: Part de la barre de cadence, entre 0 et 1 — calculée ici pour que l'écran n'ait
    #: aucun `Math.max` à faire sur une collection de mesures.
    cadence_ratio: float | None = None


class RunSplits(BaseModel):
    """Les paliers d'une course et ce qu'ils disent d'elle (`ACT-19`).

    Tout ce qui se moyenne ici écarte les paliers partiels : c'est la règle du domaine, et
    elle vit dans `splits.py`, jamais à l'écran.
    """

    splits: list[RunSplit] = Field(default_factory=list)
    full_count: int = 0
    partial_count: int = 0
    #: Secondes par kilomètre, seconde moitié moins première. **Négative = accélération**,
    #: ce qui est contre-intuitif au premier regard : l'écran doit le dire en toutes
    #: lettres plutôt que de montrer le signe seul.
    drift_s_per_km: float | None = None
    first_half_pace_min_km: float | None = None
    second_half_pace_min_km: float | None = None
    fastest_index: int | None = None
    slowest_index: int | None = None
    #: Bornes de l'axe d'allure, le plus lent d'abord : c'est ainsi que le graphique
    #: retourne l'axe sans que l'écran ait à décider quoi que ce soit.
    pace_domain_min_km: tuple[float, float] | None = None
    cadence_max_spm: int | None = None


class RunDetail(BaseModel):
    """Ce que la page Course affiche : une course et ses paliers.

    `run` est **nullable** parce que l'écran a besoin de distinguer deux silences que rien
    d'autre ne sépare : « aucune course enregistrée » — auquel cas il dit ce que coûte le
    prochain geste — et « le serveur n'a pas répondu », qui est une panne. Un `404` sur
    l'adresse « la dernière course » aurait confondu les deux.
    """

    run: Run | None = None
    splits: RunSplits = Field(default_factory=RunSplits)


# ── Séances ───────────────────────────────────────────


class ExerciseEntryPayload(BaseModel):
    """Une performance à consigner (`ACT-07`)."""

    exercise_id: str = Field(min_length=1, max_length=40)
    #: `0` = poids du corps, valeur légitime et non une absence.
    weight_kg: LoadKg = 0
    sets: Sets = 1
    reps: Reps = 1
    note: Note | None = None

    @field_validator("weight_kg", mode="before")
    @classmethod
    def read_load(cls, value: object) -> object:
        return parse_decimal(value) if isinstance(value, str) and value.strip() else value


class WorkoutPayload(BaseModel):
    """Saisie d'une séance (`ACT-03`, `ACT-18`).

    ## Les exercices peuvent venir avec

    Ils étaient forcément **après** : on créait la séance, puis on consignait chaque série
    par un appel de plus. C'est la bonne forme quand on consigne au fil de la séance, et
    c'est celle que le journal garde. Mais l'assistant de saisie (C06) et l'import de
    notes (C07) construisent une séance entière avant de rien écrire, et pour eux la
    séparation avait un coût visible : abandonner l'assistant après avoir passé la
    première étape laissait une séance vide dans l'historique.

    `exercises` est donc facultatif et vaut la liste vide — les appelants d'avant ne
    changent pas d'un caractère.

    **Ce n'est pas une transaction**, et il ne faut pas le laisser croire : le stockage
    est un dépôt CSV sur WebDAV, il n'en a pas. Ce que le service garantit est plus
    modeste et suffit au cas réel : **tous les exercices sont résolus avant la première
    écriture**, donc un identifiant inconnu — le seul échec courant — refuse la demande
    entière sans avoir rien écrit. Une panne de stockage au milieu, elle, laisse une
    séance partielle, comme n'importe quelle autre écriture du projet.
    """

    date: PastDate
    type: Label
    duration_min: DurationMin
    calories: Calories | None = None
    rpe: Rpe | None = None
    note: Note | None = None
    exercises: list[ExerciseEntryPayload] = Field(default_factory=list, max_length=60)

    @field_validator("duration_min", mode="before")
    @classmethod
    def read_duration(cls, value: object) -> object:
        return _duration(value) if isinstance(value, str) else value

    @field_validator("calories", "rpe", mode="before")
    @classmethod
    def read_optional_number(cls, value: object) -> object:
        if isinstance(value, str):
            return None if not value.strip() else round(parse_decimal(value))
        return value


class ExerciseEntry(BaseModel):
    id: int
    token: str
    workout_id: str
    date: date
    exercise_id: str
    exercise_name: str
    muscle_group: str
    weight_kg: float
    sets: int
    reps: int
    note: str | None = None
    #: Charge × séries × réps (`ACT-14`).
    volume_kg: float
    #: 1RM estimé par Epley (`ACT-15`). `None` au poids du corps.
    one_rep_max_kg: float | None = None


class Workout(BaseModel):
    """Séance rendue au client, avec ses exercices."""

    id: int
    token: str
    workout_id: str
    date: date
    type: str
    duration_min: float
    calories: int | None = None
    rpe: int | None = None
    note: str | None = None
    source: str
    exercises: list[ExerciseEntry] = Field(default_factory=list)
    #: Tonnage total de la séance.
    volume_kg: float = 0


# ── Catalogue d'exercices (`ACT-06`) ──────────────────


class ExercisePayload(BaseModel):
    name: Label
    muscle_group: str
    #: Les autres façons d'écrire cet exercice (`C07`). Absent = inchangé, `[]` = effacé.
    #:
    #: `None` et liste vide se distinguent volontairement : le formulaire du catalogue ne
    #: parle pas d'alias et ne doit pas les effacer en corrigeant un nom, alors que la
    #: validation d'une note en ajoute un explicitement.
    aliases: list[Label] | None = None

    @field_validator("aliases", mode="before")
    @classmethod
    def clean_aliases(cls, value: object) -> object:
        """Sans doublon, sans vide, et **sans point-virgule** — c'est le séparateur.

        Un alias qui en contiendrait un couperait la cellule en deux à la relecture, et
        ferait apparaître un alias qui n'a jamais été saisi.
        """
        if not isinstance(value, list):
            return value
        seen: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            cleaned = item.replace(";", " ").strip()
            if cleaned and cleaned.casefold() not in {other.casefold() for other in seen}:
                seen.append(cleaned)
        return seen

    @field_validator("muscle_group")
    @classmethod
    def known_group(cls, value: str) -> str:
        from app.domains.activity.models import MuscleGroup

        if value not in {group.value for group in MuscleGroup}:
            raise ValueError(f"groupe musculaire inconnu : {value}")
        return value


class NoteLine(BaseModel):
    """Un exercice lu dans une note, avant toute écriture (`C07`).

    Tout est facultatif sauf le nom : une note qui dit « tractions 3xmax » ne porte ni
    répétitions ni charge, et remplir ces champs les inventerait. L'écran affiche le vide
    et l'utilisateur complète — ou pas.
    """

    name: str = Field(max_length=80)
    muscle_group: str = "autre"
    sets: int | None = None
    reps: int | None = None
    #: `0` = poids du corps, valeur légitime (`ACT-07`). `None` = charge absente ou
    #: exprimée dans une unité qu'on ne convertit pas.
    weight_kg: float | None = None
    #: Pourquoi la charge est vide, quand il y a une raison à dire — « charge en lbs, non
    #: convertie ». Sans elle, la ligne passerait pour une lecture ratée.
    note: str | None = None
    #: Ce que la ligne coûterait si on la validait :
    #:
    #: * `known` — l'exercice existe, rien à écrire au catalogue ;
    #: * `alias` — même exercice sous un autre nom : la graphie de la note s'ajoute en
    #:   alias, et le nom du catalogue s'impose ;
    #: * `new` — absent du catalogue, à créer avec le groupe déduit.
    #:
    #: Les deux derniers se valident **un par un** à l'écran : une fusion erronée est
    #: difficile à défaire et pollue l'historique.
    status: Literal["known", "alias", "new"] = "new"
    exercise_id: str | None = None
    #: Sur un `alias` : la graphie de la note, qui sera ajoutée à l'exercice du catalogue.
    #: `name`, lui, porte déjà le nom du catalogue — c'est lui qui s'impose.
    alias_of: str | None = None


class NoteDraft(BaseModel):
    """Ce qu'une note a produit. **Rien n'est écrit** tant que rien n'est validé."""

    lines: list[NoteLine] = Field(default_factory=list)
    #: Le texte réellement lu — celui qui a été tapé, ou celui que l'OCR a tiré de la
    #: photo. Affiché pour que l'utilisateur voie **ce que le modèle a vu** quand une
    #: ligne le surprend.
    source_text: str = ""


class Exercise(BaseModel):
    id: int
    token: str
    exercise_id: str
    name: str
    muscle_group: str
    #: Les autres écritures reconnues pour cet exercice (`C07`).
    aliases: list[str] = Field(default_factory=list)
    #: Séries déjà consignées sur cet exercice. Dit ce qu'un retrait laisse intact
    #: (`ACT-06`) et ce qu'une correction de nom ou de groupe répercute.
    entries: int = 0
    #: Dernière performance, pour choisir sa charge sans consulter l'historique (`ACT-08`).
    last_weight_kg: float | None = None
    last_reps: int | None = None
    last_sets: int | None = None
    last_date: date | None = None


# ── Historique et agrégats ────────────────────────────


class ActivityItem(BaseModel):
    """Ligne de l'historique fusionné courses + séances (`ACT-13`)."""

    kind: str = Field(description="« run » ou « workout »")
    id: int
    token: str
    date: date
    label: str
    duration_min: float
    distance_km: float | None = None
    pace_min_km: float | None = None
    rpe: int | None = None
    #: Séries rattachées, pour une séance. Supprimer une séance les purge (`ACT-04`) : la
    #: ligne doit pouvoir dire ce qu'elle emporte **avant** que le geste ne s'arme.
    entries: int = 0
    source: str


class DayVolume(BaseModel):
    """Un jour de la semaine (`ACT-10`)."""

    date: date
    weekday: int = Field(description="1 = lundi, 7 = dimanche")
    minutes: float
    #: Distingué d'un jour à zéro minute : un jour de repos est un choix, pas un trou.
    rest: bool


class WeekTotals(BaseModel):
    """Totaux de la semaine en cours (`ACT-11`), remis à zéro le lundi."""

    week_start: date
    minutes: float
    sessions: int
    distance_km: float
    pace_min_km: float | None = None


class WeekVolume(BaseModel):
    """Une des huit dernières semaines (`ACT-12`)."""

    week_start: date
    minutes: float
    sessions: int
    #: Part de la semaine la plus chargée de la fenêtre, entre 0 et 1.
    #:
    #: **Servi, et non déduit à l'écran.** Le tableau de bord le dérivait d'un
    #: `Math.max(...weeks.map(…))` en TypeScript : un maximum sur une série *est* une
    #: dérivation, et deux implémentations de la même échelle divergent au premier cas
    #: limite — ici, une fenêtre entièrement vide. Toutes les semaines à zéro rendent 0,
    #: jamais une division par zéro déguisée en barre pleine.
    ratio: float = Field(default=0.0, ge=0, le=1)


class TrainingSplit(BaseModel):
    """Une part de la répartition courses / musculation (`AGG-02`)."""

    kind: str = Field(description="« run », « strength » ou « other »")
    label: str
    sessions: int
    minutes: float
    #: Part des séances, entre 0 et 1.
    ratio: float = Field(ge=0, le=1)


class TrainingTotals(BaseModel):
    """Totaux d'entraînement du tableau de bord (`AGG-02`).

    Vit dans le domaine Activité et non dans les agrégats : c'est de l'arithmétique
    d'activité, et la semaine en cours comme les huit dernières y sont déjà calculées
    (`ACT-11`, `ACT-12`). Les agrégats assemblent, ils ne recalculent pas.
    """

    sessions_total: int
    minutes_total: float
    week: WeekTotals
    #: Les huit dernières semaines, la plus ancienne en premier.
    weeks: list[WeekVolume]
    split: list[TrainingSplit]


class MuscleVolume(BaseModel):
    """Tonnage par groupe musculaire (`ACT-14`)."""

    muscle_group: str
    volume_kg: float
    sets: int


class NeglectedGroup(BaseModel):
    """Jours depuis la dernière sollicitation (`ACT-16`)."""

    muscle_group: str
    days_since: int | None = None
    last_date: date | None = None


class ExerciseProgress(BaseModel):
    """Progression d'un exercice (`ACT-09`, `ACT-15`)."""

    exercise_id: str
    name: str
    muscle_group: str
    last_weight_kg: float | None = None
    last_date: date | None = None
    #: Écart de charge avec la fois précédente.
    delta_kg: float | None = None
    #: Série de la charge maximale par séance.
    max_series: list[float] = Field(default_factory=list)
    dates: list[date] = Field(default_factory=list)
    best_weight_kg: float | None = None
    best_one_rep_max_kg: float | None = None


class ActivityOverview(BaseModel):
    """Tout ce qu'affiche l'écran Activité, en une requête."""

    #: Le jour, dans le fuseau local du serveur. L'écran date ses saisies avec lui et ne
    #: consulte jamais l'horloge du téléphone : c'est l'invariant « le jour vient du
    #: serveur », que `/nutrition` avait cassé au lot D pour l'avoir oublié.
    today: date
    week: WeekTotals
    days: list[DayVolume]
    weeks: list[WeekVolume]
    muscles: list[MuscleVolume]
    neglected: list[NeglectedGroup]
    history: list[ActivityItem]
    total: int
