"""Formes échangées avec le client pour le domaine Activité.

Les durées et distances entrent en **texte** : `44:12`, `8,40`, `1h30`. La normalisation
se fait ici, à la frontière, pour que le domaine ne voie jamais que des minutes décimales
(`ACT-01`).
"""

from __future__ import annotations

from datetime import date, time
from typing import Annotated, Literal

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
from app.domains.activity import circuit_link as _link
from app.domains.activity.models import MuscleGroup

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
    #: Calories **actives** — la dépense de la séance seule, sans le métabolisme de base.
    active_calories: Calories | None = None
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
    #: Les deux chiffres de calories d'une capture Apple, distincts et nommés : 439
    #: actives, 492 totales. « Calories » sans qualificatif voudrait dire les deux.
    active_calories: int | None = None
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
    #: L'autre lecture de l'allure, pour qui lit en km/h plutôt qu'en minutes par km.
    speed_kmh: float | None = None
    #: Longueur de foulée, en mètres par pas — `distance ÷ (cadence × durée)`.
    stride_m: float | None = None
    #: Écart à l'allure moyenne des paliers pleins, en secondes par kilomètre.
    #: **Négatif = plus rapide que la moyenne.**
    delta_s_per_km: float | None = None
    #: Part **signée** de la barre divergente, entre -1 et 1. Le signe porte le sens et la
    #: valeur absolue la longueur : l'écran ne cherche ni maximum ni sens dans la liste.
    deviation_ratio: float | None = None
    #: Écart à la cadence moyenne, en pas par minute, et sa barre signée.
    #:
    #: **Une part de la cadence maximale ne montrait rien.** De 158 à 174 pas par minute,
    #: les barres tenaient toutes entre 91 % et 100 % de leur rail : neuf barres pleines,
    #: visuellement identiques, pour une variation de seize pas qui est précisément ce
    #: qu'on venait regarder. L'écart à la moyenne, lui, se voit.
    cadence_delta_spm: float | None = None
    cadence_deviation_ratio: float | None = None


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

    # ── Régularité ────────────────────────────────────
    #
    # Une course de 8 km à 5'02" peut être huit kilomètres identiques ou quatre sprints et
    # quatre marches. La moyenne ne les distingue pas ; ces trois-là si.

    average_pace_min_km: float | None = None
    fastest_pace_min_km: float | None = None
    slowest_pace_min_km: float | None = None
    pace_spread_s_per_km: float | None = None
    pace_sd_s_per_km: float | None = None
    negative_split: bool | None = None

    # ── Cadence et foulée ─────────────────────────────

    cadence_avg_spm: int | None = None
    cadence_min_spm: int | None = None
    #: **Positive = la foulée s'accélère** — le signe inverse de celui de la dérive
    #: d'allure. Deux sens opposés pour deux dérives : l'écran nomme chacun.
    cadence_drift_spm: float | None = None
    stride_avg_m: float | None = None
    stride_min_m: float | None = None
    stride_max_m: float | None = None
    deviation_max_s_per_km: float | None = None


class RunMark(BaseModel):
    """Une course de l'historique, réduite à ce qu'une courbe de tendance en montre."""

    id: int
    date: date
    distance_km: float
    pace_min_km: float | None = None
    #: Celle qu'on regarde. C'est le serveur qui la désigne — l'écran ne compare pas des
    #: identifiants pour retrouver le point à mettre en avant.
    current: bool = False


class RunContext(BaseModel):
    """Ce que l'historique dit de cette course-ci (`ACT-19`).

    **Un rang n'est pas un classement absolu.** Comparer l'allure d'un 8 km à celle d'un
    3 km est bancal, et le taire serait pire que le dire : `runs_compared` accompagne
    toujours le rang, pour que l'écran puisse écrire « 2ᵉ sur 14 » et non « 2ᵉ ».
    """

    #: Nombre de courses de l'historique, celle-ci comprise.
    runs_compared: int = 0
    #: Rang d'allure, `1` = la plus rapide. `None` quand la course n'a pas d'allure.
    pace_rank: int | None = None
    distance_rank: int | None = None
    #: Meilleure allure de tout l'historique, et distance la plus longue.
    best_pace_min_km: float | None = None
    longest_distance_km: float | None = None
    #: Moyennes de l'historique, celle-ci comprise — le repère auquel la comparer.
    average_pace_min_km: float | None = None
    average_distance_km: float | None = None
    #: Écarts de cette course aux moyennes. Négatif sur l'allure = plus rapide.
    pace_delta_s_per_km: float | None = None
    distance_delta_km: float | None = None
    #: Les dernières sorties, la plus ancienne d'abord, pour une courbe de tendance.
    recent: list[RunMark] = Field(default_factory=list)
    #: Bornes de l'axe d'allure de cette tendance, **le plus lent d'abord** comme celles
    #: des paliers. Servies plutôt que dérivées : chercher les extrêmes d'une collection
    #: de mesures à l'écran est le calcul que l'invariant interdit, et la page Activité en
    #: porte déjà deux qui restent à retirer.
    pace_domain_min_km: tuple[float, float] | None = None


class DistanceBand(BaseModel):
    """Une bande de distance et son meilleur temps (`ACT-20`).

    **La seule comparaison d'allures honnête de la page.** 5'30" sur 15 km est une
    meilleure course que 5'10" sur 3 km ; à l'intérieur d'une bande, les sorties se
    ressemblent assez pour qu'un record veuille dire quelque chose.
    """

    label: str
    runs: int = 0
    best_pace_min_km: float | None = None
    #: La course qui détient le record, pour que l'écran puisse y mener.
    best_index: int | None = None
    best_day: date | None = None
    average_pace_min_km: float | None = None
    total_distance_km: float = 0.0


class MonthTotals(BaseModel):
    """Un mois de course. C'est ici que « progresser » se lit sans réserve à poser."""

    #: `2026-08`. L'écran le met en forme, il ne le calcule pas.
    month: str
    runs: int = 0
    distance_km: float = 0.0
    minutes: float = 0.0
    pace_min_km: float | None = None


class RunWindow(BaseModel):
    """Les N dernières sorties contre les N précédentes.

    Comparer une course à une course ferait dire à la dernière séance de fractionné que
    la forme s'est effondrée. La fenêtre lisse le mélange des distances sans le faire
    disparaître — et l'écran le dit plutôt que de le taire.
    """

    size: int = 0
    recent_pace_min_km: float | None = None
    previous_pace_min_km: float | None = None
    #: Secondes par kilomètre, récent moins précédent. **Négatif = plus rapide.**
    pace_delta_s_per_km: float | None = None
    recent_distance_km: float | None = None
    previous_distance_km: float | None = None
    distance_delta_km: float | None = None


class RunProgress(BaseModel):
    """La page « Toutes tes courses » (`ACT-20`) : la liste et ce qu'elle raconte.

    Une seule requête : la liste des courses **et** les agrégats. Deux appels auraient
    laissé l'écran assembler deux réponses de fraîcheurs différentes, et c'est exactement
    le genre de recollage que le tableau de bord vient d'abandonner.
    """

    runs: list[Run] = Field(
        default_factory=list, description="Toutes les courses, la plus récente d'abord"
    )
    total_runs: int = 0
    total_distance_km: float = 0.0
    total_minutes: float = 0.0
    #: Distance totale sur temps total, et non la moyenne des allures — une sortie de 2 km
    #: y pèserait autant qu'une de 20.
    overall_pace_min_km: float | None = None

    best_pace_min_km: float | None = None
    best_pace_index: int | None = None
    best_pace_day: date | None = None
    longest_distance_km: float | None = None
    longest_distance_index: int | None = None
    longest_distance_day: date | None = None
    longest_duration_min: float | None = None

    bands: list[DistanceBand] = Field(default_factory=list)
    #: Du plus ancien au plus récent. Les mois sans course sont **absents** : un zéro
    #: inséré se lirait comme une mesure alors qu'il dit qu'on n'a rien enregistré.
    months: list[MonthTotals] = Field(default_factory=list)
    window: RunWindow = Field(default_factory=RunWindow)

    #: Bornes d'allure, **le plus lent d'abord** : l'axe part retourné, comme partout où
    #: ce dépôt trace une allure.
    pace_domain_min_km: tuple[float, float] | None = None
    volume_domain_km: tuple[float, float] | None = None
    #: Bornes de distance, le plus court d'abord — l'abscisse du nuage de points.
    distance_domain_km: tuple[float, float] | None = None


class RunDetail(BaseModel):
    """Ce que la page Course affiche : une course et ses paliers.

    `run` est **nullable** parce que l'écran a besoin de distinguer deux silences que rien
    d'autre ne sépare : « aucune course enregistrée » — auquel cas il dit ce que coûte le
    prochain geste — et « le serveur n'a pas répondu », qui est une panne. Un `404` sur
    l'adresse « la dernière course » aurait confondu les deux.
    """

    run: Run | None = None
    splits: RunSplits = Field(default_factory=RunSplits)
    #: La même course, replacée parmi les autres. Vide quand il n'y en a pas d'autre —
    #: une première course ne se compare à rien, et l'écran le dit plutôt que d'afficher
    #: un rang de 1 sur 1 qui ressemblerait à un record.
    context: RunContext = Field(default_factory=RunContext)


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


# ── Circuits ouverts dans Cadence Tabata (**D2**, **D7**) ─
#
# Les bornes viennent de `circuit_link`, qui les tient de la spécification de Cadence, et
# **non** de `app.core.validation` comme le reste du domaine. La distinction n'est pas
# cosmétique : `Reps` ou `DurationMin` disent ce qui est vraisemblable *pour nous* et se
# discutent ; celles-ci sont le contrat d'une application tierce et ne se discutent pas.
# Les recopier en dur ici ferait diverger le schéma du générateur de lien au premier
# ajustement — le module reste la seule source des nombres.

CircuitRounds = Annotated[int, Field(ge=_link.ROUNDS[0], le=_link.ROUNDS[1])]
CircuitRoundRestS = Annotated[int, Field(ge=_link.ROUND_REST_S[0], le=_link.ROUND_REST_S[1])]
CircuitDurationS = Annotated[int, Field(ge=_link.DURATION_S[0], le=_link.DURATION_S[1])]
CircuitReps = Annotated[int, Field(ge=_link.REPS[0], le=_link.REPS[1])]
CircuitRestS = Annotated[int, Field(ge=_link.REST_S[0], le=_link.REST_S[1])]

#: La note d'un exercice, telle qu'elle tiendra sous son nom pendant l'effort.
#:
#: Soixante caractères et non les 500 de `Note` : `llms.txt` §11 le demande — « les notes
#: sont courtes : elles s'affichent sur une ligne, sous le nom ». Une note qui déborde ne
#: se tronque pas dans Cadence, elle pousse le reste hors de l'écran de quelqu'un qui est
#: en train de forcer. La borne est ici parce que c'est ici qu'on peut encore la refuser.
CircuitNote = Annotated[str, Field(max_length=60)]


class CircuitExercisePayload(BaseModel):
    """Un exercice d'un circuit, tel qu'on le saisit.

    **Exactement un de `duration_s` et `reps`.** À l'écran c'est un sélecteur temps/reps,
    et la sentinelle `-1` du fichier n'apparaît nulle part dans l'API : elle est une
    convention de stockage, pas une valeur qu'on demande à quelqu'un de taper.

    Les deux à la fois seraient une contradiction — la spécification n'a qu'un champ pour
    les porter — et aucun des deux laisserait le service inventer une durée.
    """

    name: Label
    #: Le groupe musculaire, parmi les neuf de Metric. **Exigé**, et c'est un choix de
    #: fond : c'est lui qui permet à un tabata de compter dans « groupes négligés » une
    #: fois déclaré fait. Le deviner depuis le nom anglais de Cadence serait une
    #: correspondance approximative de plus, du genre qui se trompe en silence.
    #:
    #: **L'énumération et non `str` + validateur**, contrairement à `ExercisePayload`. Un
    #: validateur ne laisse aucune trace dans le schéma JSON : le catalogue d'actions de
    #: l'assistant annonçait donc « texte » pour un champ qui n'accepte que neuf valeurs,
    #: et le modèle envoyait « pecs ». C'est exactement la faute que `plan.add` a payée sur
    #: son `kind`, et la leçon est écrite en tête de `actions.py` — la description que le
    #: modèle lit doit venir de la même source que la validation.
    muscle_group: MuscleGroup
    duration_s: CircuitDurationS | None = None
    reps: CircuitReps | None = None
    rest_s: CircuitRestS = 0
    #: Ce qu'on veut lire sous le nom pendant l'effort — « genoux au sol », « tempo lent ».
    #:
    #: **C7 est révisée par ce lot** : la note du lien n'est plus « fabriquée par le
    #: serveur, jamais saisie ». Elle reste fabriquée par le serveur — le client ne compose
    #: toujours aucune URL, l'invariant tient — mais elle peut désormais porter ce que
    #: l'application n'a aucun moyen de savoir. La charge s'y ajoute toute seule.
    note: CircuitNote = ""

    @model_validator(mode="after")
    def exactly_one_length(self) -> CircuitExercisePayload:
        if (self.duration_s is None) == (self.reps is None):
            raise ValueError("Un exercice est soit au temps, soit en répétitions.")
        return self


class CircuitPayload(BaseModel):
    """Un circuit à enregistrer ou à corriger.

    Pas de date : un circuit est un patron, il se rejoue. C'est le serveur qui note le
    jour où il a été créé, et cette date ne sert qu'à trier.
    """

    name: Label
    rounds: CircuitRounds = 1
    round_rest_s: CircuitRoundRestS = 0
    #: Au moins un : un circuit sans exercice n'ouvre que l'écran d'accueil de Cadence,
    #: ce qui n'est pas ce qu'on a demandé. Quarante au plus, comme les séances.
    exercises: list[CircuitExercisePayload] = Field(min_length=1, max_length=40)
    note: Note | None = None


class CircuitImportPayload(BaseModel):
    """Un lien Cadence collé, à relire en circuit.

    C'est le décodeur de `circuit_link` en sens inverse, et il ne coûte qu'une route :
    il est déjà écrit et éprouvé par l'aller-retour. Ce qu'il récupère, ce sont les
    séances construites dans Cadence avant que Metric sache en faire — sinon il faudrait
    les ressaisir une à une.
    """

    url: str = Field(min_length=1, max_length=2000)


class CircuitExercise(BaseModel):
    """Un exercice d'un circuit, tel que le client le reçoit.

    `duration_s` et `reps` s'excluent, comme à la saisie : c'est celui qui vaut `None` qui
    dit la nature de l'autre, et l'écran n'a aucune sentinelle à interpréter.
    """

    position: int
    name: str
    muscle_group: str
    duration_s: int | None = None
    reps: int | None = None
    rest_s: int
    #: La note **saisie** sur cet exercice, telle qu'elle se corrige. Vide, pas `null` :
    #: c'est un champ de formulaire qui fait l'aller-retour.
    note: str = ""
    #: Ce que le **lien** porte réellement en 4ᵉ champ — la charge et la note, composées
    #: (**C7**). `null` quand il n'y a ni l'une ni l'autre.
    #:
    #: Servi plutôt que recomposé par l'écran : il n'y a qu'un endroit au monde où « 12 »
    #: devient « 12 kg » et où les deux se joignent, et c'est celui qui fabrique le lien.
    #: Deux compositions divergeraient, et le symptôme serait une carte qui annonce autre
    #: chose que ce que Cadence affichera.
    link_note: str | None = None


class Circuit(BaseModel):
    """Un circuit, tel que le client le reçoit."""

    id: int
    token: str
    circuit_id: str
    name: str
    rounds: int
    round_rest_s: int
    #: Jour d'enregistrement. Il trie la liste ; il ne date aucune séance effectuée.
    created: date | None = None
    note: str | None = None
    exercises: list[CircuitExercise]
    #: L'adresse à ouvrir, ou `None` tant que `cadence_base_url` n'est pas réglée (**D1**).
    #: Jamais une adresse relative de repli : sans base il n'y a pas de lien, et c'est un
    #: état que l'écran sait dire.
    url: str | None = None
    #: Durée totale, calculée sur les valeurs **bornées** — celles que Cadence exécutera.
    estimated_duration_min: float
    #: Faux dès qu'un exercice est en répétitions. C'est ce booléen que l'écran traduit en
    #: `~` devant le total : la spécification interdit d'annoncer une durée exacte dans ce
    #: cas, et l'invariant « aucune valeur inventée » dit la même chose.
    exact: bool


class CircuitSuggestion(BaseModel):
    """Un nom d'exercice proposé à la saisie d'un circuit.

    **Les deux mondes se retrouvent ici, et seulement ici** : les 1324 noms du catalogue de
    Cadence et ceux que l'utilisateur a déclarés dans le sien. Rien n'est fusionné dans les
    fichiers ; c'est un résultat de recherche, calculé à la demande.

    ## `illustrated` a disparu, et ce n'est pas un oubli

    Le champ disait « ce nom exact affiche une illustration », et il avait un sens tant que
    35 noms sur tous les noms possibles en affichaient une. Avec 1324 démonstrations et un
    rapprochement qui tolère la casse, les pluriels et le français, le booléen ne distingue
    plus rien d'utile — et le calculer honnêtement demanderait de réimplémenter
    l'algorithme de Cadence, c'est-à-dire d'en tenir une seconde version qui divergerait.
    """

    name: str
    #: Le groupe musculaire, quand cet exercice est au catalogue de Metric. `null` sinon —
    #: un nom du catalogue de Cadence n'en porte aucun, et en deviner un serait inventer
    #: une valeur que les statistiques prendraient au sérieux.
    muscle_group: str | None = None
    #: Zone du corps et matériel, quand la suggestion vient du catalogue de Cadence. `null`
    #: pour un exercice de Metric, qui ne porte ni l'un ni l'autre — et les déduire de son
    #: groupe musculaire serait une correspondance de plus à tenir.
    body_part: str | None = None
    equipment: str | None = None


class CircuitList(BaseModel):
    """Les circuits enregistrés (`GET /activity/circuits`)."""

    circuits: list[Circuit]
    #: Vrai quand une adresse de base est réglée. **Non déductible de la liste** : sur une
    #: liste vide, l'écran doit distinguer « aucun circuit » de « aucune adresse », et ces
    #: deux états vides ne proposent pas le même geste suivant.
    linkable: bool


class CircuitDonePayload(BaseModel):
    """Ce qu'on confirme en déclarant un circuit fait (**D4**, **D6**).

    **La durée est exigée, pas devinée.** L'écran la pré-remplit avec l'estimation et
    laisse la corriger ; l'API, elle, ne la déduit pas d'un champ absent. Sur une séance
    en répétitions, personne ne connaît la durée réelle — l'écrire en silence dans
    `workouts.csv` mettrait une valeur inventée dans le volume hebdomadaire.

    Pas de date : elle vient du serveur. Cadence n'a aucun moyen de dire à Metric qu'une
    séance a eu lieu (**D6**), donc c'est un geste, et un geste se fait maintenant.
    """

    duration_min: DurationMin
    rpe: Rpe | None = None


class ComposeRequest(BaseModel):
    """Ce qu'on demande à l'écran de composition — une phrase (**R5**).

    Une seule zone de texte et aucun formulaire : ce qui manque au modèle, il l'a déjà.
    Le matériel possédé et les groupes négligés partent avec la demande sans qu'on ait à
    les taper (§5 bis), et c'est ce qui rend « fais-moi 30 minutes » répondable.
    """

    #: « bras 30 min, un haltère de 10 kg ». Vide est légitime : le profil suffit à
    #: composer quelque chose, et exiger une phrase pour rien serait un formulaire de plus.
    wish: str = Field(default="", max_length=500)


class ProposedCircuitExercise(BaseModel):
    """Un exercice **proposé**, tel que l'écran le reçoit — ajustable, jamais écrit."""

    name: str
    muscle_group: str
    duration_s: int | None = None
    reps: int | None = None
    rest_s: int = 0
    #: Vrai quand le nom est exactement celui d'un exercice du catalogue Cadence, donc
    #: quand une démonstration s'affichera pendant l'effort.
    #:
    #: Faux **n'est pas une erreur** : la spécification dit qu'un nom hors catalogue reste
    #: valide et que la séance tourne. C'est l'écran qui le dit, pour qu'on choisisse de
    #: corriger ou non — le taire promettrait une image qui n'arrivera pas.
    illustrated: bool = True


class CircuitProposal(BaseModel):
    """Ce que la composition rend. **Aucune ligne n'a été écrite** (**R5**).

    La symétrie avec `Proposal` du planning est voulue : cette forme ne connaît pas
    l'écriture, `POST /circuits` ne connaît pas l'IA, et entre les deux il y a un écran et
    un appui.
    """

    name: str
    rounds: int
    round_rest_s: int
    exercises: list[ProposedCircuitExercise]
    #: Ce sur quoi la proposition s'appuie, dit à l'écran : le matériel pris en compte, les
    #: groupes les plus anciens. Une suggestion dont on voit l'argument se discute ; une
    #: suggestion nue se croit ou se rejette.
    basis: list[str] = Field(default_factory=list)
    #: Exercices écartés à la relecture, et pourquoi. Les taire laisserait croire que le
    #: modèle n'a proposé que cela.
    dropped: list[str] = Field(default_factory=list)


# ── Charges des exercices de tabata (**C1**) ──────────

#: Le pas des boutons plus et moins de la page Charges (**C6**). Un kilo : le réglage réel
#: d'un tabata se fait au kilo, pas au disque. Il vit ici et non dans l'écran parce que la
#: page **et** l'assistant doivent parler du même pas le jour où il change.
LOAD_STEP_KG = 1.0

#: État d'une charge, décidé par le **serveur**. L'écran groupe sur cette étiquette ; lui
#: faire déduire « non renseigné » d'un `null` reviendrait à lui confier la règle, et il y
#: a exactement trois états à ne pas confondre — voir `CircuitLoadRow`.
LoadState = Literal["unset", "bodyweight", "weighted"]

#: La charge saisie, en kilogrammes. **`gt=0` et non `ge=0`**, contrairement à `LoadKg` du
#: journal de musculation où zéro *signifie* le poids du corps (`ACT-07`). Ici le poids du
#: corps a son propre drapeau : accepter zéro donnerait deux façons de dire la même chose,
#: et l'écran ne saurait plus laquelle afficher.
CircuitLoadKg = Annotated[float, Field(gt=0, le=1000, description="Charge en kilogrammes")]


class LoadPayload(BaseModel):
    """Ce qu'on déclare sur un exercice : une charge, ou le poids du corps.

    **Exactement un des deux**, comme `CircuitExercisePayload` pour temps et répétitions.
    Les deux à la fois seraient « poids du corps à 12 kg » ; aucun des deux laisserait le
    service décider à la place de l'utilisateur, ce que **C3** lui interdit.
    """

    name: Label
    weight_kg: CircuitLoadKg | None = None
    bodyweight: bool = False

    @model_validator(mode="after")
    def exactly_one_declaration(self) -> LoadPayload:
        if (self.weight_kg is None) == (not self.bodyweight):
            raise ValueError("Un exercice est soit au poids du corps, soit à une charge.")
        return self


class Load(BaseModel):
    """La charge d'un exercice, telle que la page la reçoit."""

    #: `null` tant qu'aucune charge n'a été déclarée : il n'y a alors **aucune ligne**, donc
    #: aucune position ni jeton. C'est ce couple à `null` qui dit à l'écran de créer plutôt
    #: que de corriger — la première charge est une addition, la suivante une modification.
    id: int | None = None
    token: str | None = None
    name: str
    state: LoadState
    weight_kg: float | None = None
    #: Jour de la dernière décision. Il ne date aucune séance (**C4**).
    updated: date | None = None
    #: Nombre de circuits qui emploient cet exercice. C'est la réponse à la seule question
    #: que pose une carte — « pourquoi celui-là est ici ? » — et elle coûte une lecture
    #: déjà faite.
    circuits: int
    #: Jours depuis le **dernier changement de charge**, lu dans `circuit_load_log.csv`.
    #:
    #: `null` quand le journal ne porte rien pour cet exercice — jamais `0`, qui voudrait
    #: dire « changée aujourd'hui ». Le journal est la seule autorité ici : `updated`
    #: bouge à chaque enregistrement, y compris celui qui ne change rien, alors que le
    #: journal ne retient que les changements confirmés (**C2**).
    days_since_change: int | None = None
    #: Séances **tenues à cette charge** depuis ce changement.
    #:
    #: `0` est une mesure et non une absence : « montée il y a trois jours, aucune séance
    #: depuis » est précisément ce qu'un coach doit lire. C'est `null` qui dit « aucun
    #: changement au journal », donc rien à compter depuis.
    sessions_since: int | None = None


class LoadList(BaseModel):
    """Les exercices de tabata et leur charge (`GET /activity/loads`).

    La liste vient de `circuit_exercises.csv` et **d'elle seule**, dédoublonnée par `fold` :
    la page ne montre que ce qui est constitutif d'une séance tabata. Un exercice de
    musculation n'y entre pas — sa charge est déjà journalisée série par série.
    """

    loads: list[Load]
    #: Le pas des boutons plus et moins. Servi plutôt que codé dans l'écran, pour la raison
    #: habituelle : deux valeurs pour un même réglage divergeraient sans que rien ne le dise.
    step_kg: float = LOAD_STEP_KG


class LoadPoint(BaseModel):
    """Un changement de charge, tel que la courbe le reçoit (**C2**)."""

    date: date
    #: `null` quand ce point est un passage au poids du corps. La courbe s'y **interrompt**
    #: plutôt que de retomber à zéro : zéro serait une charge nulle, l'absence est autre
    #: chose.
    weight_kg: float | None = None


class LoadDay(BaseModel):
    """Un jour de la ligne de 30 points."""

    date: date
    #: Nombre de séances de ce jour qui portaient cet exercice. **Zéro est une mesure ici**
    #: et non une valeur inventée : on a compté, il n'y en a pas eu.
    count: int


class LoadDetail(BaseModel):
    """Ce que la feuille de détail affiche (`GET /activity/loads/detail`).

    Les deux séries viennent de **deux fichiers différents**, et c'est la conséquence
    directe de **C2** et **C4** : la courbe est le journal des décisions
    (`circuit_load_log.csv`), les points sont les séances déclarées faites
    (`exercise_log.csv`). Elles peuvent diverger — une charge notée et jamais soulevée
    monte la courbe sans allumer un point — et c'est exactement ce qu'on veut voir.
    """

    name: str
    state: LoadState
    weight_kg: float | None = None
    history: list[LoadPoint]
    #: **Exactement 30 entrées**, du plus ancien au jour du serveur. La fenêtre est calculée
    #: ici : l'écran ne connaît ni sa longueur ni la date d'aujourd'hui (`CLAUDE.md` §2).
    sessions: list[LoadDay]
    #: Les circuits qui emploient cet exercice, par leur nom.
    circuits: list[str]
