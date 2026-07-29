"""Moteur d'assiduité : machine à états, cadences, statistiques (`HEAT-04` → `HEAT-28`).

Le cœur du projet, et **le seul module entièrement pur** : il ne lit aucun fichier, ne
connaît ni Nextcloud ni HTTP. On lui donne une configuration de piste, un agrégat
quotidien, des plages neutralisées et une plage de dates ; il rend une grille et des
statistiques. C'est ce qui permet d'écrire un test par exemple de la spec, sans monter
une application.

## Le principe dont tout découle

> Une heatmap ne mesure pas l'activité, elle mesure le **respect d'un engagement**. Un
> jour vide n'est un échec que si quelque chose était attendu ce jour-là.

D'où quatre états et non cinq niveaux (`HEAT-05`) : `off` — rien n'était attendu ;
`missed` — attendu, non validé ; `done` — validé ; `bonus` — validé alors que rien
n'était attendu. Une grille majoritairement `off` n'est pas un échec, et c'est ce qui
rend lisible une piste non quotidienne.

## Trois lectures que la spec laisse ouvertes

Elles sont tranchées ici, et chacune a son test.

**Un jour neutralisé compte comme satisfait dans une fenêtre glissante.** `HEAT-06` dit
qu'une grippe ne casse pas une série ; sans cette règle, elle ne la casserait pas
pendant, mais produirait un `missed` le lendemain — la fenêtre qui s'y referme ne
contenant aucune validation. Punir le premier jour de convalescence serait le contraire
de l'intention.

**Une série se compte en jours de calendrier, pas en validations.** `HEAT-27` illustre
la règle par « une whey prise un jour sur deux pendant trois mois donne une série de
trois mois, pas de deux jours ». Compter les validations donnerait quarante-cinq, qui
n'est ni l'un ni l'autre. La série est donc l'étendue de la plus longue période sans
`missed` bornée par des jours validés.

**Un `bonus` prolonge la série.** Une piste « un jour sur deux » tenue *tous* les jours
produit un `done` puis des `bonus` : ne compter que les `done` donnerait une série de un
pour une adhérence parfaite. Faire plus que demandé ne peut pas faire moins bien.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from app.core.cadence import Cadence, CadenceType
from app.core.dates import days_between, week_start

#: Nombre de niveaux d'intensité au-dessus de zéro (`HEAT-15`).
MAX_LEVEL = 4

#: Profondeur de la plage par défaut (`HEAT-31`, décision **D6**).
DEFAULT_WEEKS = 53


class DayState(StrEnum):
    """Les quatre états d'un jour (`HEAT-05`)."""

    OFF = "off"
    MISSED = "missed"
    DONE = "done"
    BONUS = "bonus"


class WeekStatus(StrEnum):
    """Statut d'une semaine pour une piste `per_week` (`HEAT-28`).

    La spec en nomme trois. `OFF` est ajouté par nécessité : une semaine antérieure à la
    création de la piste, ou entièrement neutralisée, n'est pas « manquée » — et `HEAT-07`
    interdit de la présenter comme telle.
    """

    REACHED = "reached"
    PARTIAL = "partial"
    MISSED = "missed"
    OFF = "off"


class DayReason(StrEnum):
    """Pourquoi un jour est `off`, quand ce n'est pas la cadence qui l'a décidé.

    **Ce n'est pas un cinquième état** : les quatre de `HEAT-05` restent les seuls sur
    lesquels se décide une couleur, une série ou un taux. C'est une nuance d'affichage,
    et elle existe parce que quatre situations très différentes se ressemblent trait pour
    trait sans elle : une semaine de grippe, les six mois qui précèdent la création de la
    piste, les jours de la semaine en cours qui ne sont pas arrivés, et la journée
    d'aujourd'hui qui n'est pas finie.

    Les peindre toutes comme un `off` de cadence serait correct au sens du moteur, et
    illisible à l'écran : une piste créée hier montrerait un an de cellules identiques
    sans dire que rien n'y était encore suivi.

    Le calcul reste **ici**, avec le reste des règles, et non dans un routeur ou dans le
    client — un « ce jour est-il neutralisé » écrit ailleurs échapperait à cette batterie
    de tests.
    """

    #: `HEAT-06` — maladie, voyage, deload.
    NEUTRALISED = "neutralised"
    #: `HEAT-07` — antérieur à la création de la piste.
    BEFORE_TRACK = "before_track"
    #: Au-delà d'aujourd'hui : la plage par défaut va jusqu'au dimanche.
    FUTURE = "future"
    #: `HEAT-08` — la journée en cours, pas encore validée et pas encore finie.
    PENDING = "pending"


class Expectation(StrEnum):
    """Ce que la cadence attend d'un jour donné.

    Trois valeurs et non deux : une cadence hebdomadaire ou descriptive ne se prononce
    **pas** au jour. `HEAT-11` l'exige explicitement — sur une piste `per_week`, les jours
    restent `done` ou `off`, jamais `missed` individuellement, et c'est la semaine qui
    porte le verdict.
    """

    #: Attendu : non validé, le jour est `missed`.
    REQUIRED = "required"
    #: Non attendu : validé, le jour est `bonus`.
    OPTIONAL = "optional"
    #: Aucun verdict au jour : validé, le jour est `done` ; sinon `off`.
    DESCRIPTIVE = "descriptive"


@dataclass(frozen=True, slots=True)
class Range:
    """Plage évaluée, bornes comprises."""

    start: date
    end: date

    def days(self) -> list[date]:
        return days_between(self.start, self.end)


def default_range(today: date) -> Range:
    """53 semaines pleines alignées sur le lundi (`HEAT-31`, décision **D6**).

    Le backlog demande « 371 jours se terminant aujourd'hui, alignés sur des semaines
    commençant le lundi ». Les deux conditions ne peuvent être vraies ensemble sauf si
    aujourd'hui est un dimanche. L'alignement de grille prime : une colonne tronquée se
    voit à l'œil, un décalage d'un jour ne se voit pas et fausse la lecture.

    La plage se termine donc au **dimanche de la semaine courante**, et les jours encore
    à venir sont rendus `off` — ils ne sont pas manqués, ils ne sont pas arrivés.
    """
    end = week_start(today) + timedelta(days=6)
    return Range(start=week_start(today) - timedelta(weeks=DEFAULT_WEEKS - 1), end=end)


@dataclass(frozen=True, slots=True)
class TrackRules:
    """Ce qu'il faut savoir d'une piste pour juger ses jours.

    Volontairement détaché du modèle CSV : le moteur se teste avec un objet de trois
    lignes, sans fichier ni dépôt.
    """

    #: Seuil de validation (`HEAT-04`). Toujours un paramètre, jamais une constante.
    validation_threshold: float
    #: Quatre bornes croissantes (`HEAT-15`). Vides en mode binaire.
    levels: Sequence[float] = ()
    #: Un seul niveau : une prise est une prise (`HEAT-16`).
    binary: bool = False
    #: Date d'entrée de la piste. Aucun état n'est produit avant (`HEAT-07`).
    created: date | None = None


@dataclass(frozen=True, slots=True)
class OffRange:
    """Plage neutralisée (`HEAT-06`)."""

    start: date
    end: date

    def covers(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True, slots=True)
class Day:
    """Un jour de la grille (`HEAT-24`)."""

    date: date
    value: float
    state: DayState
    level: int
    #: Nuance d'affichage d'un `off`. `None` quand c'est la cadence qui n'attendait rien,
    #: et sur tout jour qui n'est pas `off`.
    reason: DayReason | None = None


@dataclass(frozen=True, slots=True)
class Week:
    """Une semaine ISO d'une piste `per_week` (`HEAT-28`)."""

    week_start: date
    status: WeekStatus
    done: int
    expected: int


@dataclass(frozen=True, slots=True)
class Stats:
    """Les chiffres qui accompagnent une grille (`HEAT-26`)."""

    validated_days: int
    #: Attentes de la plage. Sur une piste hebdomadaire ce sont des **créneaux** et non
    #: des jours — « torse 2×/semaine » sur quatre semaines en attend huit, pas
    #: vingt-huit. Le nom vient du contrat de la spec (§8) et lui reste fidèle.
    expected_days: int
    #: `None` quand rien n'était attendu : un taux de respect sans attente n'existe pas,
    #: et zéro se lirait comme un échec.
    compliance: float | None
    longest_streak: int
    current_streak: int
    #: Jour de plus forte valeur. `None` en binaire — une prise ne bat pas une prise.
    best_day: date | None
    best_value: float | None
    #: Cumul brut sur la plage : kilomètres, litres, séries.
    total: float


@dataclass(frozen=True, slots=True)
class Grid:
    """Grille complète d'une piste."""

    range: Range
    days: list[Day]
    #: Renseigné pour les seules pistes `per_week`, `None` sinon.
    weeks: list[Week] | None
    stats: Stats
    #: Cadence en vigueur au dernier jour évalué, pour l'afficher sans la recalculer.
    cadence: Cadence


# ── Intensité (`HEAT-15` → `HEAT-17`) ─────────────────


def intensity(value: float, rules: TrackRules) -> int:
    """Niveau 1–4 d'une valeur, indépendamment de sa validation (`HEAT-17`).

    Validation et intensité sont **découplées** : le seuil décide vert ou rouge, les
    bornes décident l'intensité du vert. Un jour à 1,6 L d'eau est validé — le seuil est
    à 1,5 L — mais reste pâle, parce que l'objectif est à 2 L.

    En binaire, ou sans bornes renseignées, le seul niveau est 1 : une prise est une
    prise (`HEAT-16`).
    """
    if rules.binary or not rules.levels:
        return 1 if value > 0 else 0
    return min(MAX_LEVEL, sum(1 for bound in rules.levels if value >= bound))


# ── Cadences (`HEAT-09` → `HEAT-13`) ──────────────────


def _expectation(
    cadence: Cadence,
    day: date,
    *,
    validated: set[date],
    excused: set[date],
    triggers: set[date],
) -> Expectation:
    """Ce que la cadence attend de ce jour.

    `excused` regroupe les jours qu'on ne peut retenir contre l'utilisateur : neutralisés,
    antérieurs à la piste, à venir. Ils comptent comme satisfaits dans une fenêtre
    glissante — sans quoi une grippe produirait un `missed` le lendemain de la guérison.
    """
    match cadence.type:
        case CadenceType.DAILY:
            return Expectation.REQUIRED

        case CadenceType.WINDOW:
            # `HEAT-10`. La fenêtre est **glissante** et non une parité de calendrier :
            # lundi/mercredi/vendredi et mardi/jeudi/samedi sont deux rythmes également
            # corrects, et une règle « jours pairs » en punirait un arbitrairement.
            span = int(cadence.params["window_days"])
            needed = int(cadence.params["min_count"])
            window = days_between(day - timedelta(days=span - 1), day)
            # Le jour lui-même est exclu du décompte : la question posée est « ce jour
            # était-il nécessaire ? », pas « la fenêtre est-elle satisfaite ? ».
            satisfied = sum(
                1 for other in window if other != day and (other in validated or other in excused)
            )
            return Expectation.REQUIRED if satisfied < needed else Expectation.OPTIONAL

        case CadenceType.CONDITIONAL:
            # `HEAT-12`. La cadence correcte pour un supplément péri-entraînement : il
            # n'est pas manqué les jours de repos, il n'était pas attendu.
            return Expectation.REQUIRED if day in triggers else Expectation.OPTIONAL

        case CadenceType.PER_WEEK | CadenceType.NONE:
            # `HEAT-11`, `HEAT-13`. Aucun verdict au jour : c'est la semaine qui décide,
            # ou personne.
            return Expectation.DESCRIPTIVE


# ── Machine à états (`HEAT-05` → `HEAT-08`) ───────────


def evaluate(
    *,
    rules: TrackRules,
    cadence_at: Cadence | dict[date, Cadence],
    values: dict[date, float],
    window: Range,
    today: date,
    off_ranges: Iterable[OffRange] = (),
    triggers: Iterable[date] = (),
) -> Grid:
    """Juge chaque jour de la plage et rend la grille complète.

    `cadence_at` accepte une cadence unique ou une cadence par jour — c'est ainsi que la
    version datée de `HEAT-14` entre dans le moteur sans qu'il ait à connaître le journal
    qui la produit.

    **Ordre de priorité des règles neutralisantes**, et il n'est pas interchangeable :

    1. jour **neutralisé** (`HEAT-06`) — une grippe l'emporte sur tout le reste ;
    2. jour **antérieur à la création** de la piste (`HEAT-07`) — ajouter la créatine
       aujourd'hui ne rend pas rouges les six mois précédents ;
    3. jour **en cours ou à venir** (`HEAT-08`) — on ne manque pas une journée qui n'est
       pas finie ;
    4. **cadence** — et seulement alors.

    Inverser 2 et 4 rendrait rouge tout l'historique d'une piste créée ce matin ; inverser
    3 et 4 la rendrait rouge chaque matin au réveil.
    """
    ranges = list(off_ranges)
    trigger_days = set(triggers)
    all_days = window.days()

    def cadence_for(day: date) -> Cadence:
        return cadence_at if isinstance(cadence_at, Cadence) else cadence_at[day]

    def neutralised(day: date) -> bool:
        return any(item.covers(day) for item in ranges)

    def before_track(day: date) -> bool:
        return rules.created is not None and day < rules.created

    def excuse(day: date) -> DayReason | None:
        """Raison de ne pas juger ce jour, dans l'ordre de priorité documenté ci-dessus.

        Un seul endroit décide, et les deux passages le consultent : sans cela, la liste
        des jours excusés et celle des cellules peintes pourraient diverger sur un cas
        limite — un jour neutralisé *et* futur, par exemple.
        """
        if neutralised(day):
            return DayReason.NEUTRALISED
        if before_track(day):
            return DayReason.BEFORE_TRACK
        if day > today:
            return DayReason.FUTURE
        return None

    # Premier passage : ce qui ne dépend d'aucun autre jour. Les fenêtres glissantes ont
    # besoin de connaître les validations de leurs voisins, y compris hors plage — d'où
    # une marge en amont.
    margin = _window_margin(cadence_at)
    scope = days_between(window.start - timedelta(days=margin), window.end)

    validated: set[date] = set()
    excused: set[date] = set()
    for day in scope:
        if excuse(day) is not None:
            excused.add(day)
        elif values.get(day, 0.0) >= rules.validation_threshold:
            validated.add(day)

    # Second passage : l'état de chaque jour de la plage demandée.
    days: list[Day] = []
    for day in all_days:
        value = values.get(day, 0.0)

        reason = excuse(day)
        if reason is not None:
            days.append(Day(date=day, value=value, state=DayState.OFF, level=0, reason=reason))
            continue

        is_validated = day in validated
        if day == today and not is_validated:
            # `HEAT-08` : la journée en cours n'est jamais manquée tant qu'elle n'est pas
            # terminée. Elle reste `off`, et basculera le soir venu si rien n'arrive.
            days.append(
                Day(
                    date=day,
                    value=value,
                    state=DayState.OFF,
                    level=0,
                    reason=DayReason.PENDING,
                )
            )
            continue

        expectation = _expectation(
            cadence_for(day),
            day,
            validated=validated,
            excused=excused,
            triggers=trigger_days,
        )

        if is_validated:
            state = DayState.BONUS if expectation is Expectation.OPTIONAL else DayState.DONE
            # Le niveau ne colore que ce qui a réussi : un `missed` gradué se lirait comme
            # une demi-réussite, et une grille doit se lire sans notice.
            days.append(Day(date=day, value=value, state=state, level=intensity(value, rules)))
        elif expectation is Expectation.REQUIRED:
            days.append(Day(date=day, value=value, state=DayState.MISSED, level=0))
        else:
            days.append(Day(date=day, value=value, state=DayState.OFF, level=0))

    # Deux périmètres distincts, et les confondre fausserait les chiffres.
    #
    # `covered` — ce dont la piste a quelque chose à dire : depuis sa création, jusqu'à
    # aujourd'hui. Les jours neutralisés en font partie : boire deux litres pendant une
    # grippe reste une mesure, et le cumul doit la porter.
    #
    # `judgeable` — ce qu'on peut compter comme réussite ou comme échec. Les jours
    # neutralisés en sont exclus : ils « ne comptent ni comme réussite ni comme échec »
    # (`HEAT-06`).
    covered = {day for day in all_days if day <= today and not before_track(day)}
    judgeable = {day for day in covered if not neutralised(day)}

    cadence = cadence_for(min(window.end, today) if window.start <= today else window.start)
    weeks = (
        _weeks(days, cadence, today, judgeable) if cadence.type is CadenceType.PER_WEEK else None
    )

    return Grid(
        range=window,
        days=days,
        weeks=weeks,
        stats=_stats(days, weeks, cadence, rules, today, covered),
        cadence=cadence,
    )


def _window_margin(cadence_at: Cadence | dict[date, Cadence]) -> int:
    """Jours à charger en amont de la plage pour que les fenêtres glissantes soient
    justes à la première colonne."""
    cadences = [cadence_at] if isinstance(cadence_at, Cadence) else list(cadence_at.values())
    spans = [
        int(cadence.params["window_days"])
        for cadence in cadences
        if cadence.type is CadenceType.WINDOW
    ]
    return max(spans, default=1)


# ── Statuts hebdomadaires (`HEAT-11`, `HEAT-28`) ──────


def _weeks(days: list[Day], cadence: Cadence, today: date, judgeable: set[date]) -> list[Week]:
    """Statut de chaque semaine ISO couverte par la grille.

    Une semaine **non terminée** n'est jamais `missed`, pour la même raison qu'un jour en
    cours ne l'est pas : elle n'a pas encore eu lieu en entier.

    Le statut ne peut pas se déduire des seuls états des jours : sur une piste `per_week`,
    un jour non validé est `off` (`HEAT-11`), si bien qu'une semaine sans rien et une
    semaine antérieure à la piste se ressemblent trait pour trait. D'où `judgeable`, qui
    dit lesquels de ces jours la piste avait le droit de juger.
    """
    expected = int(cadence.params["count"])
    buckets: dict[date, list[Day]] = {}
    for day in days:
        buckets.setdefault(week_start(day.date), []).append(day)

    weeks: list[Week] = []
    for start, bucket in sorted(buckets.items()):
        done = sum(1 for day in bucket if day.state in (DayState.DONE, DayState.BONUS))
        eligible = any(day.date in judgeable for day in bucket)
        running = start + timedelta(days=6) >= today

        if not eligible:
            # Semaine antérieure à la piste, entièrement neutralisée, ou encore à venir :
            # elle n'a rien à dire, et la présenter comme manquée serait un mensonge.
            status = WeekStatus.OFF
        elif done >= expected:
            status = WeekStatus.REACHED
        elif done > 0 or running:
            status = WeekStatus.PARTIAL
        else:
            status = WeekStatus.MISSED

        weeks.append(Week(week_start=start, status=status, done=done, expected=expected))
    return weeks


# ── Statistiques (`HEAT-26`, `HEAT-27`) ───────────────


def _stats(
    days: list[Day],
    weeks: list[Week] | None,
    cadence: Cadence,
    rules: TrackRules,
    today: date,
    covered: set[date],
) -> Stats:
    judged = [day for day in days if day.date <= today]

    done = sum(1 for day in judged if day.state is DayState.DONE)
    bonus = sum(1 for day in judged if day.state is DayState.BONUS)
    missed = sum(1 for day in judged if day.state is DayState.MISSED)

    achieved = done
    if weeks is not None:
        # Sur une piste hebdomadaire, l'attente se compte en créneaux de semaine et non
        # en jours : « torse 2×/semaine » attend deux séances, pas sept.
        #
        # La semaine en cours est écartée des deux côtés du rapport, pour la même raison
        # qu'un jour en cours n'est pas manqué : elle n'a pas encore eu lieu en entier, et
        # compter ses créneaux comme dus ferait chuter le taux tous les lundis matin.
        finished = [
            week
            for week in weeks
            if week.status is not WeekStatus.OFF and week.week_start + timedelta(days=6) < today
        ]
        expected = sum(week.expected for week in finished)
        achieved = sum(min(week.done, week.expected) for week in finished)
    elif cadence.type is CadenceType.NONE:
        expected = 0  # piste descriptive : rien n'est attendu, rien n'est manqué
    else:
        expected = done + missed

    # Les mesures ne portent que sur ce que la piste couvre : le meilleur jour et le
    # cumul d'une piste créée hier ne peuvent pas venir de l'an dernier.
    measured = [day for day in judged if day.date in covered and day.value > 0]
    best = max(measured, key=lambda day: day.value, default=None)

    return Stats(
        validated_days=done + bonus,
        expected_days=expected,
        # Un `bonus` ne gonfle pas le taux : on ne respecte pas un engagement à 120 %.
        compliance=min(1.0, achieved / expected) if expected else None,
        longest_streak=_longest_streak(days, today),
        current_streak=_current_streak(days, today),
        best_day=None if rules.binary or best is None else best.date,
        best_value=None if rules.binary or best is None else best.value,
        total=round(sum(day.value for day in judged if day.date in covered), 3),
    )


def _runs(days: list[Day], today: date) -> list[tuple[date, date]]:
    """Périodes sans `missed`, bornées par un jour validé de part et d'autre.

    Une série se mesure en **jours de calendrier** et non en validations (`HEAT-27`) :
    une whey prise un jour sur deux pendant trois mois donne trois mois, pas quarante-cinq.
    Les jours `off` et neutralisés sont transparents — ils n'ouvrent ni ne ferment une
    période, ils la traversent.
    """
    runs: list[tuple[date, date]] = []
    first: date | None = None
    last: date | None = None

    for day in days:
        if day.date > today:
            break
        if day.state is DayState.MISSED:
            if first is not None and last is not None:
                runs.append((first, last))
            first = last = None
        elif day.state in (DayState.DONE, DayState.BONUS):
            if first is None:
                first = day.date
            last = day.date

    if first is not None and last is not None:
        runs.append((first, last))
    return runs


def _longest_streak(days: list[Day], today: date) -> int:
    return max(((end - start).days + 1 for start, end in _runs(days, today)), default=0)


def _current_streak(days: list[Day], today: date) -> int:
    """Série en cours : la dernière période, si rien ne l'a cassée depuis.

    Les `off` qui suivent le dernier jour validé ne la prolongent pas — on ne compte pas
    une avance qu'on n'a pas encore prise — mais ils ne la cassent pas non plus.
    """
    runs = _runs(days, today)
    if not runs:
        return 0

    start, end = runs[-1]
    after = [day for day in days if end < day.date <= today]
    if any(day.state is DayState.MISSED for day in after):
        return 0
    return (end - start).days + 1
