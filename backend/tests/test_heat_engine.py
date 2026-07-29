"""Moteur d'assiduité : machine à états, cadences, statistiques (`HEAT-04` → `HEAT-28`).

**La batterie de règles du lot L10.** Chaque exemple cité en clair dans `heat_backlog.md`
y est un test, et chaque décision que la spec laissait ouverte y est fixée noir sur blanc.

Le moteur étant pur, ces tests ne montent ni application ni stockage : une configuration
de trois lignes, un dictionnaire de valeurs, une plage. C'est ce qui permet d'en écrire
cent sans qu'ils coûtent une seconde — et de les lire comme on lit la spec.

Convention des tests : `J0` est « aujourd'hui », `J(-3)` avant-hier-avant-hier. Les
grilles sont lues comme des chaînes d'initiales — `..DoD` — où `.` est `off`, `D` est
`done`, `M` est `missed`, `B` est `bonus`.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.cadence import Cadence
from app.domains.heatmap.engine import (
    DayReason,
    DayState,
    Grid,
    OffRange,
    Range,
    TrackRules,
    WeekStatus,
    default_range,
    evaluate,
    intensity,
)

#: Un lundi, pour que les semaines ISO des tests soient lisibles sans calcul mental.
TODAY = date(2026, 7, 27)

STATE_LETTERS = {
    DayState.OFF: ".",
    DayState.DONE: "D",
    DayState.MISSED: "M",
    DayState.BONUS: "B",
}


def J(offset: int) -> date:  # noqa: N802 - lisibilité des tableaux de dates
    """Jour relatif à `TODAY`. `J(-1)` = hier."""
    return TODAY + timedelta(days=offset)


def span(first: int, last: int = 0) -> Range:
    return Range(start=J(first), end=J(last))


def shape(grid: Grid) -> str:
    """Grille lue comme une chaîne d'initiales, la plus ancienne à gauche."""
    return "".join(STATE_LETTERS[day.state] for day in grid.days)


def run(
    values: dict[date, float],
    cadence: str = "daily",
    *,
    window: Range | None = None,
    threshold: float = 1,
    levels: tuple[float, ...] = (),
    binary: bool = False,
    created: date | None = None,
    off_ranges: tuple[OffRange, ...] = (),
    triggers: tuple[date, ...] = (),
    today: date = TODAY,
) -> Grid:
    return evaluate(
        rules=TrackRules(
            validation_threshold=threshold, levels=levels, binary=binary, created=created
        ),
        cadence_at=Cadence.parse(cadence),
        values=values,
        window=window or span(-6),
        today=today,
        off_ranges=off_ranges,
        triggers=triggers,
    )


def taken(*offsets: int, value: float = 1) -> dict[date, float]:
    return {J(offset): value for offset in offsets}


# ── Validation (`HEAT-04`) ────────────────────────────


def test_a_day_is_validated_when_the_aggregate_reaches_the_threshold() -> None:
    """La règle tient en un signe : `agrégat ≥ seuil`. Le seuil est un paramètre de la
    piste, jamais une constante."""
    grid = run({J(-2): 1499, J(-1): 1500, J(0): 1501}, threshold=1500, window=span(-2))

    assert shape(grid) == "MDD"


def test_the_threshold_is_inclusive() -> None:
    """Atteindre l'objectif, c'est l'atteindre. Un `>` strict punirait le jour exact."""
    assert run({J(0): 1.0}, threshold=1.0, window=span(0)).days[0].state is DayState.DONE


def test_a_day_without_data_is_not_validated() -> None:
    grid = run({}, window=span(-2))

    assert shape(grid) == "MM."  # aujourd'hui n'est pas manqué : il n'est pas fini


# ── Priorité des règles neutralisantes (`L10-03`) ─────


def test_a_neutralised_day_is_off_whatever_the_cadence() -> None:
    """`HEAT-06`. Maladie, voyage, deload : ces jours ne comptent ni comme réussite ni
    comme échec."""
    grid = run({}, off_ranges=(OffRange(J(-5), J(-3)),), window=span(-6))

    assert shape(grid) == "M...MM."


def test_a_flu_does_not_break_a_ninety_day_streak() -> None:
    """L'exemple de la spec, mot pour mot.

    Cinq jours de grippe au milieu de quatre-vingt-dix jours d'eau : la série doit
    traverser la grippe, pas repartir de zéro.
    """
    values = taken(*range(-89, 1), value=2000)
    for offset in range(-50, -45):
        del values[J(offset)]

    grid = run(
        values,
        threshold=1500,
        window=span(-89),
        off_ranges=(OffRange(J(-50), J(-46)),),
    )

    assert grid.stats.current_streak == 90
    assert grid.stats.longest_streak == 90
    assert DayState.MISSED not in {day.state for day in grid.days}


def test_a_track_produces_no_state_before_its_creation() -> None:
    """`HEAT-07`. Ajouter la créatine aujourd'hui ne rend pas rouges les six mois
    précédents."""
    grid = run({}, created=J(-2), window=span(-6))

    assert shape(grid) == "....MM."


def test_creation_wins_over_the_cadence_but_loses_to_neutralisation() -> None:
    """L'ordre du lot : neutralisé > antérieur à la création > jour en cours > cadence.

    Inverser deux et quatre rendrait rouge tout l'historique d'une piste créée ce matin ;
    inverser trois et quatre la rendrait rouge chaque matin au réveil.
    """
    grid = run({}, created=J(-4), off_ranges=(OffRange(J(-3), J(-3)),), window=span(-6))

    assert shape(grid) == "..M.MM."
    assert grid.days[1].state is DayState.OFF, "antérieur à la piste"
    assert grid.days[2].state is DayState.MISSED, "jour de création, la cadence s'applique"
    assert grid.days[3].state is DayState.OFF, "neutralisé, bien qu'après la création"
    assert grid.days[6].state is DayState.OFF, "aujourd'hui n'est jamais manqué"


def test_today_is_never_missed_while_it_is_not_over() -> None:
    """`HEAT-08`. Sans cette règle, une grille passerait au rouge chaque matin pour
    reverdir le soir."""
    assert run({}, window=span(0)).days[0].state is DayState.OFF


def test_today_becomes_done_as_soon_as_it_is_validated() -> None:
    assert run(taken(0), window=span(0)).days[0].state is DayState.DONE


def test_future_days_are_off_not_missed() -> None:
    """`L10-17` : la plage par défaut va jusqu'au dimanche de la semaine courante. Les
    jours qui restent ne sont pas manqués, ils ne sont pas arrivés."""
    grid = run({}, window=Range(start=J(0), end=J(6)))

    assert shape(grid) == "......."


# ── Cadence `daily` (`HEAT-09`) ───────────────────────


def test_daily_expects_every_day() -> None:
    grid = run(taken(-6, -4, -2), window=span(-6))

    assert shape(grid) == "DMDMDM."


def test_daily_never_produces_a_bonus() -> None:
    """Tout est attendu : il n'y a rien à faire en plus."""
    grid = run(taken(*range(-6, 1)), window=span(-6))

    assert set(shape(grid)) == {"D"}


# ── Cadence `window` (`HEAT-10`) ──────────────────────

WINDOW = "window:min_count=1;window_days=2"


def test_a_sliding_window_accepts_two_equally_correct_rhythms() -> None:
    """**Le test qui justifie la fenêtre glissante.**

    Lundi/mercredi/vendredi et mardi/jeudi/samedi sont deux rythmes également corrects.
    Une règle « jours pairs » en punirait un arbitrairement, et c'est précisément ce que
    la spec refuse.
    """
    odd = run(taken(-7, -5, -3, -1), cadence=WINDOW, window=span(-6))
    even = run(taken(-6, -4, -2, 0), cadence=WINDOW, window=span(-6))

    assert DayState.MISSED not in {day.state for day in odd.days}
    assert DayState.MISSED not in {day.state for day in even.days}


def test_a_day_is_missed_when_the_window_closing_on_it_is_empty() -> None:
    """« Un jour est `missed` uniquement si la fenêtre qui s'y referme contient moins de
    `min_count` validations. »"""
    grid = run(taken(-6), cadence=WINDOW, window=span(-6))

    assert shape(grid) == "D.MMMM."


def test_a_second_day_in_a_row_is_a_bonus_not_a_duty() -> None:
    """Rien n'était attendu de ce jour : la fenêtre était déjà satisfaite."""
    grid = run(taken(-6, -5), cadence=WINDOW, window=span(-6))

    assert shape(grid) == "DB.MMM."


def test_whey_every_other_day_for_three_months_is_a_three_month_streak() -> None:
    """**L'exemple central de `HEAT-27`.**

    « Une whey prise un jour sur deux pendant trois mois donne une série de trois mois,
    pas de deux jours. » Compter les validations donnerait quarante-cinq, qui n'est ni
    l'un ni l'autre : la série se mesure en jours de calendrier.
    """
    grid = run(taken(*range(-89, 1, 2)), cadence=WINDOW, window=span(-89))

    # De J-89 à J-1, sans interruption : la lecture naïve — jours de calendrier
    # consécutifs validés — en aurait annoncé un seul.
    assert grid.stats.current_streak == 89
    assert DayState.MISSED not in {day.state for day in grid.days}


def test_a_perfect_run_beats_the_minimum_rather_than_losing_to_it() -> None:
    """Une piste « un jour sur deux » tenue *tous* les jours produit un `done` puis des
    `bonus`. Ne compter que les `done` donnerait une série de un pour une adhérence
    parfaite : faire plus que demandé ne peut pas faire moins bien."""
    grid = run(taken(*range(-89, 1)), cadence=WINDOW, window=span(-89))

    assert grid.stats.current_streak == 90


def test_a_wider_window_tolerates_a_longer_gap() -> None:
    grid = run(taken(-6), cadence="window:min_count=1;window_days=4", window=span(-6))

    assert shape(grid) == "D...MM."


def test_the_window_looks_before_the_requested_range() -> None:
    """Sans marge en amont, la première colonne d'une grille serait toujours `missed` —
    la fenêtre qui s'y referme n'aurait aucun voisin à regarder."""
    grid = run(taken(-7), cadence=WINDOW, window=span(-6))

    assert grid.days[0].state is DayState.OFF, "la veille de la plage comptait"


# ── Cadence `per_week` (`HEAT-11`, `HEAT-28`) ─────────


def test_a_weekly_track_never_misses_a_single_day() -> None:
    """`HEAT-11`. Sur une piste hebdomadaire, c'est la **semaine** qui porte le verdict :
    « torse 2×/semaine » ne dit rien sur *quel* jour."""
    grid = run(taken(-13), cadence="per_week:count=2", window=span(-13))

    assert DayState.MISSED not in {day.state for day in grid.days}
    assert set(shape(grid)) <= {".", "D"}


def test_a_week_carries_its_own_status() -> None:
    """`HEAT-28` : atteint, partiel, manqué, avec le réalisé sur l'attendu."""
    # Semaine dernière : deux séances sur deux. Semaine d'avant : une seule. Encore
    # avant : aucune.
    grid = run(taken(-13, -6, -4), cadence="per_week:count=2", window=span(-20))

    weeks = {week.week_start: week for week in grid.weeks or []}
    assert weeks[J(-14)].status is WeekStatus.PARTIAL
    assert weeks[J(-14)].done == 1
    assert weeks[J(-7)].status is WeekStatus.REACHED
    assert weeks[J(-7)].done == 2
    assert weeks[J(-21)].status is WeekStatus.MISSED


def test_the_running_week_is_never_missed() -> None:
    """Même raison qu'un jour en cours : la semaine n'a pas encore eu lieu en entier."""
    grid = run({}, cadence="per_week:count=2", window=span(-6))

    current = [week for week in grid.weeks or [] if week.week_start == J(0)]
    assert current and current[0].status is WeekStatus.PARTIAL


def test_a_week_before_the_track_is_off_not_missed() -> None:
    """`HEAT-07` au grain de la semaine. Sur une piste `per_week`, un jour non validé est
    `off` : sans marqueur d'éligibilité, une semaine vide et une semaine antérieure à la
    piste se ressembleraient trait pour trait."""
    grid = run({}, cadence="per_week:count=2", created=J(-6), window=span(-20))

    weeks = {week.week_start: week for week in grid.weeks or []}
    assert weeks[J(-21)].status is WeekStatus.OFF
    assert weeks[J(-14)].status is WeekStatus.OFF


def test_a_fully_neutralised_week_is_off() -> None:
    grid = run(
        {},
        cadence="per_week:count=2",
        off_ranges=(OffRange(J(-14), J(-8)),),
        window=span(-20),
    )

    weeks = {week.week_start: week for week in grid.weeks or []}
    assert weeks[J(-14)].status is WeekStatus.OFF
    assert weeks[J(-21)].status is WeekStatus.MISSED


def test_weekly_expectations_count_slots_not_days() -> None:
    """« Torse 2×/semaine » attend deux séances, pas sept.

    La semaine en cours est écartée du rapport : compter ses créneaux comme déjà dus
    ferait chuter le taux de respect tous les lundis matin.
    """
    grid = run(taken(-6, -5), cadence="per_week:count=2", window=span(-6))

    assert grid.stats.expected_days == 2, "une seule semaine terminée dans la plage"
    assert grid.stats.compliance == 1.0


# ── Cadence `conditional` (`HEAT-12`) ─────────────────


def test_a_conditional_track_is_only_expected_when_the_trigger_fires() -> None:
    """La cadence correcte pour un supplément péri-entraînement : il n'est pas manqué les
    jours de repos, il n'y était pas attendu."""
    grid = run(
        {},
        cadence="conditional:trigger=workout",
        triggers=(J(-5), J(-2)),
        window=span(-6),
    )

    assert shape(grid) == ".M..M.."


def test_taking_it_on_a_rest_day_is_a_bonus() -> None:
    grid = run(
        taken(-6, -5),
        cadence="conditional:trigger=workout",
        triggers=(J(-5),),
        window=span(-6),
    )

    assert shape(grid) == "BD....."


# ── Cadence `none` (`HEAT-13`) ────────────────────────


def test_a_descriptive_track_never_accuses() -> None:
    """Une piste d'observation ne doit pas se transformer en injonction."""
    grid = run(taken(-6, -3), cadence="none", window=span(-6))

    assert shape(grid) == "D..D..."
    assert grid.stats.expected_days == 0
    assert grid.stats.compliance is None, "un taux de respect sans attente n'existe pas"


# ── Intensité (`HEAT-15` → `HEAT-17`) ─────────────────

WATER = (1000.0, 1500.0, 2000.0, 2500.0)


@pytest.mark.parametrize(
    ("value", "level"),
    [(900, 0), (1000, 1), (1499, 1), (1500, 2), (2000, 3), (2500, 4), (4000, 4)],
)
def test_four_bounds_convert_a_value_into_a_level(value: float, level: int) -> None:
    assert intensity(value, TrackRules(validation_threshold=1500, levels=WATER)) == level


def test_a_validated_day_can_stay_pale() -> None:
    """`HEAT-17`, l'illustration de la spec. Validation et intensité sont découplées : le
    seuil décide vert ou rouge, les bornes décident l'intensité du vert."""
    grid = run({J(0): 1600}, threshold=1500, levels=WATER, window=span(0))

    assert grid.days[0].state is DayState.DONE
    assert grid.days[0].level == 2, "validé, mais loin des deux litres"


def test_a_missed_day_carries_no_level() -> None:
    """Un `missed` gradué se lirait comme une demi-réussite, et une grille doit se lire
    sans notice. La valeur, elle, reste là pour l'infobulle."""
    grid = run({J(-1): 1200}, threshold=1500, levels=WATER, window=span(-1))

    assert grid.days[0].state is DayState.MISSED
    assert grid.days[0].level == 0
    assert grid.days[0].value == 1200


def test_a_binary_track_has_a_single_level() -> None:
    """`HEAT-16` : une prise est une prise, il n'y a pas de gradient."""
    grid = run(taken(-1, value=3), binary=True, window=span(-1))

    assert grid.days[0].level == 1
    assert grid.stats.best_day is None, "une prise ne bat pas une prise"


def test_a_track_without_bounds_falls_back_to_binary() -> None:
    """Le fichier des pistes est éditable à la main : une colonne `levels` vidée doit
    dégrader l'intensité, pas faire tomber la grille."""
    assert run(taken(0, value=42), window=span(0)).days[0].level == 1


# ── Grille (`HEAT-24`) ────────────────────────────────


def test_the_grid_has_no_hole() -> None:
    """Le client n'a **aucun** trou à combler : les jours sans donnée sont retournés
    explicitement, jamais omis."""
    grid = run(taken(-3), window=span(-30))

    assert len(grid.days) == 31
    assert [day.date for day in grid.days] == [J(offset) for offset in range(-30, 1)]


def test_the_default_range_is_fifty_three_full_weeks() -> None:
    """`HEAT-31` et décision **D6**. Les deux conditions du backlog — 371 jours finissant
    aujourd'hui, et des semaines complètes — ne peuvent être vraies ensemble sauf un
    dimanche. L'alignement prime : une colonne tronquée se voit, un décalage d'un jour
    ne se voit pas et fausse la lecture."""
    window = default_range(TODAY)

    assert window.start.weekday() == 0, "commence un lundi"
    assert window.end.weekday() == 6, "finit un dimanche"
    assert len(window.days()) == 371


@pytest.mark.parametrize("weekday", range(7))
def test_the_default_range_stays_aligned_whatever_the_day(weekday: int) -> None:
    window = default_range(date(2026, 7, 27) + timedelta(days=weekday))

    assert window.start.weekday() == 0
    assert len(window.days()) == 371


# ── Statistiques (`HEAT-26`) ──────────────────────────


def test_compliance_is_the_share_of_expectations_met() -> None:
    grid = run(taken(-6, -5, -4, -3), window=span(-6))

    assert grid.stats.validated_days == 4
    assert grid.stats.expected_days == 6, "aujourd'hui n'est pas encore attendu"
    assert grid.stats.compliance == pytest.approx(4 / 6)


def test_a_bonus_never_pushes_compliance_past_one() -> None:
    """On ne respecte pas un engagement à cent vingt pour cent."""
    grid = run(taken(*range(-6, 1)), cadence=WINDOW, window=span(-6))

    assert grid.stats.compliance is not None
    assert grid.stats.compliance <= 1.0


def test_the_best_day_and_the_total_are_measures_not_verdicts() -> None:
    """Boire deux litres pendant une grippe reste une mesure : le cumul la porte, même si
    la journée ne compte ni comme réussite ni comme échec."""
    grid = run(
        {J(-3): 2000, J(-2): 3000, J(-1): 1000},
        threshold=1500,
        off_ranges=(OffRange(J(-2), J(-2)),),
        window=span(-3),
    )

    assert grid.stats.best_day == J(-2)
    assert grid.stats.best_value == 3000
    assert grid.stats.total == 6000


def test_measures_ignore_what_predates_the_track() -> None:
    """Le meilleur jour d'une piste créée hier ne peut pas venir de l'an dernier."""
    grid = run({J(-5): 9000, J(-1): 2000}, threshold=1500, created=J(-2), window=span(-6))

    assert grid.stats.best_day == J(-1)
    assert grid.stats.total == 2000


def test_an_empty_history_answers_without_inventing_a_figure() -> None:
    grid = run({}, cadence="none", window=span(-6))

    assert grid.stats.validated_days == 0
    assert grid.stats.compliance is None
    assert grid.stats.best_day is None
    assert grid.stats.total == 0
    assert grid.stats.current_streak == 0


# ── Séries (`HEAT-27`) ────────────────────────────────


def test_a_streak_is_broken_by_a_miss() -> None:
    grid = run(taken(-6, -5, -3, -2, -1), window=span(-6))

    assert grid.stats.current_streak == 3
    assert grid.stats.longest_streak == 3


def test_off_days_traverse_a_streak_without_extending_it() -> None:
    """« Ils n'incrémentent ni ne cassent la série. » Les `off` de queue ne comptent pas :
    on ne prend pas une avance qu'on n'a pas encore prise."""
    grid = run(taken(-6, -5), cadence="none", window=span(-6))

    assert grid.stats.current_streak == 2


def test_a_streak_ends_at_the_last_validated_day() -> None:
    grid = run(taken(-6, -4), cadence=WINDOW, window=span(-6))

    # La période court de J-6 à J-4 — le creux de J-5 la traverse sans la casser — puis
    # J-2 la referme définitivement.
    assert grid.stats.longest_streak == 3
    assert grid.stats.current_streak == 0


def test_the_longest_streak_survives_the_current_one() -> None:
    grid = run(taken(-9, -8, -7, -6, -4, -3), window=span(-9))

    assert grid.stats.longest_streak == 4
    assert grid.stats.current_streak == 0, "hier a été manqué"


# ── Cadence versionnée (`HEAT-14`) ────────────────────


def test_a_cadence_change_only_judges_from_its_effective_date() -> None:
    """`HEAT-14`. Passer la whey d'un jour sur deux à tous les jours aujourd'hui ne doit
    pas réécrire le verdict des mois passés."""
    per_day = {
        day: Cadence.parse(WINDOW if day < J(-3) else "daily") for day in [*span(-6).days(), TODAY]
    }
    grid = evaluate(
        rules=TrackRules(validation_threshold=1),
        cadence_at=per_day,
        values=taken(-6, -4),
        window=span(-6),
        today=TODAY,
    )

    assert shape(grid) == "D.DMMM."
    assert grid.days[1].state is DayState.OFF, "la fenêtre valait encore ce jour-là"
    assert grid.days[3].state is DayState.MISSED, "la règle quotidienne s'applique depuis"


# ── Propriétés (`L10-19`) ─────────────────────────────


CADENCES = ["daily", WINDOW, "per_week:count=2", "conditional:trigger=workout", "none"]


@pytest.mark.parametrize("cadence", CADENCES)
def test_no_grid_ever_contains_a_hole(cadence: str) -> None:
    grid = run(taken(-40, -20, -3), cadence=cadence, window=span(-60))

    assert len(grid.days) == 61
    assert len({day.date for day in grid.days}) == 61


@pytest.mark.parametrize("cadence", ["per_week:count=3", "none"])
def test_no_day_is_ever_missed_on_a_weekly_or_descriptive_track(cadence: str) -> None:
    """`HEAT-11`, `HEAT-13`. Un rouge quotidien sur une piste hebdomadaire serait un
    contresens : la semaine seule peut être manquée."""
    grid = run(taken(-40, -3), cadence=cadence, window=span(-60))

    assert DayState.MISSED not in {day.state for day in grid.days}


@pytest.mark.parametrize("cadence", CADENCES)
def test_a_level_is_never_carried_by_an_unvalidated_day(cadence: str) -> None:
    grid = run(taken(-40, -20, -3, value=2000), cadence=cadence, levels=WATER, window=span(-60))

    for day in grid.days:
        if day.state in (DayState.DONE, DayState.BONUS):
            assert day.level >= 1
        else:
            assert day.level == 0


@pytest.mark.parametrize("cadence", CADENCES)
def test_statistics_never_exceed_the_days_they_count(cadence: str) -> None:
    grid = run(taken(*range(-60, 1, 3)), cadence=cadence, window=span(-60))

    assert 0 <= grid.stats.validated_days <= len(grid.days)
    assert 0 <= grid.stats.current_streak <= grid.stats.longest_streak
    assert grid.stats.longest_streak <= len(grid.days)
    assert grid.stats.compliance is None or 0 <= grid.stats.compliance <= 1


@pytest.mark.parametrize("cadence", CADENCES)
def test_a_fully_neutralised_range_accuses_no_one(cadence: str) -> None:
    grid = run(
        {},
        cadence=cadence,
        off_ranges=(OffRange(J(-60), J(0)),),
        window=span(-60),
    )

    assert set(shape(grid)) == {"."}
    assert grid.stats.current_streak == 0
    assert grid.stats.compliance is None or grid.stats.expected_days == 0


# ── Nuance d'affichage d'un `off` (lot L11) ───────────
#
# Quatre situations très différentes produisent le même `off`, et se ressembleraient
# trait pour trait à l'écran sans une raison attachée à la cellule. La raison ne change
# aucun état, aucune série, aucun taux : elle dit seulement pourquoi rien n'était dû.


def reasons(grid: Grid) -> dict[date, DayReason | None]:
    return {day.date: day.reason for day in grid.days}


def test_a_day_the_cadence_did_not_ask_for_carries_no_reason() -> None:
    """Le cas ordinaire. « Rien n'était attendu ce jour-là » est déjà porté par l'état :
    y ajouter une raison inviterait le client à peindre quatre gris différents."""
    grid = run(taken(-6, -4, -2), cadence=WINDOW, window=span(-6, -1))

    assert grid.days[1].state is DayState.OFF
    assert grid.days[1].reason is None


def test_a_neutralised_day_says_it_was_neutralised() -> None:
    grid = run({}, off_ranges=(OffRange(J(-4), J(-3)),), window=span(-6, -1))

    assert reasons(grid)[J(-4)] is DayReason.NEUTRALISED
    assert reasons(grid)[J(-3)] is DayReason.NEUTRALISED
    assert reasons(grid)[J(-2)] is None, "hors de la plage neutralisée, le jour est jugé"


def test_a_day_before_the_track_says_the_track_did_not_exist() -> None:
    """`HEAT-07`. Une piste créée hier ne doit pas montrer une année de cellules qu'on
    ne distingue pas d'une année sans rien faire."""
    grid = run({}, created=J(-3), window=span(-6, -1))

    assert reasons(grid)[J(-4)] is DayReason.BEFORE_TRACK
    assert reasons(grid)[J(-3)] is None


def test_a_day_still_to_come_says_so_rather_than_looking_empty() -> None:
    grid = run({}, window=span(-1, 3))

    assert reasons(grid)[J(1)] is DayReason.FUTURE
    assert reasons(grid)[J(3)] is DayReason.FUTURE


def test_today_says_it_is_not_over_yet() -> None:
    """`HEAT-08`. La journée en cours n'est ni manquée ni à venir : elle est en train."""
    grid = run({}, window=span(-1, 0))

    assert reasons(grid)[J(0)] is DayReason.PENDING
    assert reasons(grid)[J(-1)] is None, "hier, lui, est bel et bien manqué"


def test_today_loses_its_reason_once_it_is_validated() -> None:
    grid = run(taken(0), window=span(-1, 0))

    assert grid.days[-1].state is DayState.DONE
    assert grid.days[-1].reason is None


def test_neutralisation_wins_over_every_other_reason() -> None:
    """L'ordre de priorité de `evaluate` est le même dans les deux passages du moteur.

    Un jour à la fois neutralisé, antérieur à la piste et à venir n'a qu'une raison, et
    c'est la première de la liste — sans quoi la table des jours excusés et les cellules
    peintes pourraient diverger sur ce cas limite.
    """
    grid = run({}, created=J(2), off_ranges=(OffRange(J(1), J(3)),), window=span(0, 3))

    assert reasons(grid)[J(1)] is DayReason.NEUTRALISED
    assert reasons(grid)[J(2)] is DayReason.NEUTRALISED


@pytest.mark.parametrize("cadence", CADENCES)
def test_a_reason_never_appears_on_a_day_that_counts(cadence: str) -> None:
    """La raison est réservée aux `off`. Un `done` ou un `missed` qui en porterait une
    laisserait croire qu'il ne compte pas."""
    grid = run(
        taken(*range(-30, 1, 2)),
        cadence=cadence,
        created=J(-20),
        off_ranges=(OffRange(J(-10), J(-9)),),
        window=span(-30, 2),
    )

    for day in grid.days:
        if day.state is not DayState.OFF:
            assert day.reason is None
